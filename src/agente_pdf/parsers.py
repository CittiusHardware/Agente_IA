import re
import unicodedata
from typing import Any

from agente_pdf.pdf_reader import PDFDocument, PDFPage


LOT_PATTERN = re.compile(r"\bLOTE\s*([123])\b", re.IGNORECASE)
SPEC_ITEM_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)+)\s*[-–—]\s*(.*?)\s*$")
SPEC_LOT_ITEM_PATTERN = re.compile(
    r"^\s*(Unidade\s+m[oó]vel\s+de\s+experimenta[cç][aã]o)\s*[—–-]\s*integrante\s+do\s+LOTE\s*([123])\s*$",
    re.IGNORECASE,
)
CATALOG_ITEM_PATTERN = re.compile(r"^\s*ITEM\s+(\d+)\s*[:–—-]\s*(.*?)\s*$", re.IGNORECASE)
QUANTITY_PATTERN = re.compile(
    r"(?<![\w.])(\d+(?:[,.]\d+)?)\s*(unidades?|un\.?|peças?|kits?|conjuntos?)?\b",
    re.IGNORECASE,
)
STANDALONE_QUANTITY_PATTERN = re.compile(
    r"^\s*(\d+(?:[,.]\d+)?)\s*(unidades?|un\.?|peças?|kits?|conjuntos?)?\s*$",
    re.IGNORECASE,
)
LEADING_COMPONENT_PATTERN = re.compile(
    r"^\s*(\d+(?:[,.]\d+)?)\s+(?:(unidades?|un\.?|peças?|kits?|conjuntos?)\s+)?(?:(?:de|do|da|dos|das)\s+)?(.+?)\s*$",
    re.IGNORECASE,
)
COMPONENT_PATTERN = re.compile(r"^\s*[-•]\s*(.+?)\s*$")
NUMERIC_WORD_PATTERN = re.compile(r"^\d+(?:[,.]\d+)?$")
QUANTITY_WITH_UNIT_PATTERN = re.compile(
    r"(?<![\w.])(\d+(?:[,.]\d+)?)\s*(unidades?|un\.?|peças?|kits?|conjuntos?)(?!\w)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value)
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", value).strip().lower()


def _quantity_from_match(match: re.Match[str]) -> dict[str, Any]:
    number = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    return {"valor": int(number) if number.is_integer() else number, "unidade": unit}


def _quantity(value: str) -> dict[str, Any] | None:
    match = QUANTITY_PATTERN.search(value or "")
    return _quantity_from_match(match) if match else None


def _standalone_quantity(value: str) -> dict[str, Any] | None:
    match = STANDALONE_QUANTITY_PATTERN.fullmatch(value or "")
    return _quantity_from_match(match) if match else None


def _leading_component(value: str) -> dict[str, Any] | None:
    match = LEADING_COMPONENT_PATTERN.match(value or "")
    if not match:
        return None
    return {
        "descricao": match.group(3).strip(),
        "quantidade": {
            "valor": int(float(match.group(1).replace(",", ".")))
            if float(match.group(1).replace(",", ".")).is_integer()
            else float(match.group(1).replace(",", ".")),
            "unidade": match.group(2),
        },
    }


def parse_specification(document: PDFDocument, target_lot: int) -> dict[str, Any]:
    """Collect numbered technical items and their explicit quantity lines."""
    current_lot = None
    items: list[dict[str, Any]] = []
    current_item: dict[str, Any] | None = None
    current_component: dict[str, Any] | None = None
    lot_found = False

    for page in document.pages:
        for line in page.text.splitlines():
            lot_match = LOT_PATTERN.search(_normalize(line))
            if lot_match:
                current_lot = int(lot_match.group(1))
                lot_found = lot_found or current_lot == target_lot
                current_item = None
                current_component = None

            item_match = SPEC_ITEM_PATTERN.match(line)
            if item_match:
                current_item = None
                current_component = None
                if current_lot == target_lot:
                    current_item = {
                        "lote": current_lot,
                        "codigo": item_match.group(1),
                        "descricao": item_match.group(2).strip(),
                        "texto_detalhado": item_match.group(2).strip(),
                        "quantidade_por_ambiente": None,
                        "componentes": [],
                        "pagina": page.number,
                    }
                    items.append(current_item)
                continue

            # Some lot-level deliverables have a titled heading and quantity,
            # but no numbered code such as 1.1. Keep this explicit mobile-unit
            # section as an item so it can be paired to its catalog title.
            lot_item_match = SPEC_LOT_ITEM_PATTERN.match(line)
            if lot_item_match:
                current_item = None
                current_component = None
                item_lot = int(lot_item_match.group(2))
                if item_lot == target_lot:
                    current_item = {
                        "lote": item_lot,
                        "codigo": f"{item_lot}.unidade_movel",
                        "descricao": lot_item_match.group(1).strip(),
                        "texto_detalhado": lot_item_match.group(1).strip(),
                        "quantidade_por_ambiente": None,
                        "componentes": [],
                        "pagina": page.number,
                    }
                    items.append(current_item)
                continue

            if current_item is None:
                continue

            detail_line = line.strip()
            if detail_line:
                current_item["texto_detalhado"] += "\n" + detail_line

            if (
                "quantidade por ambiente" in _normalize(line)
                or re.match(r"^\s*quantidade\s*:", _normalize(line))
            ):
                current_item["quantidade_por_ambiente"] = _quantity(line)
                current_item["pagina_quantidade"] = page.number
                current_component = None
                continue

            component_match = COMPONENT_PATTERN.match(line)
            if component_match:
                component_text = component_match.group(1).strip()
                component = _leading_component(component_text)
                if component:
                    component.update({"pagina": page.number, "evidencia": component_text})
                    current_item["componentes"].append(component)
                    current_component = component
                else:
                    current_component = None
                continue

            # PDF extraction often wraps a component across physical lines. Keep
            # those continuation lines with the quantity-bearing component until
            # the next bullet, item, lot, or per-environment quantity line.
            normalized_line = _normalize(line)
            if current_component and normalized_line:
                continuation_key = re.sub(r"[^a-z0-9]+", " ", normalized_line).strip()
                if (
                    re.fullmatch(r"\d+", continuation_key)
                    or continuation_key.startswith(("tr solucoes educacionais", "pagina "))
                    or re.fullmatch(r"(?:www\.)?\S+\.\S+", normalized_line)
                ):
                    continue
                continuation = line.strip()
                current_component["descricao"] += " " + continuation
                current_component["evidencia"] += " " + continuation

    return {
        "lote_solicitado": target_lot,
        "lote_encontrado": lot_found,
        "itens": items,
    }


def _table_columns(table: tuple[tuple[str, ...], ...]) -> tuple[int, int, int] | None:
    for row_index, row in enumerate(table):
        normalized = [_normalize(cell) for cell in row]
        description_index = next((i for i, cell in enumerate(normalized) if "descri" in cell), None)
        quantity_index = next((i for i, cell in enumerate(normalized) if "qtd" in cell or "quant" in cell), None)
        if description_index is not None and quantity_index is not None:
            return row_index, description_index, quantity_index
    return None


def _catalog_component_row(
    row: tuple[str, ...],
    description_index: int,
    quantity_index: int,
    fallback_quantity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    cells = [cell.strip() for cell in row]
    if max(description_index, quantity_index) >= len(cells):
        return None

    # In many catalog PDFs, the table extractor places the product title, an
    # isolated Qtd value, and the descriptive text in the same cell. Only an
    # isolated number is treated as the table quantity; numbers embedded in
    # phrases such as "caixa com 100 unidades" remain product details.
    quantity = _standalone_quantity(cells[quantity_index])
    if quantity is None:
        for cell in cells:
            for line in cell.splitlines():
                quantity = _standalone_quantity(line)
                if quantity is not None:
                    break
            if quantity is not None:
                break

    if quantity is None:
        quantity = fallback_quantity

    description_parts: list[str] = []
    for index, cell in enumerate(cells):
        if index == quantity_index and _standalone_quantity(cell) is not None:
            continue
        for line in cell.splitlines():
            line = line.strip()
            if not line or _standalone_quantity(line) is not None:
                continue
            if re.search(r"[A-Za-zÀ-ÿ]", line):
                description_parts.append(line)

    description = re.sub(r"\s+", " ", " ".join(description_parts)).strip()
    if description and quantity:
        return {"descricao": description, "quantidade": quantity}
    return None


def _catalog_component_without_header(
    row: tuple[str, ...],
    fallback_quantity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Extract a continued catalog-table row when its header is not repeated."""
    cells = [cell.strip() for cell in row if cell and cell.strip()]
    if not cells:
        return None

    quantity = None
    quantity_line = None
    for cell in cells:
        for line in cell.splitlines():
            candidate = _standalone_quantity(line)
            if candidate is not None:
                quantity = candidate
                quantity_line = line.strip()
                break
        if quantity is not None:
            break

    # Some extracted rows put a lone final Qtd on the same line as the title.
    # Accept only a trailing integer on the first title line, never numbers in
    # the descriptive text or package-size phrases.
    if quantity is None and len(cells) == 1:
        lines = [line.strip() for line in cells[0].splitlines() if line.strip()]
        if lines:
            match = re.fullmatch(r"(.+?)\s+(\d+)", lines[0])
            if match and re.search(r"[A-Za-zÀ-ÿ]", match.group(1)):
                quantity = _standalone_quantity(match.group(2))
                if quantity:
                    quantity_line = match.group(2)
                    lines[0] = match.group(1).strip()
                    cells = ["\n".join(lines)]

    if quantity is None:
        quantity = fallback_quantity
    if quantity is None:
        return None

    description_parts = []
    for cell in cells:
        for line in cell.splitlines():
            line = line.strip()
            if not line or _standalone_quantity(line) is not None:
                continue
            if quantity_line and line == quantity_line:
                continue
            if re.search(r"[A-Za-zÀ-ÿ]", line):
                description_parts.append(line)
    description = re.sub(r"\s+", " ", " ".join(description_parts)).strip()
    if not description:
        return None
    return {"descricao": description, "quantidade": quantity}


def _header_word(words: tuple[dict[str, Any], ...], kind: str) -> dict[str, Any] | None:
    for word in words:
        normalized = _normalize(word["text"])
        if kind == "description" and "descri" in normalized:
            return word
        if kind == "quantity" and ("qtd" in normalized or "quant" in normalized):
            return word
    return None


def _coordinate_components(page: PDFPage) -> list[dict[str, Any]]:
    """Read catalog rows by geometry, using headers or a continued-table layout."""
    description_header = _header_word(page.words, "description")
    quantity_header = _header_word(page.words, "quantity")
    valid_header = bool(
        description_header
        and quantity_header
        and abs(description_header["top"] - quantity_header["top"]) <= 8
    )
    table_rows = None
    description_left = 0.0
    if valid_header:
        description_left = max(0, description_header["x0"] - 18)
        quantity_left = quantity_header["x0"] - 18
        start_y = max(description_header["bottom"], quantity_header["bottom"]) + 2
        header_y = (description_header["top"] + description_header["bottom"]) / 2
        for bounds in page.table_row_bounds:
            if any(top <= header_y <= bottom for top, bottom in bounds):
                table_rows = bounds
                break
    elif page.table_row_bounds and page.table_bounds:
        # Catalog tables often continue on the next page without repeating the
        # header. In those pages the quantity column is the narrow rightmost part
        # of the detected table; never infer it from numbers in the description.
        table_index = max(
            range(min(len(page.table_row_bounds), len(page.table_bounds))),
            key=lambda index: len(page.table_row_bounds[index]),
        )
        table_rows = page.table_row_bounds[table_index]
        table_left, table_top, table_right, _ = page.table_bounds[table_index]
        description_left = table_left
        quantity_left = table_right - (table_right - table_left) * 0.16
        start_y = table_top - 1
    else:
        return []

    if table_rows:
        components = []
        for row_top, row_bottom in table_rows:
            if row_bottom <= start_y:
                continue
            row_words = [
                word for word in page.words
                if row_top <= (word["top"] + word["bottom"]) / 2 < row_bottom
            ]
            quantity_words = [
                word for word in row_words
                if word["x0"] >= quantity_left
                and NUMERIC_WORD_PATTERN.fullmatch(word["text"].strip())
            ]
            quantity_word = max(
                quantity_words, key=lambda word: (word["x1"], word["x0"]), default=None
            )
            description_words = [
                word for word in row_words
                if description_left <= (word["x0"] + word["x1"]) / 2
                and (quantity_word is None or word["x0"] < quantity_word["x0"])
                and (
                    re.search(r"[A-Za-zÀ-ÿ]", word["text"])
                    or NUMERIC_WORD_PATTERN.fullmatch(word["text"].strip())
                )
            ]
            description = " ".join(
                word["text"] for word in sorted(
                    description_words, key=lambda word: (word["top"], word["x0"])
                )
            ).strip()
            if description and quantity_word:
                # The Qtd column is the rightmost numeric token in the row.
                # Earlier numeric tokens belong to the description and may be
                # dimensions close to the Qtd column.
                quantity = _quantity(quantity_word["text"])
                if quantity:
                    components.append({
                        "descricao": description,
                        "quantidade": quantity,
                        "pagina": page.number,
                        "evidencia": f"{description} | {quantity_word['text']}",
                    })
        return components

    body_words = [word for word in page.words if word["top"] > start_y]
    body_words.sort(key=lambda word: (word["top"], word["x0"]))

    lines: list[list[dict[str, Any]]] = []
    for word in body_words:
        if not lines or word["top"] - lines[-1][0]["top"] > 3:
            lines.append([word])
        else:
            lines[-1].append(word)

    pending_description: list[str] = []
    components = []
    for line in lines:
        line.sort(key=lambda word: word["x0"])
        quantity_word = max(
            (word for word in line if word["x0"] >= quantity_left and NUMERIC_WORD_PATTERN.fullmatch(word["text"].strip())),
            key=lambda word: (word["x1"], word["x0"]),
            default=None,
        )
        description_words = [
            word["text"] for word in line
            if description_left <= (word["x0"] + word["x1"]) / 2
            and (quantity_word is None or word["x0"] < quantity_word["x0"])
            and (
                re.search(r"[A-Za-zÀ-ÿ]", word["text"])
                or NUMERIC_WORD_PATTERN.fullmatch(word["text"].strip())
            )
        ]
        if description_words:
            pending_description.extend(description_words)
        if quantity_word is None:
            continue

        description = " ".join(pending_description).strip()
        if quantity_word is None:
            continue
        quantity = _quantity(quantity_word["text"])
        if description and quantity:
            components.append({
                "descricao": description,
                "quantidade": quantity,
                "pagina": page.number,
                "evidencia": f"{description} | {quantity_word['text']}",
            })
        pending_description = []

    return components


def _remove_quantity_column_artifact(
    description: str, quantity: dict[str, Any] | None
) -> str:
    """Remove a Qtd token accidentally inserted between a measure and its unit."""
    if not quantity:
        return description
    try:
        value = float(quantity["valor"])
    except (KeyError, TypeError, ValueError):
        return description
    if not value.is_integer():
        return description

    quantity_token = str(int(value))
    pattern = re.compile(
        rf"(?<![\w.])(?P<measure>\d+(?:[,.]\d+)?)\s+{quantity_token}"
        r"(?=\s*(?:mm|cm|m)\b)",
        re.IGNORECASE,
    )
    return pattern.sub(r"\g<measure>", description)


def _add_components(item: dict[str, Any], components: list[dict[str, Any]]) -> None:
    existing = {
        (_normalize(component["descricao"]), component["quantidade"]["valor"], component["pagina"])
        for component in item["componentes"]
    }
    for source_component in components:
        component = dict(source_component)
        component["descricao"] = _remove_quantity_column_artifact(
            component["descricao"], component.get("quantidade")
        )
        key = (_normalize(component["descricao"]), component["quantidade"]["valor"], component["pagina"])
        if key not in existing:
            item["componentes"].append(component)
            existing.add(key)


def _looks_like_catalog_contents(page: PDFPage) -> bool:
    """Ignore a navigation page listing many item titles without item data."""
    headings = [
        line for line in page.text.splitlines()
        if CATALOG_ITEM_PATTERN.match(line)
    ]
    if len(headings) < 5:
        return False

    has_table_header = any(_table_columns(table) is not None for table in page.tables)
    has_coordinate_header = _has_catalog_component_columns(page)
    has_body_quantity = any(
        QUANTITY_WITH_UNIT_PATTERN.search(line)
        for line in page.text.splitlines()
        if not CATALOG_ITEM_PATTERN.match(line)
    )
    return not has_table_header and not has_coordinate_header and not has_body_quantity


def _has_catalog_component_columns(page: PDFPage) -> bool:
    description_header = _header_word(page.words, "description")
    quantity_header = _header_word(page.words, "quantity")
    return bool(
        description_header
        and quantity_header
        and abs(description_header["top"] - quantity_header["top"]) <= 8
    )


def parse_catalog(document: PDFDocument) -> dict[str, Any]:
    """Collect catalog headings and component rows from tables or page coordinates."""
    items: list[dict[str, Any]] = []
    unassigned_tables: list[dict[str, Any]] = []
    current_item: dict[str, Any] | None = None
    title_continuation_pending = False
    title_connectors = {"de", "da", "do", "das", "dos", "para", "com", "em", "e"}
    table_header_lines = {"imagem descricao qtd", "imagem descricao quantidade"}

    for page in document.pages:
        if _looks_like_catalog_contents(page):
            # Prevent index entries from becoming data items and owning tables on
            # following pages before the first real catalog item appears.
            current_item = None
            title_continuation_pending = False
            continue

        page_items: list[dict[str, Any]] = []
        has_tabular_component_structure = bool(page.tables) or _has_catalog_component_columns(page)
        for line in page.text.splitlines():
            item_match = CATALOG_ITEM_PATTERN.match(line)
            if item_match:
                item_title = item_match.group(2).strip()
                title_continuation_pending = bool(
                    item_title
                    and _normalize(item_title).split()[-1] in title_connectors
                )
                current_item = {
                    "codigo": item_match.group(1),
                    "descricao": item_title,
                    "texto_detalhado": item_match.group(2).strip(),
                    "quantidade_do_conjunto": None,
                    "componentes": [],
                    "pagina": page.number,
                }
                items.append(current_item)
                page_items.append(current_item)
                continue

            if current_item is not None and title_continuation_pending:
                continuation = line.strip()
                title_continuation_pending = False
                if (
                    continuation
                    and continuation.isupper()
                    and any(character.isalpha() for character in continuation)
                    and _normalize(continuation) not in table_header_lines
                ):
                    current_item["descricao"] += " " + continuation
                    current_item["texto_detalhado"] += "\n" + continuation
                    continue

            if current_item is not None and line.strip():
                current_item["texto_detalhado"] += "\n" + line.strip()

            if current_item is not None and current_item["quantidade_do_conjunto"] is None:
                quantity = _standalone_quantity(line)
                if quantity:
                    current_item["quantidade_do_conjunto"] = quantity
                    current_item["pagina_quantidade"] = page.number
                    continue

            # Some later catalog pages use plain text instead of a detected table:
            # description first, followed by an explicit quantity and unit.
            if current_item is not None and not has_tabular_component_structure:
                quantity_match = QUANTITY_WITH_UNIT_PATTERN.search(line)
                if quantity_match:
                    description = line[:quantity_match.start()].strip(" \t:;,-–—")
                    if (
                        re.search(r"[A-Za-zÀ-ÿ]{2}", description)
                        and not re.fullmatch(r"(?:qtd|quantidade)", _normalize(description))
                    ):
                        quantity = {
                            "valor": float(quantity_match.group(1).replace(",", ".")),
                            "unidade": quantity_match.group(2),
                        }
                        if quantity["valor"].is_integer():
                            quantity["valor"] = int(quantity["valor"])
                        current_item["componentes"].append({
                            "descricao": description,
                            "quantidade": quantity,
                            "pagina": page.number,
                            "evidencia": line.strip(),
                        })

        table_owner = page_items[0] if len(page_items) == 1 else None
        if not page_items and current_item is not None:
            table_owner = current_item

        coordinate_rows = _coordinate_components(page)
        extracted_table_rows: list[dict[str, Any]] = []
        # Tables before the first ITEM heading (for example the catalog index)
        # have no catalog-item context and must not be counted as components.
        if table_owner is None and current_item is None:
            continue
        for table in page.tables:
            columns = _table_columns(table)
            if columns is not None:
                header_index, description_index, quantity_index = columns
                table_data_rows = list(table[header_index + 1:])
                rows = []
                for row_index, row in enumerate(table_data_rows):
                    fallback_quantity = (
                        coordinate_rows[row_index]["quantidade"]
                        if len(coordinate_rows) == len(table_data_rows)
                        else None
                    )
                    component = _catalog_component_row(
                        row, description_index, quantity_index, fallback_quantity
                    )
                    # The table cell provides the full product title and text;
                    # the rightmost Qtd column, read by coordinates, is the
                    # source of truth for the row quantity.
                    if len(coordinate_rows) == len(table_data_rows):
                        if component is None:
                            component = {"descricao": "", "quantidade": coordinate_rows[row_index]["quantidade"]}
                        else:
                            coordinate_description = coordinate_rows[row_index]["descricao"]
                            table_tokens = re.findall(r"[a-z0-9]+", _normalize(component["descricao"]))
                            coordinate_tokens = re.findall(r"[a-z0-9]+", _normalize(coordinate_description))
                            quantity_value = coordinate_rows[row_index]["quantidade"]["valor"]
                            quantity_token = str(int(quantity_value)) if float(quantity_value).is_integer() else str(quantity_value)
                            # Use coordinate text only when removing exactly one Qtd token
                            # makes it identical to the full table text. This avoids
                            # cutting fractions, inches, or words from the table cell.
                            for token_index, token in enumerate(table_tokens):
                                if token == quantity_token and (
                                    table_tokens[:token_index] + table_tokens[token_index + 1:]
                                    == coordinate_tokens
                                ):
                                    component["descricao"] = coordinate_description
                                    break
                            component["quantidade"] = coordinate_rows[row_index]["quantidade"]
                    if component and component["descricao"]:
                        component.update({"pagina": page.number, "evidencia": " | ".join(row)})
                        rows.append(component)
            else:
                rows = []
                table_data_rows = list(table)
                for row_index, row in enumerate(table_data_rows):
                    fallback_quantity = (
                        coordinate_rows[row_index]["quantidade"]
                        if len(coordinate_rows) == len(table_data_rows)
                        else None
                    )
                    component = _catalog_component_without_header(row, fallback_quantity)
                    if len(coordinate_rows) == len(table_data_rows):
                        if component is None:
                            component = {"descricao": "", "quantidade": coordinate_rows[row_index]["quantidade"]}
                        else:
                            coordinate_description = coordinate_rows[row_index]["descricao"]
                            table_tokens = re.findall(r"[a-z0-9]+", _normalize(component["descricao"]))
                            coordinate_tokens = re.findall(r"[a-z0-9]+", _normalize(coordinate_description))
                            quantity_value = coordinate_rows[row_index]["quantidade"]["valor"]
                            quantity_token = str(int(quantity_value)) if float(quantity_value).is_integer() else str(quantity_value)
                            # Use coordinate text only when removing exactly one Qtd token
                            # makes it identical to the full table text. This avoids
                            # cutting fractions, inches, or words from the table cell.
                            for token_index, token in enumerate(table_tokens):
                                if token == quantity_token and (
                                    table_tokens[:token_index] + table_tokens[token_index + 1:]
                                    == coordinate_tokens
                                ):
                                    component["descricao"] = coordinate_description
                                    break
                            component["quantidade"] = coordinate_rows[row_index]["quantidade"]
                    if component and component["descricao"]:
                        component.update({"pagina": page.number, "evidencia": " | ".join(row)})
                        rows.append(component)
            extracted_table_rows.extend(rows)
            if table_owner is not None:
                _add_components(table_owner, rows)
            elif rows and current_item is not None:
                unassigned_tables.append({"pagina": page.number, "linhas": rows})

        # Coordinate extraction usually stays a fallback because combining
        # both strategies can create partial duplicates. When it finds more
        # rows than the table parser, however, the table extraction is
        # incomplete (often because quantities are embedded between text lines).
        # Replace this page's table rows with the coordinate rows in that case.
        if coordinate_rows and len(coordinate_rows) > len(extracted_table_rows):
            page_owner = table_owner or current_item
            if page_owner is not None:
                page_owner["componentes"] = [
                    component for component in page_owner["componentes"]
                    if component.get("pagina") != page.number
                ]
                _add_components(page_owner, coordinate_rows)
            else:
                unassigned_tables = [
                    table for table in unassigned_tables
                    if table.get("pagina") != page.number
                ]
                unassigned_tables.append({"pagina": page.number, "linhas": coordinate_rows})
        elif not extracted_table_rows and coordinate_rows:
            if table_owner is not None:
                _add_components(table_owner, coordinate_rows)
            elif current_item is not None:
                unassigned_tables.append({"pagina": page.number, "linhas": coordinate_rows})

    return {"itens": items, "tabelas_sem_item_vinculado": unassigned_tables}
