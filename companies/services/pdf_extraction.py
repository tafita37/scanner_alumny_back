"""
Extraction du texte d'un PDF (étape 1 du pipeline documentaire).

Le PDF est d'abord ouvert par PyMuPDF pour refuser rapidement, avec un message clair, un fichier
corrompu ou protégé. Docling le convertit ensuite en Markdown, page par page : colonnes et
tableaux gardés, OCR des seules zones scannées (voir docling_conversion).
"""
from pathlib import Path

import pymupdf
from django.conf import settings

from .docling_conversion import convert_pdf


class PdfExtractionError(Exception):
    """PDF illisible : corrompu ou protégé par mot de passe."""


def check_pdf(pdf_path: Path) -> None:
    """Lève PdfExtractionError si le PDF est corrompu ou protégé par mot de passe."""
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise PdfExtractionError(f'PDF illisible : {exc}') from exc
    with doc:
        if doc.needs_pass:
            raise PdfExtractionError('PDF protégé par mot de passe.')


def extract_pdf(pdf_path: Path) -> dict:
    """
    Extrait le texte Markdown de chaque page :
    {'nb_pages', 'pages': [{'number', 'text'}, ...], 'errors': [...]}.
    'errors' liste les pages que Docling n'a pas pu convertir (conversion partielle) ; elle est
    vide si tout le document a été lu.
    Lève PdfExtractionError si le PDF est corrompu ou protégé, DocumentConversionError si
    Docling échoue.
    """
    check_pdf(pdf_path)
    conversion = convert_pdf(pdf_path, settings.DOCLING_ARTIFACTS_PATH)
    pages = conversion['pages']
    return {'nb_pages': len(pages), 'pages': pages, 'errors': conversion['errors']}
