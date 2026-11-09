"""
Extraction du texte d'un PDF (étape 1 du pipeline documentaire).

Le PDF est d'abord ouvert par PyMuPDF, qui refuse rapidement, avec un message clair, un fichier
corrompu ou protégé, et lit le texte natif de chaque page (quelques millisecondes par page, sans
la structure des tableaux). Docling le convertit ensuite en Markdown, page par page : colonnes et
tableaux gardés, OCR des seules zones scannées (voir docling_conversion).

Docling est lent sur les tableaux (10 à 15 s par page de liasse fiscale) : pour des comptes
annuels, le texte natif sert à choisir les pages utiles (bilan, compte de résultat, annexe), et
Docling ne convertit que celles-ci (46 pages -> 6 sur une liasse, 8 min -> 1 min 40).
"""
from pathlib import Path

import pymupdf
from django.conf import settings

from structuration.noeuds import categorie_par_mots_cles
from structuration.pages import indices_pages_utiles

from .docling_conversion import convert_pdf


class PdfExtractionError(Exception):
    """PDF illisible : corrompu ou protégé par mot de passe."""


def read_native_text(pdf_path: Path) -> list[str]:
    """
    Texte natif de chaque page, dans l'ordre (chaîne vide pour une page scannée).
    Lève PdfExtractionError si le PDF est corrompu ou protégé par mot de passe.
    """
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise PdfExtractionError(f'PDF illisible : {exc}') from exc
    with doc:
        if doc.needs_pass:
            raise PdfExtractionError('PDF protégé par mot de passe.')
        return [page.get_text() for page in doc]


def pages_to_convert(native_texts: list[str]) -> list[int] | None:
    """
    Numéros (à partir de 1) des pages à faire convertir par Docling, ou None pour tout convertir.
    Seuls des comptes annuels sont réduits, et seulement quand le texte natif suffit à en juger :
    - le début du document ne contient que des mots-clés de comptes annuels (sinon, document
      commercial ou type incertain : le LLM le classera sur le document entier) ;
    - au moins une page d'états financiers est reconnue (sinon : PDF scanné, présentation
      inhabituelle).
    Une page sans texte natif (scannée) est toujours gardée : rien ne permet de l'écarter.
    """
    if categorie_par_mots_cles('\n'.join(native_texts)) != 'comptes_annuels':
        return None
    useful = indices_pages_utiles(native_texts)
    if useful is None:
        return None
    scanned = [index for index, text in enumerate(native_texts) if not text.strip()]
    indices = sorted({*useful, *scanned})
    if len(indices) == len(native_texts):
        return None
    return [index + 1 for index in indices]


def extract_pdf(pdf_path: Path) -> dict:
    """
    Extrait le texte Markdown des pages utiles (voir pages_to_convert), toutes le plus souvent :
    {'nb_pages', 'pages': [{'number', 'text'}, ...], 'errors': [...]}.
    'nb_pages' est le nombre de pages du PDF ; 'pages' ne contient que les pages converties,
    avec leur numéro dans le PDF.
    'errors' liste les pages que Docling n'a pas pu convertir (conversion partielle) ; elle est
    vide si toutes les pages demandées ont été lues.
    Lève PdfExtractionError si le PDF est corrompu ou protégé, DocumentConversionError si
    Docling échoue.
    """
    native_texts = read_native_text(pdf_path)
    conversion = convert_pdf(pdf_path, settings.DOCLING_ARTIFACTS_PATH, pages_to_convert(native_texts))
    return {'nb_pages': len(native_texts), 'pages': conversion['pages'], 'errors': conversion['errors']}
