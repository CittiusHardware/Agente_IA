from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber


@dataclass(frozen=True)
class PDFPage:
    number: int
    text: str
    tables: tuple[tuple[tuple[str, ...], ...], ...] = ()
    words: tuple[dict[str, Any], ...] = ()
    table_row_bounds: tuple[tuple[tuple[float, float], ...], ...] = ()
    table_bounds: tuple[tuple[float, float, float, float], ...] = ()

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip()) or bool(self.tables) or bool(self.words)


@dataclass(frozen=True)
class PDFDocument:
    path: Path
    pages: tuple[PDFPage, ...]

    @property
    def pages_without_text(self) -> tuple[int, ...]:
        return tuple(page.number for page in self.pages if not page.has_text)


def read_pdf(file_path: str | Path) -> PDFDocument:
    """Extract text, tables, and word positions from a PDF, keeping page numbers."""
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"PDF não encontrado: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"O arquivo precisa ter extensão .pdf: {path}")

    with pdfplumber.open(path) as pdf:
        pages = []
        for index, page in enumerate(pdf.pages, start=1):
            table_objects = page.find_tables() or []
            tables = tuple(
                tuple(
                    tuple((cell or "").strip() for cell in row)
                    for row in (table.extract() or [])
                )
                for table in table_objects
            )
            table_row_bounds = tuple(
                tuple(
                    (
                        min(cell[1] for cell in row.cells if cell is not None),
                        max(cell[3] for cell in row.cells if cell is not None),
                    )
                    for row in table.rows
                    if any(cell is not None for cell in row.cells)
                )
                for table in table_objects
            )
            table_bounds = tuple(tuple(table.bbox) for table in table_objects)
            words = tuple(
                {
                    "text": word["text"],
                    "x0": word["x0"],
                    "x1": word["x1"],
                    "top": word["top"],
                    "bottom": word["bottom"],
                }
                for word in (page.extract_words() or [])
            )
            pages.append(
                PDFPage(
                    number=index,
                    text=page.extract_text() or "",
                    tables=tables,
                    words=words,
                    table_row_bounds=table_row_bounds,
                    table_bounds=table_bounds,
                )
            )

    if not pages:
        raise ValueError(f"O PDF não contém páginas: {path}")

    return PDFDocument(path=path.resolve(), pages=tuple(pages))


def save_page_text(document: PDFDocument, output_path: str | Path) -> Path:
    """Save extracted text and detected table rows with page markers."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sections = []
    for page in document.pages:
        sections.append(f"===== PÁGINA {page.number} =====\n{page.text.strip()}\n")
        for table_number, table in enumerate(page.tables, start=1):
            sections.append(f"===== TABELA {table_number} - PÁGINA {page.number} =====")
            sections.extend(" | ".join(row) for row in table)
            sections.append("")
    destination.write_text("\n".join(sections), encoding="utf-8")
    return destination.resolve()
