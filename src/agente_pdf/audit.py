"""Build a local, privacy-preserving audit of PDF extraction coverage."""

import re
from collections import Counter
from typing import Any

from agente_pdf.parsers import (
    CATALOG_ITEM_PATTERN,
    COMPONENT_PATTERN,
    LEADING_COMPONENT_PATTERN,
    LOT_PATTERN,
    SPEC_ITEM_PATTERN,
    _normalize,
    _table_columns,
)
from agente_pdf.pdf_reader import PDFDocument


def build_extraction_audit(
    catalog_document: PDFDocument,
    specification_document: PDFDocument,
    catalog: dict[str, Any],
    specification: dict[str, Any],
    target_lot: int,
    specification_page_range: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return page/item counts and local-only candidate lines for human review."""
    catalog_items = catalog["itens"]
    unassigned_by_page: Counter[int] = Counter()
    for table in catalog["tabelas_sem_item_vinculado"]:
        unassigned_by_page[table["pagina"]] += len(table["linhas"])
    catalog_by_code = {item["codigo"]: item for item in catalog_items}
    catalog_item_stats = {
        code: {
            "codigo": code,
            "pagina_do_item": item["pagina"],
            "componentes_reconhecidos": len(item["componentes"]),
            "paginas_com_componentes": sorted({c["pagina"] for c in item["componentes"]}),
            "linhas_texto_com_quantidade_e_unidade": 0,
            "linhas_candidatas_para_revisao": [],
        }
        for code, item in catalog_by_code.items()
    }
    catalog_pages = []
    current_catalog_code: str | None = None
    for page in catalog_document.pages:
        page_codes: list[str] = []
        page_candidates = 0
        page_review_candidates = 0
        for line in page.text.splitlines():
            item_match = CATALOG_ITEM_PATTERN.match(line)
            if item_match:
                current_catalog_code = item_match.group(1)
                page_codes.append(current_catalog_code)
                continue
            candidate_text = re.sub(r"^\s*[-•]\s*", "", line).strip()
            if current_catalog_code and LEADING_COMPONENT_PATTERN.match(candidate_text):
                page_candidates += 1
                stats = catalog_item_stats.get(current_catalog_code)
                if stats is not None:
                    stats["linhas_texto_com_quantidade_e_unidade"] += 1
                    # This list is saved only to the local audit JSON and is never printed.
                    stats["linhas_candidatas_para_revisao"].append({
                        "pagina": page.number,
                        "linha": candidate_text,
                    })
                    page_review_candidates += 1
        # Candidate lines from the text layer are review clues, not a definitive
        # count of missed components: table extraction can split cells differently.
        catalog_pages.append({
            "pagina": page.number,
            "tabelas_detectadas": len(page.tables),
            "tabelas_com_cabecalho_descricao_e_quantidade": sum(
                _table_columns(table) is not None for table in page.tables
            ),
            "itens_identificados_na_pagina": page_codes,
            "linhas_com_quantidade_e_unidade_no_texto": page_candidates,
            "linhas_candidatas_para_revisao": page_review_candidates,
            "componentes_reconhecidos_pelo_parser": sum(
                1 for item in catalog_items for component in item["componentes"]
                if component["pagina"] == page.number
            ),
            "componentes_extraidos_sem_item_vinculado": unassigned_by_page[page.number],
        })

    specification_items = specification["itens"]
    spec_stats = {
        item["codigo"]: {
            "codigo": item["codigo"],
            "pagina_do_item": item["pagina"],
            "componentes_reconhecidos": len(item["componentes"]),
            "tem_quantidade_por_ambiente": item["quantidade_por_ambiente"] is not None,
            "linhas_de_componente_nao_reconhecidas": [],
        }
        for item in specification_items
    }
    spec_page_candidates: dict[int, list[dict[str, Any]]] = {}
    current_lot: int | None = None
    current_spec_code: str | None = None
    for page in specification_document.pages:
        page_is_selected = specification_page_range is None or (
            specification_page_range["inicio"] <= page.number <= specification_page_range["fim"]
        )
        for line in page.text.splitlines():
            lot_match = LOT_PATTERN.search(_normalize(line))
            if lot_match:
                current_lot = int(lot_match.group(1))
                current_spec_code = None
            item_match = SPEC_ITEM_PATTERN.match(line)
            if item_match:
                current_spec_code = item_match.group(1) if current_lot == target_lot else None
                continue
            bullet_match = COMPONENT_PATTERN.match(line)
            if (
                not page_is_selected
                or not bullet_match
                or current_spec_code not in spec_stats
            ):
                continue
            candidate_text = bullet_match.group(1).strip()
            if not LEADING_COMPONENT_PATTERN.match(candidate_text):
                candidate = {
                    "pagina": page.number,
                    "linha": candidate_text,
                }
                spec_stats[current_spec_code]["linhas_de_componente_nao_reconhecidas"].append(candidate)
                spec_page_candidates.setdefault(page.number, []).append({
                    "codigo_item": current_spec_code,
                    **candidate,
                })

    catalog_candidates = sum(
        len(item["linhas_candidatas_para_revisao"])
        for item in catalog_item_stats.values()
    )
    spec_unrecognized = sum(
        len(item["linhas_de_componente_nao_reconhecidas"])
        for item in spec_stats.values()
    )
    return {
        "observacao": (
            "Linhas candidatas são pistas para revisão local; a extração de tabela pode "
            "dividir ou reorganizar células. Não representam divergências confirmadas."
        ),
        "catalogo": {
            "itens": list(catalog_item_stats.values()),
            "paginas": catalog_pages,
            "total_linhas_candidatas_para_revisao": catalog_candidates,
            "total_componentes_sem_item_vinculado": sum(unassigned_by_page.values()),
        },
        "descricao_tecnica": {
            "itens": list(spec_stats.values()),
            "paginas_com_linhas_nao_reconhecidas": [
                {"pagina": page_number, "linhas": lines}
                for page_number, lines in sorted(spec_page_candidates.items())
            ],
            "total_linhas_de_componente_nao_reconhecidas": spec_unrecognized,
            "intervalo_paginas_considerado": specification_page_range,
        },
    }
