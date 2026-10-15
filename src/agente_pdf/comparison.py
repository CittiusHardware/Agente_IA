"""Compare catalog claims with the paired technical item, locally."""

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any


STOPWORDS = {
    "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos",
    "e", "em", "na", "nas", "no", "nos", "o", "os", "para", "por",
    "p", "sem", "um", "uma", "uns", "umas",
}
COMPONENT_IDENTITY_THRESHOLD = 0.55
NAME_WEIGHT = 0.45
QUANTITY_WEIGHT = 0.45
DETAIL_WEIGHT = 0.10
ITEM_TITLE_THRESHOLD = 0.40


def _tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    ).lower()
    # Keep capacities and measures comparable whether the PDF joins the unit
    # to the number ("50ml") or separates them ("50 ml").
    normalized = re.sub(r"(?<=\d)(?=[a-z])", " ", normalized)
    aliases = {
        "pinceis": "pincel",
        "organizadora": "armazenamento",
        "organizadoras": "armazenamento",
        "organizadores": "armazenamento",
        "organizador": "armazenamento",
        "massas": "massa",
        "aferidas": "aferida",
        "copos": "copo",
        "medidores": "medidor",
        "jogos": "jogo",
        "dados": "dado",
        "tubos": "tubo",
    }
    tokens = [
        aliases.get(token, token)
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in STOPWORDS
    ]
    if "realidade aumentada" in normalized:
        tokens.append("ra")
    return tokens


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    ).lower()
    return re.sub(r"\s+", " ", normalized).strip()


def _dimension_values_mm(
    value: str, quantity: dict[str, Any] | None = None
) -> list[int]:
    """Extract explicit metric dimensions and normalize them to millimeters."""
    text = _fold_text(value)
    # A table quantity can be interleaved into a measurement by PDF extraction,
    # for example "150 4 mm" when the row quantity is 4.
    if quantity is not None:
        try:
            quantity_value = float(quantity["valor"])
        except (KeyError, TypeError, ValueError):
            quantity_value = None
        if quantity_value is not None and quantity_value.is_integer():
            quantity_token = str(int(quantity_value))
            text = re.sub(
                rf"(?<![\w.])(?P<measure>\d+(?:[,.]\d+)?)\s+{quantity_token}"
                r"(?=\s*(?:mm|cm|m)\b)",
                r"\g<measure>",
                text,
            )
    # PDF text extraction can interleave page-number artifacts into "20 cm",
    # producing strings such as "20 a n cm". Remove that artifact only when
    # it occurs between a number and a metric unit.
    text = re.sub(r"(?<=\d)\s+a\s+n(?=\s*(?:mm|cm|m)\b)", " ", text)
    values: list[int] = []
    unit_to_mm = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
    number = r"([0-9]+(?:[,.][0-9]+)?)"
    unit = r"(mm|cm|m)?"
    chain_pattern = re.compile(
        rf"(?<![\w]){number}\s*{unit}\s*[x×]\s*{number}\s*{unit}\s*[x×]\s*"
        rf"{number}\s*(mm|cm|m)(?![a-z])"
    )
    chain_spans: list[tuple[int, int]] = []
    for match in chain_pattern.finditer(text):
        first, first_unit, second, second_unit, third, third_unit = match.groups()
        units = [first_unit, second_unit, third_unit]
        for index in (1, 0):
            if not units[index]:
                units[index] = units[index + 1]
        values.extend([
            round(float(first.replace(",", ".")) * unit_to_mm[units[0]]),
            round(float(second.replace(",", ".")) * unit_to_mm[units[1]]),
            round(float(third.replace(",", ".")) * unit_to_mm[units[2]]),
        ])
        chain_spans.append(match.span())

    pair_pattern = re.compile(
        rf"(?<![\w]){number}\s*{unit}\s*[x×]\s*{number}\s*(mm|cm|m)(?![a-z])"
    )
    for match in pair_pattern.finditer(text):
        if any(start <= match.start() < end for start, end in chain_spans):
            continue
        first, first_unit, second, second_unit = match.groups()
        first_unit = first_unit or second_unit
        values.extend([
            round(float(first.replace(",", ".")) * unit_to_mm[first_unit]),
            round(float(second.replace(",", ".")) * unit_to_mm[second_unit]),
        ])

    labeled_pattern = re.compile(
        r"\b(?:comprimento|largura|altura|diametro|profundidade|espessura|d)\s*"
        r"(?:aproximad[oa]s?\s*)?(?:de\s*)?[:=]?\s*"
        r"([0-9]+(?:[,.][0-9]+)?)\s*(mm|cm|m)\b"
    )
    parsed_spans = list(chain_spans)
    for match in pair_pattern.finditer(text):
        if any(start <= match.start() < end for start, end in chain_spans):
            continue
        parsed_spans.append(match.span())
    for match in labeled_pattern.finditer(text):
        dimension_number, dimension_unit = match.groups()
        values.append(round(float(dimension_number.replace(",", ".")) * unit_to_mm[dimension_unit]))
        parsed_spans.append(match.span())

    # Keep isolated metric measurements too (for example "Ø 20 mm", "30 cm"
    # or "15 cm de comprimento"). PDF tables often separate the number from
    # its label or omit a multiplication sign, so relying only on x/× pairs
    # silently drops valid dimensions. Skip spans already consumed above to
    # avoid counting the same measurement twice.
    standalone_pattern = re.compile(rf"(?<![\w.]){number}\s*(mm|cm|m)(?![a-z])")
    for match in standalone_pattern.finditer(text):
        if any(start <= match.start() < end for start, end in parsed_spans):
            continue
        value, unit = match.groups()
        values.append(round(float(value.replace(",", ".")) * unit_to_mm[unit]))
        parsed_spans.append(match.span())
    return values


