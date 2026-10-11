"""
Extraction du texte et des tableaux d'un PDF (étape 1 du pipeline documentaire).

Chaque page est analysée séparément : une page qui contient une image est passée à l'OCR
(PaddleOCR) et marquée `needs_ocr=True` ; les autres restent sur l'extraction native.
"""
from pathlib import Path

import numpy as np
import pdfplumber
import pymupdf

from .ocr_extraction import ocr_image

# Résolution du rendu d'une page avant OCR.
OCR_DPI = 300


class PdfExtractionError(Exception):
    """PDF illisible : corrompu ou protégé par mot de passe."""


def page_has_image(page: pymupdf.Page) -> bool:
    """Vrai si au moins une image est affichée sur la page."""
    return bool(page.get_image_info())


def render_page(page: pymupdf.Page) -> np.ndarray:
    """Rend la page en image BGR (format attendu par PaddleOCR)."""
    pixmap = page.get_pixmap(dpi=OCR_DPI, alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def extract_pages(pdf_path: Path) -> list[dict]:
    """
    Retourne, pour chaque page, son texte : par OCR si la page contient une image,
    sinon natif, dans l'ordre de lecture (haut-gauche vers bas-droite).
    """
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise PdfExtractionError(f'PDF illisible : {exc}') from exc
    with doc:
        if doc.needs_pass:
            raise PdfExtractionError('PDF protégé par mot de passe.')
        pages = []
        for number, page in enumerate(doc, start=1):
            needs_ocr = page_has_image(page)
            text = ocr_image(render_page(page)) if needs_ocr else page.get_text('text', sort=True)
            pages.append({'number': number, 'text': text, 'needs_ocr': needs_ocr})
        return pages


def extract_tables_pdfplumber(pdf_path: Path, page_numbers: list[int]) -> list[dict]:
    """
    Retourne les tableaux détectés sur les pages demandées (numérotées à partir de 1),
    sous la forme {'page': n, 'rows': [[cellule, ...], ...]}. Une cellule vide vaut None.
    """
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for number in page_numbers:
            for rows in pdf.pages[number - 1].extract_tables():
                tables.append({'page': number, 'rows': rows})
    return tables


def extract_pdf(pdf_path: Path) -> dict:
    """
    Extrait le texte de chaque page (natif ou OCR) et les tableaux des pages sans image.
    Lève PdfExtractionError si le PDF est corrompu ou protégé, OcrExtractionError si l'OCR échoue.
    """
    pages = extract_pages(pdf_path)
    native_pages = [page['number'] for page in pages if not page['needs_ocr']]
    try:
        tables = extract_tables_pdfplumber(pdf_path, native_pages) if native_pages else []
    except Exception as exc:
        raise PdfExtractionError(f'Extraction des tableaux impossible : {exc}') from exc
    return {
        'nb_pages': len(pages),
        'needs_ocr': any(page['needs_ocr'] for page in pages),
        'pages': pages,
        'tables': tables,
    }
