"""
Conversion d'un PDF en texte Markdown par Docling : analyse de la mise en page (colonnes,
tableaux, en-têtes et pieds de page) et OCR des seules zones sans texte natif (RapidOCR).
Un PDF natif, scanné ou mixte suit donc le même chemin.

Les modèles sont lourds à charger : le convertisseur est créé une seule fois, au premier appel,
puis réutilisé.

Docling tourne dans un processus séparé du serveur Django, CONVERSION_EXECUTOR : sa forte
consommation mémoire (PyTorch) ne s'ajoute pas à celle du serveur (spaCy pour l'anonymisation),
et s'il plante, seul ce processus meurt et il est remplacé au prochain appel, sans faire tomber
le serveur. Docling n'est importé que dans ce processus :
- l'importer suffit à charger PyTorch (~330 Mo) ;
- sous Windows, son lecteur de PDF (docling_parse) ne se charge pas après psycopg, qui a déjà
  chargé une autre version de libwinpthread-1.dll (celle de PostgreSQL).
"""
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import lru_cache
from pathlib import Path

# Langue de l'OCR, et moteur d'exécution du modèle (onnxruntime : le plus rapide sur CPU).
OCR_LANG = 'fr'
OCR_BACKEND = 'onnxruntime'

# Processus dédié à Docling, démarré au premier appel. Les conversions demandées en même temps
# par plusieurs requêtes passent l'une après l'autre.
CONVERSION_EXECUTOR = ProcessPoolExecutor(max_workers=1)


class DocumentConversionError(Exception):
    """Docling n'a pas pu convertir le document."""


@lru_cache(maxsize=1)
def get_converter(artifacts_path: str | None):
    """
    Crée le convertisseur Docling au premier appel.
    À n'appeler que dans le processus CONVERSION_EXECUTOR (voir run_conversion).
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(
        artifacts_path=artifacts_path,
        do_ocr=True,
        do_table_structure=True,
        # Mode par défaut : OCR des seules zones sans texte natif (page scannée, bande scannée...)
        ocr_options=RapidOcrOptions(lang=[OCR_LANG], backend=OCR_BACKEND),
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def conversion_errors(result) -> list[str]:
    """
    Erreurs d'un succès partiel, une par problème signalé par Docling, avec la page concernée
    quand il y en a une. Une page en échec reste dans le document mais sans texte.
    """
    return [
        f'Conversion du PDF, page {error.page_no} : {error.error_message}'
        if error.page_no is not None
        else f'Conversion du PDF : {error.error_message}'
        for error in result.errors
    ]


def run_conversion(pdf_path: Path, artifacts_path: str | None) -> dict:
    """
    Exécuté dans CONVERSION_EXECUTOR : {'pages': [{'number', 'text'}, ...], 'errors': [...]}.
    Un succès partiel (certaines pages en échec) est accepté, les autres pages restent utiles,
    mais ses erreurs sont renvoyées dans 'errors' (vide si la conversion est complète).
    """
    from docling.datamodel.base_models import ConversionStatus
    from docling_core.types.doc import ContentLayer

    result = get_converter(artifacts_path).convert(pdf_path, raises_on_error=False)
    if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
        details = '; '.join(error.error_message for error in result.errors) or result.status.value
        raise DocumentConversionError(f'Conversion impossible : {details}')
    errors = conversion_errors(result) if result.status == ConversionStatus.PARTIAL_SUCCESS else []
    document = result.document
    pages = [
        {
            'number': number,
            'text': document.export_to_markdown(
                page_no=number,
                # Le corps du document, plus les en-têtes et pieds de page (mentions légales,
                # échéance, IBAN...), que Docling range à part et n'exporte pas par défaut.
                included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
                # Texte destiné au LLM : pas d'échappement de « _ » ni de « & » (e-mails, références)
                escape_underscores=False,
                escape_html=False,
                # Logo, signature... : rien d'utile pour le LLM
                image_placeholder='',
            ),
        }
        for number in sorted(document.pages)
    ]
    return {'pages': pages, 'errors': errors}


def convert_pdf(pdf_path: Path, artifacts_path: str | None) -> dict:
    """
    Retourne le texte Markdown de chaque page du PDF, dans l'ordre, et les erreurs d'une
    conversion partielle : {'pages': [{'number', 'text'}, ...], 'errors': [...]}.
    Le travail est fait dans CONVERSION_EXECUTOR ; l'appelant attend le résultat.
    """
    global CONVERSION_EXECUTOR
    try:
        return CONVERSION_EXECUTOR.submit(run_conversion, pdf_path, artifacts_path).result()
    except BrokenProcessPool as exc:
        # Le processus Docling est mort (manque de mémoire...) : on en prépare un neuf pour les
        # appels suivants, sinon tous échoueraient jusqu'au redémarrage du serveur.
        CONVERSION_EXECUTOR = ProcessPoolExecutor(max_workers=1)
        raise DocumentConversionError('Conversion impossible : le processus Docling s\'est arrêté.') from exc
    except DocumentConversionError:
        raise
    except Exception as exc:
        raise DocumentConversionError(f'Conversion impossible : {exc}') from exc