def _dimension_scope(value: str) -> str:
    """Limit item-level dimension checks to the passage labeled as dimensions."""
    match = re.search(r"\bdimens(?:ao|oes)\b", _fold_text(value))
    if not match:
        return value

    scope = value[match.start():]
    boundary = re.search(
        r"(?:\n\s*[✓✔•]\s*|;\s*(?:peso|alimentacao|autonomia|garantia|material)\b)",
        scope,
        re.IGNORECASE,
    )
    return scope[:boundary.start()] if boundary else scope


def _catalog_dimensions_supported(
    catalog_text: str,
    spec_text: str,
    catalog_quantity: dict[str, Any] | None = None,
) -> bool | None:
    catalog_values = _dimension_values_mm(catalog_text, catalog_quantity)
    spec_values = _dimension_values_mm(spec_text)
    if not catalog_values or not spec_values:
        return None
    catalog_counts = Counter(catalog_values)
    spec_counts = Counter(spec_values)
    return all(spec_counts[value] >= count for value, count in catalog_counts.items())


def _piece_count_claims(value: str) -> list[dict[str, Any]]:
    """Extract exact or minimum counts of internal pieces/parts with context."""
    text = _fold_text(value)
    pattern = re.compile(
        r"(?:(?P<minimum>no\s+minimo|minimo\s+de|pelo\s+menos)\s+)?"
        r"(?P<count>\d+)\s+(?P<unit>pecas?|partes?|poliedros?)\b"
    )
    claims = []
    for match in pattern.finditer(text):
        unit = match.group("unit")
        if unit.startswith("poliedro"):
            after = text[match.end():]
            modifier_match = re.match(r"\s+([a-z]+)", after)
            modifier = modifier_match.group(1) if modifier_match else ""
            context = " ".join(part for part in ("poliedro", modifier) if part)
        else:
            before = text[max(0, match.start() - 48):match.start()]
            context_tokens = _tokens(before)
            context = " ".join(context_tokens[-2:])
        if not context:
            continue
        claims.append({
            "contexto": context,
            "quantidade": int(match.group("count")),
            "minima": bool(match.group("minimum")),
        })
    return claims


def _piece_count_conflicts(catalog_text: str, spec_text: str) -> list[tuple[str, int, int]]:
    catalog_claims = _piece_count_claims(catalog_text)
    spec_claims = _piece_count_claims(spec_text)
    conflicts = []
    for catalog_claim in catalog_claims:
        matching_spec = next(
            (
                claim for claim in spec_claims
                if claim["contexto"] == catalog_claim["contexto"]
            ),
            None,
        )
        if matching_spec is None:
            continue
        if catalog_claim["minima"] and matching_spec["quantidade"] >= catalog_claim["quantidade"]:
            continue
        if matching_spec["quantidade"] != catalog_claim["quantidade"]:
            conflicts.append((
                catalog_claim["contexto"],
                catalog_claim["quantidade"],
                matching_spec["quantidade"],
            ))
    return conflicts


def _match_features(
    catalog_description: str,
    specification_description: str,
) -> tuple[float, float]:
    """Return keyword identity and low-weight detail similarity scores."""
    catalog_tokens = _tokens(catalog_description)
    specification_tokens = _tokens(specification_description)
    if not catalog_tokens or not specification_tokens:
        return 0.0, 0.0

    catalog_keywords = catalog_tokens[:3]
    specification_keywords = specification_tokens[:3]
    keyword_score = (
        len(set(catalog_keywords) & set(specification_keywords))
        / max(1, len(set(catalog_keywords)))
    )

    catalog_text = " ".join(catalog_tokens)
    specification_text = " ".join(specification_tokens)
    detail_coverage = (
        len(set(catalog_tokens) & set(specification_tokens))
        / max(1, len(set(catalog_tokens)))
    )
    detail_sequence = SequenceMatcher(None, catalog_text, specification_text).ratio()
    return keyword_score, max(detail_coverage, detail_sequence)


