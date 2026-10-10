"""
Extraction native du texte et des tableaux d'un PDF (étape 1 du pipeline documentaire).

Chaque page est analysée séparément : une page sans couche de texte exploitable
(scan, police mal encodée) est marquée `needs_ocr=True` pour être passée à l'OCR ensuite.
"""
from pathlib import Path

import pdfplumber
import pymupdf

# Seuils à calibrer sur de vrais devis (Sprint 3).
MIN_CHARS_PER_PAGE = 100      # en dessous : probablement une page scannée
MAX_BAD_CHAR_RATIO = 0.10     # au-dessus : texte corrompu (symboles, �)

# Zone d'usage privé Unicode : ce que renvoie PyMuPDF quand l'encodage d'une police est cassé.
PRIVATE_USE_AREA = range(0xE000, 0xF900)


class PdfExtractionError(Exception):
    """PDF illisible : corrompu ou protégé par mot de passe."""


def extract_text_pymupdf(pdf_path: Path) -> list[str]:
    """Retourne le texte de chaque page, dans l'ordre de lecture (haut-gauche vers bas-droite)."""
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise PdfExtractionError(f'PDF illisible : {exc}') from exc
    with doc:
        if doc.needs_pass:
            raise PdfExtractionError('PDF protégé par mot de passe.')
        return [page.get_text('text', sort=True) for page in doc]


def extract_tables_pdfplumber(pdf_path: Path, page_numbers: list[int]) -> list[dict]:
    """
    Retourne les tableaux détectés sur les pages demandées (numérotées à partir de 1),
    sous la forme {'page': n, 'rows': [[cellule, ...], ...]}. Une cellule vide vaut None.
    """
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for number in page_numbers:
            print(f'Extraction des tableaux de la page {number}...\n')
            for rows in pdf.pages[number - 1].extract_tables():
                print(rows)
                tables.append({'page': number, 'rows': rows})
    return tables


def bad_char_ratio(text: str) -> float:
    """Part de caractères suspects : remplacement Unicode, contrôle, zone d'usage privé."""
    if not text:
        return 1.0
    bad = sum(
        1 for c in text
        if c == '�'
        or (ord(c) < 32 and c not in '\n\r\t')
        or ord(c) in PRIVATE_USE_AREA
    )
    return bad / len(text)


def page_needs_ocr(text: str) -> bool:
    """Décide si le texte natif d'une page est inutilisable et qu'il faut passer à l'OCR."""
    return len(text.strip()) < MIN_CHARS_PER_PAGE or bad_char_ratio(text) > MAX_BAD_CHAR_RATIO


def extract_pdf(pdf_path: Path) -> dict:
    """
    Extrait le texte de chaque page et les tableaux des pages au texte natif exploitable.
    Lève PdfExtractionError si le PDF est corrompu ou protégé.
    """
    pages = [
        {'number': number, 'text': text, 'needs_ocr': page_needs_ocr(text)}
        for number, text in enumerate(extract_text_pymupdf(pdf_path), start=1)
    ]
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
