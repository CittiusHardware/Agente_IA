from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pdfplumber
import streamlit as st

from agente_pdf.audit import build_extraction_audit
from agente_pdf.comparison import compare_documents
from agente_pdf.parsers import parse_catalog, parse_specification
from agente_pdf.pdf_reader import read_pdf


LEVEL_TO_LOT = {
    "Básico — Lote 1 — Anos Iniciais": (1, "basico"),
    "Intermediário — Lote 2 — Anos Finais": (2, "intermediario"),
    "Avançado — Lote 3 — Ensino Médio": (3, "avancado"),
}


def _output_directory() -> Path:
    if getattr(sys, "frozen", False):
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local_app_data / "AgenteComparadorPDF" / "saida" / "extraidos"
    return Path(__file__).resolve().parent / "saida" / "extraidos"


def _file_digest(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    return hashlib.sha256(uploaded_file.getvalue()).hexdigest()


def _pdf_page_count(pdf_bytes: bytes | None) -> int | None:
    if not pdf_bytes:
        return None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def _specification_page_range(spec_data: dict, start_page: int, end_page: int) -> dict:
    """Keep only specification items/components overlapping selected pages."""
    selected_items = []
    for item in spec_data["itens"]:
        item_page = int(item.get("pagina", 0) or 0)
        selected_components = [
            component for component in item.get("componentes", [])
            if start_page <= int(component.get("pagina", 0) or 0) <= end_page
        ]
        if start_page <= item_page <= end_page or selected_components:
            selected_item = dict(item)
            selected_item["componentes"] = selected_components
            selected_items.append(selected_item)

    filtered = dict(spec_data)
    filtered["itens"] = selected_items
    filtered["intervalo_paginas"] = {"inicio": start_page, "fim": end_page}
    filtered["itens_encontrados_no_intervalo"] = len(selected_items)
    return filtered


def _partially_selected_specification_items(
    spec_data: dict, start_page: int, end_page: int
) -> list[str]:
    partial = []
    for item in spec_data["itens"]:
        pages = {int(item.get("pagina", 0) or 0)}
        if item.get("pagina_quantidade") is not None:
            pages.add(int(item["pagina_quantidade"]))
        pages.update(
            int(component.get("pagina", 0) or 0)
            for component in item.get("componentes", [])
            if component.get("pagina") is not None
        )
        inside = {page for page in pages if start_page <= page <= end_page}
        if inside and inside != pages:
            partial.append(str(item.get("codigo", "?")))
    return partial


st.set_page_config(page_title="Comparador de PDFs", page_icon="📄", layout="wide")
st.title("Comparador de catálogo e descrição técnica")
col_catalog, col_spec = st.columns(2)
with col_catalog:
    catalog_file = st.file_uploader("Catálogo em PDF", type=["pdf"], key="catalog")
with col_spec:
    spec_file = st.file_uploader("Descrição técnica em PDF", type=["pdf"], key="spec")

selected_level = st.selectbox("Nível do catálogo", tuple(LEVEL_TO_LOT))
lot_number, level_slug = LEVEL_TO_LOT[selected_level]
st.caption(f"Associação automática: {selected_level.split('—')[0].strip()} → Lote {lot_number}.")
use_page_range = st.checkbox("Limitar a extração a páginas específicas da descrição técnica")
if use_page_range:
    spec_bytes_for_count = spec_file.getvalue() if spec_file is not None else None
    try:
        spec_page_count = _pdf_page_count(spec_bytes_for_count)
    except Exception as error:
        spec_page_count = None
        st.error(f"Não consegui ler a quantidade de páginas da descrição técnica: {error}")

    upload_signature = _file_digest(spec_file)
    if st.session_state.get("page_range_upload_signature") != upload_signature:
        st.session_state["page_range_upload_signature"] = upload_signature
        st.session_state["description_page_start"] = 1
        st.session_state["description_page_end"] = max(spec_page_count or 1, 1)

    start_page, end_page = st.columns(2)
    with start_page:
        description_start_page = st.number_input(
            "Página inicial da descrição técnica", min_value=1, max_value=99999, step=1,
            key="description_page_start",
        )
    with end_page:
        description_end_page = st.number_input(
            "Página final da descrição técnica", min_value=1, max_value=99999, step=1,
            key="description_page_end",
        )
    if spec_page_count:
        st.caption(
            f"A descrição técnica tem {spec_page_count} páginas. Use a numeração física do PDF "
            "e inclua as páginas de continuação dos itens do lote."
        )
    else:
        st.caption("O intervalo usa a numeração física das páginas do PDF.")
else:
    description_start_page = None
    description_end_page = None

current_signature = (
    _file_digest(catalog_file),
    _file_digest(spec_file),
    selected_level,
    (int(description_start_page), int(description_end_page)) if use_page_range else None,
)
extraction_state = st.session_state.get("extraction_state")
if extraction_state and extraction_state.get("signature") != current_signature:
    st.session_state.pop("extraction_state", None)
    st.session_state.pop("comparison_result", None)

extract_clicked = st.button("Extrair e conferir", type="primary", width="stretch")
if extract_clicked:
    st.session_state.pop("extraction_state", None)
    st.session_state.pop("comparison_result", None)
    if catalog_file is None or spec_file is None:
        st.error("Selecione o catálogo e a descrição técnica antes de extrair.")
    elif use_page_range and int(description_start_page) > int(description_end_page):
        st.error("A página inicial precisa ser menor ou igual à página final.")
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="comparador_pdf_") as temp_dir:
                catalog_path = Path(temp_dir) / "catalogo.pdf"
                spec_path = Path(temp_dir) / "descricao_tecnica.pdf"
                catalog_path.write_bytes(catalog_file.getvalue())
                spec_path.write_bytes(spec_file.getvalue())

                catalog_document = read_pdf(catalog_path)
                spec_document = read_pdf(spec_path)
                total_spec_pages = len(spec_document.pages)
                if use_page_range and int(description_end_page) > total_spec_pages:
                    raise ValueError(
                        f"O intervalo termina na página {int(description_end_page)}, "
                        f"mas a descrição técnica tem apenas {total_spec_pages} páginas."
                    )

                catalog_data = parse_catalog(catalog_document)
                full_spec_data = parse_specification(spec_document, lot_number)
                if use_page_range:
                    spec_data = _specification_page_range(
                        full_spec_data,
                        int(description_start_page),
                        int(description_end_page),
                    )
                    selected_page_range = {
                        "inicio": int(description_start_page),
                        "fim": int(description_end_page),
                    }
                    partial_items = _partially_selected_specification_items(
                        full_spec_data,
                        int(description_start_page),
                        int(description_end_page),
                    )
                else:
                    spec_data = full_spec_data
                    selected_page_range = None
                    partial_items = []

                parsed_data = {
                    "nivel_catalogo": level_slug,
                    "lote_alvo": lot_number,
                    "lote_encontrado": spec_data["lote_encontrado"],
                    "intervalo_paginas_descricao_tecnica": selected_page_range,
                    "total_paginas_descricao_tecnica": total_spec_pages,
                    "catalogo": catalog_data,
                    "descricao_tecnica": spec_data,
                }
                output_dir = _output_directory()
                output_dir.mkdir(parents=True, exist_ok=True)
                parsed_path = output_dir / "itens_extraidos.json"
                parsed_path.write_text(
                    json.dumps(parsed_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                audit_data = build_extraction_audit(
                    catalog_document,
                    spec_document,
                    catalog_data,
                    spec_data,
                    lot_number,
                    specification_page_range=selected_page_range,
                )
                audit_data["nivel_catalogo"] = level_slug
                audit_data["lote_alvo"] = lot_number
                audit_data["intervalo_paginas_descricao_tecnica"] = selected_page_range
                audit_path = output_dir / "auditoria_extracao.json"
                audit_path.write_text(
                    json.dumps(audit_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                selected_spec_pages = (
                    set(range(int(description_start_page), int(description_end_page) + 1))
                    if use_page_range else set(range(1, total_spec_pages + 1))
                )
                spec_pages_without_text = [
                    page for page in spec_document.pages_without_text
                    if page in selected_spec_pages
                ]

            st.session_state["extraction_state"] = {
                "signature": current_signature,
                "catalog_data": catalog_data,
                "spec_data": spec_data,
                "catalog_name": catalog_file.name,
                "spec_name": spec_file.name,
                "level": selected_level,
                "lot_number": lot_number,
                "lot_found": spec_data["lote_encontrado"],
                "parsed_path": str(parsed_path.resolve()),
                "page_range": selected_page_range,
                "total_spec_pages": total_spec_pages,
                "partial_items": partial_items,
                "comparison_available": bool(spec_data["lote_encontrado"] and spec_data["itens"]),
                "spec_pages_without_text": spec_pages_without_text,
            }
        except Exception as error:
            st.error(f"Não foi possível extrair os PDFs: {error}")

extraction_state = st.session_state.get("extraction_state")
if extraction_state:
    catalog_data = extraction_state["catalog_data"]
    spec_data = extraction_state["spec_data"]
    catalog_component_count = sum(len(item["componentes"]) for item in catalog_data["itens"])
    spec_component_count = sum(len(item["componentes"]) for item in spec_data["itens"])

    st.divider()
    st.subheader("Conferência da extração")
    st.caption(
        f"Catálogo: {extraction_state['catalog_name']} · "
        f"Descrição: {extraction_state['spec_name']} · {extraction_state['level']}"
    )
    if extraction_state["page_range"]:
        page_range = extraction_state["page_range"]
        st.caption(
            f"Páginas da descrição técnica selecionadas: {page_range['inicio']} a {page_range['fim']} "
            f"(de {extraction_state['total_spec_pages']}). O catálogo foi extraído por inteiro."
        )
    metrics = st.columns(4)
    metrics[0].metric("Itens no catálogo", len(catalog_data["itens"]))
    metrics[1].metric("Componentes no catálogo", catalog_component_count)
    metrics[2].metric("Itens na descrição", len(spec_data["itens"]))
    metrics[3].metric("Componentes na descrição", spec_component_count)

    if extraction_state["partial_items"]:
        st.warning(
            "O intervalo selecionado corta páginas de continuação destes itens da descrição técnica: "
            + ", ".join(extraction_state["partial_items"])
            + ". Amplie o intervalo para incluir todas as páginas desses itens."
        )
    if extraction_state["spec_pages_without_text"]:
        st.warning(
            "Páginas da descrição sem texto extraível: "
            + ", ".join(map(str, extraction_state["spec_pages_without_text"]))
            + ". Elas podem precisar de OCR."
        )

    if not extraction_state["lot_found"]:
        st.warning(
            f"Não encontrei o Lote {extraction_state['lot_number']} na descrição técnica. "
            "Confira o nível selecionado; a comparação ficará indisponível."
        )
    elif not extraction_state["comparison_available"]:
        st.warning(
            "Nenhum item do lote associado foi encontrado no intervalo da descrição técnica. "
            "Amplie ou ajuste o intervalo antes de comparar."
        )
    elif st.button("Comparar itens", type="primary", width="stretch"):
        try:
            divergences = compare_documents(catalog_data, spec_data)
            divergences_path = _output_directory() / "divergencias.json"
            divergences_path.write_text(
                json.dumps(divergences, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            st.session_state["comparison_result"] = {
                "divergences": divergences,
                "catalog_name": extraction_state["catalog_name"],
                "spec_name": extraction_state["spec_name"],
                "level": extraction_state["level"],
                "lot_found": extraction_state["lot_found"],
                "parsed_path": extraction_state["parsed_path"],
            }
        except Exception as error:
            st.error(f"Não foi possível comparar os PDFs: {error}")

result = st.session_state.get("comparison_result")
if result:
    st.divider()
    st.subheader("Resultado")
    st.caption(
        f"Catálogo: {result['catalog_name']}  ·  "
        f"Descrição: {result['spec_name']}  ·  {result['level']}"
    )
    divergences = result["divergences"]
    if not result["lot_found"]:
        pass
    elif not divergences:
        st.success("Nenhuma divergência encontrada nos itens comparados.")
    else:
        st.warning(f"Foram encontradas {len(divergences)} divergências.")

        colors = {
            "quantidade_divergente": ("#FEE2E2", "#991B1B", "Quantidade ou dimensão divergente"),
            "quantidade_do_item_divergente": ("#FEE2E2", "#991B1B", "Quantidade ou dimensão divergente"),
            "quantidade_interna_divergente": ("#FEF3C7", "#92400E", "Contagem interna divergente"),
            "componente_nao_encontrado_na_descricao": ("#FFEDD5", "#9A3412", "Componente não encontrado"),
            "item_ausente_na_descricao": ("#FFEDD5", "#9A3412", "Item ausente na descrição"),
            "dimensao_divergente": ("#FEE2E2", "#991B1B", "Quantidade ou dimensão divergente"),
        }

        st.markdown("**Legenda**")
        legend_cols = st.columns(3)
        legend_types = (
            "quantidade_divergente",
            "quantidade_interna_divergente",
            "componente_nao_encontrado_na_descricao",
        )
        for col, divergence_type in zip(legend_cols, legend_types):
            background, foreground, label = colors[divergence_type]
            col.markdown(
                f"<div style='background:{background};color:{foreground};"
                f"padding:.5rem .65rem;border-radius:.45rem;font-weight:600'>"
                f"{label}</div>",
                unsafe_allow_html=True,
            )

        summary_rows = []
        for divergence in divergences:
            divergence_type = divergence.get("tipo", "")
            summary_rows.append({
                "Tipo": colors.get(divergence_type, ("#F3F4F6", "#374151", divergence_type))[2],
                "Item do catálogo": divergence.get("item_catalogo", ""),
                "Item da descrição": divergence.get("item_descricao_tecnica", ""),
                "Descrição no catálogo": divergence.get(
                    "descricao_item_catalogo", divergence.get("componente_catalogo", "")
                ),
                "Componente na descrição": divergence.get("componente_descricao_tecnica", ""),
                "Página catálogo": divergence.get("pagina_catalogo", ""),
                "Página descrição": divergence.get("pagina_descricao_tecnica", ""),
                "_tipo": divergence_type,
            })

        summary = pd.DataFrame(summary_rows)
        def style_row(row):
            divergence_type = summary.loc[row.name, "_tipo"]
            background, foreground, _ = colors.get(
                divergence_type, ("#F3F4F6", "#374151", divergence_type)
            )
            return [
                f"background-color: {background}; color: {foreground};"
                for _ in row
            ]

        styled_summary = summary.drop(columns=["_tipo"]).style.apply(style_row, axis=1)
        st.dataframe(styled_summary, width="stretch", hide_index=True)

        for index, divergence in enumerate(divergences, start=1):
            title = (
                f"{index}. {divergence.get('tipo', 'Divergência')} — "
                f"Item {divergence.get('item_catalogo', '?')}"
            )
            with st.expander(title):
                if divergence.get("descricao_item_catalogo"):
                    st.markdown(
                        f"**Título lido no catálogo:** {divergence['descricao_item_catalogo']}"
                    )
                st.write(divergence.get("motivo", ""))
                if divergence.get("tipo") == "dimensao_divergente":
                    catalog_mm = divergence.get("medidas_catalogo_mm", [])
                    spec_mm = divergence.get("medidas_descricao_tecnica_mm", [])
                    st.write(f"Medidas do catálogo (mm): {catalog_mm}")
                    st.write(f"Medidas da descrição técnica (mm): {spec_mm}")
                if divergence.get("tipo") == "quantidade_interna_divergente":
                    st.write(
                        f"Contagem de {divergence.get('contexto_contagem', 'peças')}: "
                        f"catálogo {divergence.get('contagem_catalogo')} × "
                        f"descrição {divergence.get('contagem_descricao_tecnica')}"
                    )
                st.json(divergence)

        st.download_button(
            "Baixar divergências em JSON",
            data=json.dumps(divergences, ensure_ascii=False, indent=2),
            file_name="divergencias.json",
            mime="application/json",
            width="stretch",
        )