def _component_name_tokens(component: dict[str, Any]) -> set[str]:
    """Use the catalog row's leading product name as the strongest identity cue."""
    description = component.get("descricao", "")
    # Catalog rows commonly put the product name before check-marked details.
    name = re.split(r"[✓|]", description, maxsplit=1)[0]
    # Some catalogs omit a separator between the displayed name and its first
    # sentence ("Ciclo de Vida do Sapo Placa em resina..."). Keep the opening
    # identifying words so later technical details do not dilute the name.
    generic_descriptors = {
        "instrumento", "musical", "tipo", "frasco", "rolo", "escolar",
        "professor", "confeccionado", "confeccionada",
    }
    raw_tokens = _tokens(name)
    tokens = [token for token in raw_tokens if token not in generic_descriptors]
    identifying_tokens = set(tokens[:3])
    # Preserve explicit variants that distinguish otherwise identical products.
    if "aluno" in raw_tokens:
        identifying_tokens.add("aluno")
    if "professor" in raw_tokens and "versao" in raw_tokens:
        identifying_tokens.add("professor")
    return identifying_tokens


def _component_variant_conflict(catalog_component: dict[str, Any], spec_component: dict[str, Any]) -> bool:
    catalog_name = _component_name_tokens(catalog_component)
    spec_lead = set(_tokens(spec_component.get("descricao", ""))[:12])
    if (
        ("professor" in catalog_name and "aluno" in spec_lead and "professor" not in spec_lead)
        or ("aluno" in catalog_name and "professor" in spec_lead and "aluno" not in spec_lead)
    ):
        return True

    color_variants = {
        "amarelo", "azul", "branco", "incolor", "laranja", "marrom",
        "preto", "rosa", "roxo", "verde", "vermelho",
    }
    catalog_colors = catalog_name & color_variants
    spec_colors = set(_tokens(spec_component.get("descricao", ""))) & color_variants
    return bool(catalog_colors and spec_colors and catalog_colors.isdisjoint(spec_colors))


def _component_attribute_conflict(catalog_component: dict[str, Any], spec_component: dict[str, Any]) -> bool:
    catalog_text = _fold_text(catalog_component.get("descricao", ""))
    spec_text = _fold_text(spec_component.get("descricao", ""))
    opposites = (("sem furo", "com furo"), ("sem tampa", "com tampa"))
    return any(
        (left in catalog_text and right in spec_text)
        or (right in catalog_text and left in spec_text)
        for left, right in opposites
    )


def _name_coverage(catalog_component: dict[str, Any], spec_component: dict[str, Any]) -> float:
    name_tokens = _component_name_tokens(catalog_component)
    spec_text = _fold_text(spec_component.get("descricao", ""))
    spec_tokens = _tokens(spec_text)
    if not name_tokens or not spec_tokens:
        return 0.0

    # This catalog calls the science app an "ambiente virtualizado"; the
    # specification describes the same science-content app by its function.
    if (
        {"ambiente", "virtualizado", "ciencias"}.issubset(name_tokens)
        and "aplicativo" in spec_tokens
        and "ciencias" in spec_tokens
    ):
        return 1.0

    # In some specifications the catalog's "Ambiente Virtualizado de
    # Matemática" appears as an image-recognition app with math content.
    if (
        {"ambiente", "virtualizado", "matematica"}.issubset(name_tokens)
        and {"aplicativo", "matematica", "reconhecimento", "imagem"}.issubset(spec_tokens)
    ):
        return 1.0

    # "Copos medidores" and "conjunto de copo de medidas" are equivalent
    # names for the same graduated polypropylene measuring-cup set.
    if (
        {"copo", "medidor"}.issubset(name_tokens)
        and "copo" in spec_tokens
        and "medidas" in spec_tokens
    ):
        return 1.0

    # RA is commonly written out as "realidade aumentada" in the technical
    # description. Treat that explicit phrase as support for the acronym.
    if (
        {"cartao", "ativacao", "ra"}.issubset(name_tokens)
        and "cartao" in spec_tokens
        and "ativacao" in spec_tokens
        and "realidade aumentada" in spec_text
    ):
        return 1.0

    # Require the product-name words to occur near one another. Counting hits
    # across the entire paragraph let unrelated mentions (e.g. "caixa" in one
    # sentence and "armazenamento" much later) create a false match.
    window_size = min(len(spec_tokens), max(8, len(name_tokens) * 3))
    return max(
        len(name_tokens & set(spec_tokens[start:start + window_size])) / len(name_tokens)
        for start in range(max(1, len(spec_tokens) - window_size + 1))
    )


