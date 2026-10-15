import argparse
import json
from pathlib import Path

from agente_pdf.audit import build_extraction_audit
from agente_pdf.comparison import compare_documents
from agente_pdf.parsers import parse_catalog, parse_specification
from agente_pdf.pdf_reader import read_pdf, save_page_text


LEVEL_TO_LOT = {
    "basico": (1, "Lote 1 - Anos Iniciais"),
    "intermediario": (2, "Lote 2 - Anos Finais"),
    "avancado": (3, "Lote 3 - Ensino Médio"),
}


def _describe_document(label: str, document, output_path: Path) -> None:
    text_pages = sum(page.has_text for page in document.pages)
    table_count = sum(len(page.tables) for page in document.pages)
    print(f"{label}: {document.path}")
    print(f"  Páginas: {len(document.pages)}; páginas com conteúdo extraível: {text_pages}.")
    print(f"  Tabelas detectadas: {table_count}.")
    if document.pages_without_text:
        pages = ", ".join(str(number) for number in document.pages_without_text)
        print(f"  Atenção: páginas sem conteúdo extraível: {pages}. Podem precisar de OCR.")
    saved = save_page_text(document, output_path)
    print(f"  Extração local salva em: {saved}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrai conteúdo de catálogo e descrição técnica em PDF."
    )
    parser.add_argument("--catalogo", required=True, help="Caminho do PDF do catálogo")
    parser.add_argument("--descricao", required=True, help="Caminho do PDF da descrição técnica")
    parser.add_argument(
        "--nivel",
        required=True,
        choices=tuple(LEVEL_TO_LOT),
        help="Nível do catálogo: basico, intermediario ou avancado",
    )
    parser.add_argument(
        "--saida",
        default="saida/extraidos",
        help="Pasta local para salvar os arquivos extraídos",
    )
    args = parser.parse_args()

    try:
        catalog = read_pdf(args.catalogo)
        specification = read_pdf(args.descricao)
    except (FileNotFoundError, ValueError, OSError) as error:
        parser.error(str(error))

    output_dir = Path(args.saida)
    target_lot, lot_label = LEVEL_TO_LOT[args.nivel]
    print(f"Nível selecionado: {args.nivel} -> {lot_label}")
    _describe_document("Catálogo", catalog, output_dir / "catalogo.txt")
    _describe_document("Descrição técnica", specification, output_dir / "descricao_tecnica.txt")

    catalog_data = parse_catalog(catalog)
    specification_data = parse_specification(specification, target_lot)
    parsed = {
        "nivel_catalogo": args.nivel,
        "lote_alvo": target_lot,
        "lote_encontrado": False,
        "catalogo": catalog_data,
        "descricao_tecnica": specification_data,
    }
    parsed["lote_encontrado"] = parsed["descricao_tecnica"]["lote_encontrado"]
    parsed_path = output_dir / "itens_extraidos.json"
    parsed_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Pré-análise local salva em: {parsed_path.resolve()}")
    audit = build_extraction_audit(catalog, specification, catalog_data, specification_data, target_lot)
    audit_path = output_dir / "auditoria_extracao.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Auditoria local salva em: {audit_path.resolve()}")
    print(
        "Auditoria: "
        f"{len(catalog_data['itens'])} itens no catálogo, "
        f"{sum(len(i['componentes']) for i in catalog_data['itens'])} componentes reconhecidos; "
        f"{sum(len(t['linhas']) for t in catalog_data['tabelas_sem_item_vinculado'])} componentes "
        "sem item vinculado; "
        f"{audit['catalogo']['total_linhas_candidatas_para_revisao']} linhas do texto do catálogo "
        "(pistas de quantidade; podem coincidir com componentes reconhecidos); "
        f"{sum(len(i['componentes']) for i in specification_data['itens'])} componentes reconhecidos "
        f"e {audit['descricao_tecnica']['total_linhas_de_componente_nao_reconhecidas']} "
        "linhas não reconhecidas na descrição."
    )
    divergences = (
        compare_documents(catalog_data, specification_data)
        if parsed["lote_encontrado"]
        else []
    )
    divergences_path = output_dir / "divergencias.json"
    divergences_path.write_text(
        json.dumps(divergences, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Divergências salvas localmente em: {divergences_path.resolve()}")
    print(f"Divergências encontradas: {len(divergences)}.")
    if not parsed["lote_encontrado"]:
        print("Lote do nível selecionado não encontrado; nenhuma comparação deve ser feita.")


if __name__ == "__main__":
    main()