def _name_starts_specification(catalog_component: dict[str, Any], spec_component: dict[str, Any]) -> bool:
    """Whether the matched catalog name describes the component itself, not nested packaging text."""
    name_tokens = _component_name_tokens(catalog_component)
    spec_tokens = _tokens(spec_component.get("descricao", ""))
    if not name_tokens or not spec_tokens:
        return False
    # Catalog titles can reorder their words ("Balão volumétrico" / "Balão de
    # vidro termorresistente, volumétrico"). Look near the beginning so nested
    # mentions such as a storage box inside a paper-package requirement do not
    # inherit that package's quantity.
    return len(name_tokens & set(spec_tokens[:8])) / len(name_tokens) >= 0.67


def _item_title_tokens(value: str) -> set[str]:
    """Normalize item titles, including common wording variants between PDFs."""
    tokens = _tokens(value)
    # This catalog labels the training deliverable "Formação Continuada", while
    # the specification calls it "Capacitação e Suporte".
    if {"formacao", "continuada"}.issubset(tokens):
        tokens = [token for token in tokens if token not in {"formacao", "continuada"}]
        tokens.append("capacitacao")
    # In this document family, the lot-level "Unidade móvel de experimentação"
    # is the same deliverable as the catalog's "Unidade de Armazenamento Experimental".
    if {"unidade", "movel", "experimentacao"}.issubset(tokens):
        tokens = [
            token for token in tokens
            if token not in {"movel", "experimentacao"}
        ] + ["armazenamento", "experimental"]
    generic = {
        "material", "conjunto", "solucao", "didatico", "didatica",
        "pedagogica", "pedagogico", "integrado", "integrada",
        "nao", "consumivel",
    }
    synonyms = {
        "aluno": "estudante",
        "alunos": "estudante",
        "estudantes": "estudante",
        "educacional": "educacional",
        "educacionais": "educacional",
        "professores": "professor",
    }
    return {synonyms.get(token, token) for token in tokens if token not in generic}


def _embedded_storage_unit(item: dict[str, Any]) -> dict[str, Any] | None:
    """Find the storage-unit subsection embedded inside a broader catalog item."""
    detail = item.get("texto_detalhado", "")
    heading_pattern = re.compile(
        r"(?im)^\s*(?P<title>UNIDADE\s+(?:EXPERIMENTAL\s+DE\s+ARMAZENAMENTO|"
        r"DE\s+ARMAZENAMENTO\s+EXPERIMENTAL))\s*$"
    )
    match = heading_pattern.search(detail)
    if not match:
        return None

    section = detail[match.start():]
    quantity_match = re.search(
        r"(?im)^\s*(?P<value>\d+(?:[,.]\d+)?)\s*(?P<unit>unidades?)\s*$",
        section,
    )
    quantity = None
    if quantity_match:
        number = float(quantity_match.group("value").replace(",", "."))
        quantity = {
            "valor": int(number) if number.is_integer() else number,
            "unidade": quantity_match.group("unit"),
        }
    return {
        "titulo": match.group("title"),
        "descricao": section,
        "quantidade": quantity,
    }


def _best_item_matches(
    catalog_items: list[dict[str, Any]],
    spec_items: list[dict[str, Any]],
) -> dict[int, int]:
    """Pair catalog/specification items by title; matching codes are tie-breakers."""
    row_count = len(catalog_items)
    if not row_count or not spec_items:
        return {}

    catalog_titles = [_item_title_tokens(item.get("descricao", "")) for item in catalog_items]
    spec_titles = [_item_title_tokens(item.get("descricao", "")) for item in spec_items]
    title_scores = []
    weights = []
    for catalog_index, catalog_tokens in enumerate(catalog_titles):
        score_row = []
        weight_row = []
        catalog_code = str(catalog_items[catalog_index].get("codigo", ""))
        for spec_index, spec_tokens in enumerate(spec_titles):
            overlap = len(catalog_tokens & spec_tokens)
            score = (
                2 * overlap / (len(catalog_tokens) + len(spec_tokens))
                if catalog_tokens and spec_tokens
                else 0.0
            )
            title_scores.append(score)
            score_row.append(score)
            spec_code = str(spec_items[spec_index].get("codigo", ""))
            code_matches = spec_code.split(".", 1)[-1] == catalog_code
            weight_row.append(
                1.0 + score + (0.05 if code_matches else 0.0)
                if score >= ITEM_TITLE_THRESHOLD
                else 0.0
            )
        weight_row.extend([0.0] * row_count)
        weights.append(weight_row)

    # Hungarian assignment with dummy columns so unrelated titles stay unmatched.
    column_count = len(weights[0])
    costs = [[-weight for weight in row] for row in weights]
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    column_row = [0] * (column_count + 1)
    previous_column = [0] * (column_count + 1)

    for row in range(1, row_count + 1):
        column_row[0] = row
        current_column = 0
        min_cost = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[current_column] = True
            current_row = column_row[current_column]
            delta = float("inf")
            next_column = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                reduced_cost = costs[current_row - 1][column - 1] - u[current_row] - v[column]
                if reduced_cost < min_cost[column]:
                    min_cost[column] = reduced_cost
                    previous_column[column] = current_column
                if min_cost[column] < delta:
                    delta = min_cost[column]
                    next_column = column
            for column in range(column_count + 1):
                if used[column]:
                    u[column_row[column]] += delta
                    v[column] -= delta
                else:
                    min_cost[column] -= delta
            current_column = next_column
            if column_row[current_column] == 0:
                break
        while True:
            next_column = previous_column[current_column]
            column_row[current_column] = column_row[next_column]
            current_column = next_column
            if current_column == 0:
                break

    assignment: dict[int, int] = {}
    for column in range(1, len(spec_items) + 1):
        row = column_row[column]
        if row and title_scores[(row - 1) * len(spec_items) + column - 1] >= ITEM_TITLE_THRESHOLD:
            assignment[column - 1] = row - 1
    return assignment


def _best_component_matches(
    catalog_components: list[dict[str, Any]],
    spec_components: list[dict[str, Any]],
) -> dict[int, tuple[int, float]]:
    """Map catalog components to specification components using weighted evidence.

    Component identity determines whether a pair is plausible. Name and quantity
    carry equal weight when choosing among candidates; descriptive details have
    less weight because the specification may phrase them differently.
    """
    row_count = len(catalog_components)
    if not row_count or not spec_components:
        return {}

    features = [
        [
            _match_features(catalog_component["descricao"], spec_component["descricao"])
            for spec_component in spec_components
        ]
        for catalog_component in catalog_components
    ]
    # Match each catalog row independently. A single specification component
    # can describe a grouped set (four boards, several brush sizes, or nested
    # packaging), so forcing one-to-one assignment creates false positives.
    assignment: dict[int, tuple[int, float]] = {}
    for ci, catalog_component in enumerate(catalog_components):
        candidates: list[tuple[float, int, float, bool | None]] = []
        for si, spec_component in enumerate(spec_components):
            if (
                _component_variant_conflict(catalog_component, spec_component)
                or _component_attribute_conflict(catalog_component, spec_component)
            ):
                continue
            keyword_score, detail_score = features[ci][si]
            name_score = _name_coverage(catalog_component, spec_component)
            dimensions_match = _catalog_dimensions_supported(
                catalog_component["descricao"], spec_component["descricao"]
            )
            quantity_score = 1.0 if _quantities_equal(
                catalog_component.get("quantidade"),
                spec_component.get("quantidade"),
            ) else 0.0
            # Grouped spec entries (for example, a set of printed boards) may
            # not repeat each catalog row's title. Matching dimensions plus
            # related wording can identify the correct grouped entry and avoid
            # comparing a printed cell diagram to a physical cell model.
            eligible = (
                name_score >= 0.60
                or keyword_score >= COMPONENT_IDENTITY_THRESHOLD
                or (
                    dimensions_match is True
                    and name_score >= 0.30
                    and detail_score >= 0.55
                )
            )
            if eligible:
                combined = (
                    NAME_WEIGHT * name_score
                    + QUANTITY_WEIGHT * quantity_score
                    + DETAIL_WEIGHT * detail_score
                )
                candidates.append((combined, si, name_score, dimensions_match))
        if candidates:
            # When a plausible candidate confirms the catalog dimensions,
            # prefer it over a superficially similar candidate with different
            # dimensions. Keep a conflicting candidate if no confirming one
            # exists so genuine dimension discrepancies are still reported.
            if any(candidate[3] is True for candidate in candidates):
                candidates = [candidate for candidate in candidates if candidate[3] is not False]
            score, si, _, _ = max(candidates, key=lambda candidate: candidate[0])
            assignment[ci] = (si, score)
    return assignment


def _canonical_unit(value: str | None) -> str | None:
    if not value:
        return None
    unit = value.strip().lower().rstrip(".")
    if unit in {"unidade", "unidades", "un"}:
        return "unidade"
    if unit in {"peça", "peças", "peca", "pecas"}:
        return "peça"
    if unit in {"kit", "kits"}:
        return "kit"
    if unit in {"conjunto", "conjuntos"}:
        return "conjunto"
    return unit


def _quantities_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return left is right
    if float(left["valor"]) != float(right["valor"]):
        return False
    left_unit = _canonical_unit(left.get("unidade"))
    right_unit = _canonical_unit(right.get("unidade"))
    return not left_unit or not right_unit or left_unit == right_unit


def _divergence(
    *,
    item_catalog: str,
    item_spec: str,
    kind: str,
    reason: str,
    page_catalog: int | None = None,
    page_spec: int | None = None,
    component_catalog: dict[str, Any] | None = None,
    component_spec: dict[str, Any] | None = None,
    quantity_catalog: dict[str, Any] | None = None,
    quantity_spec: dict[str, Any] | None = None,
    match_score: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "item_catalogo": item_catalog,
        "item_descricao_tecnica": item_spec,
        "tipo": kind,
        "motivo": reason,
    }
    if component_catalog:
        result["componente_catalogo"] = component_catalog["descricao"]
    if component_spec:
        result["componente_descricao_tecnica"] = component_spec["descricao"]
    if quantity_catalog is not None:
        result["quantidade_catalogo"] = quantity_catalog
    if quantity_spec is not None:
        result["quantidade_descricao_tecnica"] = quantity_spec
    if page_catalog is not None:
        result["pagina_catalogo"] = page_catalog
    if page_spec is not None:
        result["pagina_descricao_tecnica"] = page_spec
    if match_score is not None:
        result["similaridade_textual"] = round(match_score, 3)
    return result


def compare_documents(catalog: dict[str, Any], specification: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only divergences, pairing items primarily by their titles.

    Additional specification-only components are intentionally ignored. Components
    with no catalog item owner are not supplied to this function and cannot match.
    """
    catalog_items = list(catalog["itens"])
    specification_items = [
        item for item in specification["itens"]
        if "." in str(item["codigo"])
    ]
    item_matches = _best_item_matches(catalog_items, specification_items)
    divergences: list[dict[str, Any]] = []

    matched_catalog_indices = set(item_matches.values())
    for spec_index, spec_item in enumerate(specification_items):
        catalog_index = item_matches.get(spec_index)
        if catalog_index is None:
            # The specification may include extra components or services. The
            # comparison reports catalog claims that are unsupported by the
            # specification, so specification-only items are informational.
            continue

        catalog_item = catalog_items[catalog_index]
        item_number = str(catalog_item["codigo"])

        catalog_components = list(catalog_item["componentes"])
        spec_components = list(spec_item["componentes"])
        catalog_item_quantity = catalog_item["quantidade_do_conjunto"]
        if (
            catalog_item_quantity is None
            and not spec_components
            and len(catalog_components) == 1
        ):
            catalog_item_quantity = catalog_components[0]["quantidade"]
        spec_item_quantity = spec_item["quantidade_por_ambiente"]
        if (
            catalog_item_quantity is not None
            and spec_item_quantity is not None
            and not _quantities_equal(catalog_item_quantity, spec_item_quantity)
        ):
            divergences.append(_divergence(
                item_catalog=item_number,
                item_spec=spec_item["codigo"],
                kind="quantidade_do_item_divergente",
                reason="A quantidade do item por ambiente não coincide com a quantidade do item no catálogo.",
                page_catalog=catalog_item.get("pagina_quantidade", catalog_item["pagina"]),
                page_spec=spec_item.get("pagina_quantidade", spec_item["pagina"]),
                quantity_catalog=catalog_item_quantity,
                quantity_spec=spec_item_quantity,
            ))

        if catalog_components and spec_components:
            component_matches = _best_component_matches(catalog_components, spec_components)

            for ci, catalog_component in enumerate(catalog_components):
                if ci not in component_matches:
                    # Some shared resources, such as an RA activation card,
                    # are listed under a different technical subitem. Search
                    # other items only when the catalog's principal name has
                    # strong support there; this avoids global fuzzy matches.
                    cross_item_candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
                    for other_spec_item in specification_items:
                        if other_spec_item is spec_item:
                            continue
                        for other_component in other_spec_item["componentes"]:
                            if (
                                _component_variant_conflict(catalog_component, other_component)
                                or _component_attribute_conflict(catalog_component, other_component)
                            ):
                                continue
                            name_score = _name_coverage(catalog_component, other_component)
                            if name_score < 0.60:
                                continue
                            _, detail_score = _match_features(
                                catalog_component["descricao"], other_component["descricao"]
                            )
                            quantity_score = 1.0 if _quantities_equal(
                                catalog_component.get("quantidade"),
                                other_component.get("quantidade"),
                            ) else 0.0
                            score = (
                                NAME_WEIGHT * name_score
                                + QUANTITY_WEIGHT * quantity_score
                                + DETAIL_WEIGHT * detail_score
                            )
                            cross_item_candidates.append((score, other_spec_item, other_component))
                    if cross_item_candidates:
                        score, other_spec_item, other_component = max(
                            cross_item_candidates, key=lambda candidate: candidate[0]
                        )
                        if not _quantities_equal(
                            catalog_component["quantidade"], other_component["quantidade"]
                        ):
                            divergences.append(_divergence(
                                item_catalog=item_number,
                                item_spec=other_spec_item["codigo"],
                                kind="quantidade_divergente",
                                reason="A quantidade do componente correspondente não coincide.",
                                component_catalog=catalog_component,
                                component_spec=other_component,
                                quantity_catalog=catalog_component["quantidade"],
                                quantity_spec=other_component["quantidade"],
                                page_catalog=catalog_component["pagina"],
                                page_spec=other_component["pagina"],
                                match_score=score,
                            ))
                        continue
                    divergences.append(_divergence(
                        item_catalog=item_number,
                        item_spec=spec_item["codigo"],
                        kind="componente_nao_encontrado_na_descricao",
                        reason="Componente informado no catálogo sem correspondência na descrição técnica.",
                        component_catalog=catalog_component,
                        quantity_catalog=catalog_component["quantidade"],
                        page_catalog=catalog_component["pagina"],
                        page_spec=spec_item["pagina"],
                    ))
                    continue
                si, score = component_matches[ci]
                spec_component = spec_components[si]
                if (
                    _name_starts_specification(catalog_component, spec_component)
                    and not _quantities_equal(
                        catalog_component["quantidade"], spec_component["quantidade"]
                    )
                ):
                    divergences.append(_divergence(
                        item_catalog=item_number,
                        item_spec=spec_item["codigo"],
                        kind="quantidade_divergente",
                        reason="A quantidade do componente correspondente não coincide.",
                        component_catalog=catalog_component,
                        component_spec=spec_component,
                        quantity_catalog=catalog_component["quantidade"],
                        quantity_spec=spec_component["quantidade"],
                        page_catalog=catalog_component["pagina"],
                        page_spec=spec_component["pagina"],
                        match_score=score,
                    ))
                dimensions_match = _catalog_dimensions_supported(
                    catalog_component["descricao"],
                    spec_component["descricao"],
                    catalog_component.get("quantidade"),
                )
                if dimensions_match is False:
                    divergence = _divergence(
                        item_catalog=item_number,
                        item_spec=spec_item["codigo"],
                        kind="dimensao_divergente",
                        reason="Uma ou mais medidas informadas no catálogo não aparecem com o mesmo valor na descrição técnica.",
                        component_catalog=catalog_component,
                        component_spec=spec_component,
                        page_catalog=catalog_component["pagina"],
                        page_spec=spec_component["pagina"],
                        match_score=score,
                    )
                    divergence["medidas_catalogo_mm"] = sorted(
                        _dimension_values_mm(
                            catalog_component["descricao"],
                            catalog_component.get("quantidade"),
                        )
                    )
                    divergence["medidas_descricao_tecnica_mm"] = sorted(
                        _dimension_values_mm(spec_component["descricao"])
                    )
                    divergences.append(divergence)

                for context, catalog_count, spec_count in _piece_count_conflicts(
                    catalog_component["descricao"], spec_component["descricao"]
                ):
                    divergences.append(_divergence(
                        item_catalog=item_number,
                        item_spec=spec_item["codigo"],
                        kind="quantidade_interna_divergente",
                        reason="A quantidade de peças ou partes informada para o componente não coincide.",
                        component_catalog=catalog_component,
                        component_spec=spec_component,
                        page_catalog=catalog_component["pagina"],
                        page_spec=spec_component["pagina"],
                        match_score=score,
                    ) | {
                        "contexto_contagem": context,
                        "contagem_catalogo": catalog_count,
                        "contagem_descricao_tecnica": spec_count,
                    })
            # Catalog-only components are allowed by the comparison rules.
        elif not catalog_components and not spec_components:
            # Some catalog deliverables (for example, the storage unit) are
            # described in running text rather than as table components. Keep
            # that text on the paired item and compare its explicit dimensions.
            catalog_detail = catalog_item.get("texto_detalhado", catalog_item["descricao"])
            spec_detail = spec_item.get("texto_detalhado", spec_item["descricao"])
            catalog_dimensions = _dimension_scope(catalog_detail)
            spec_dimensions = _dimension_scope(spec_detail)
            dimensions_match = _catalog_dimensions_supported(catalog_dimensions, spec_dimensions)
            if dimensions_match is False:
                divergence = _divergence(
                    item_catalog=item_number,
                    item_spec=spec_item["codigo"],
                    kind="dimensao_divergente",
                    reason="Uma ou mais medidas informadas no catálogo não aparecem com o mesmo valor na descrição técnica.",
                    component_catalog={"descricao": catalog_item["descricao"]},
                    component_spec={"descricao": spec_item["descricao"]},
                    page_catalog=catalog_item["pagina"],
                    page_spec=spec_item["pagina"],
                )
                divergence["detalhes_catalogo"] = catalog_dimensions
                divergence["detalhes_descricao_tecnica"] = spec_dimensions
                divergence["medidas_catalogo_mm"] = sorted(
                    _dimension_values_mm(catalog_dimensions)
                )
                divergence["medidas_descricao_tecnica_mm"] = sorted(
                    _dimension_values_mm(spec_dimensions)
                )
                divergences.append(divergence)

    # Some catalogs place the storage unit as a subsection under a broader
    # heading such as "Formação Continuada". It must still be compared with the
    # separate "Unidade móvel de experimentação" item in the specification.
    storage_unit_spec_titles = {"unidade", "armazenamento", "experimental"}
    for spec_index, spec_item in enumerate(specification_items):
        if spec_index in item_matches:
            continue
        spec_title_tokens = _item_title_tokens(spec_item.get("descricao", ""))
        if not storage_unit_spec_titles.issubset(spec_title_tokens):
            continue

        matched_subsection = None
        for catalog_item in catalog_items:
            subsection = _embedded_storage_unit(catalog_item)
            if subsection and _item_title_tokens(subsection["titulo"]) == spec_title_tokens:
                matched_subsection = (catalog_item, subsection)
                break
        if not matched_subsection:
            continue

        catalog_item, subsection = matched_subsection
        spec_text = spec_item.get("texto_detalhado", spec_item.get("descricao", ""))
        spec_quantity = spec_item.get("quantidade_por_ambiente")
        if (
            subsection["quantidade"] is not None
            and spec_quantity is not None
            and not _quantities_equal(subsection["quantidade"], spec_quantity)
        ):
            divergences.append(_divergence(
                item_catalog=str(catalog_item["codigo"]),
                item_spec=str(spec_item["codigo"]),
                kind="quantidade_divergente",
                reason="A quantidade da unidade móvel no catálogo não coincide com a quantidade da descrição técnica.",
                component_catalog={"descricao": subsection["descricao"]},
                component_spec={"descricao": spec_text},
                quantity_catalog=subsection["quantidade"],
                quantity_spec=spec_quantity,
                page_catalog=catalog_item.get("pagina"),
                page_spec=spec_item.get("pagina"),
            ))

        catalog_dimensions = _dimension_scope(subsection["descricao"])
        spec_dimensions = _dimension_scope(spec_text)
        if _catalog_dimensions_supported(
            catalog_dimensions, spec_dimensions, subsection["quantidade"]
        ) is False:
            divergence = _divergence(
                item_catalog=str(catalog_item["codigo"]),
                item_spec=str(spec_item["codigo"]),
                kind="dimensao_divergente",
                reason="Uma ou mais medidas da unidade móvel informadas no catálogo não aparecem com o mesmo valor na descrição técnica.",
                component_catalog={"descricao": subsection["descricao"]},
                component_spec={"descricao": spec_text},
                page_catalog=catalog_item.get("pagina"),
                page_spec=spec_item.get("pagina"),
            )
            divergence["medidas_catalogo_mm"] = sorted(
                _dimension_values_mm(catalog_dimensions, subsection["quantidade"])
            )
            divergence["medidas_descricao_tecnica_mm"] = sorted(
                _dimension_values_mm(spec_dimensions)
            )
            divergences.append(divergence)

    for catalog_index, catalog_item in enumerate(catalog_items):
        item_number = str(catalog_item["codigo"])
        if catalog_index not in matched_catalog_indices:
            divergence = _divergence(
                item_catalog=item_number,
                item_spec="sem correspondência por título",
                kind="item_ausente_na_descricao",
                reason="O item do catálogo não foi encontrado na descrição técnica.",
                page_catalog=catalog_item["pagina"],
            )
            divergence["descricao_item_catalogo"] = catalog_item["descricao"]
            divergences.append(divergence)

    return divergences
