"""
Structuration d'un document par l'agent IA (app `structuration`) : le texte extrait est
anonymisé, envoyé au LLM avec le secteur de l'entreprise, puis le résultat (données lues,
variables calculées, erreurs) est enregistré dans une `Extraction`.

Seul le texte des pages est envoyé : les tableaux de pdfplumber ne passent pas par
l'anonymisation, et leur contenu figure déjà dans le texte de la page.
"""
import json

from structuration.graphe import extraire
from structuration.schemas import SECTEURS

from ..models import Extraction
from ..metier.extraction import StatutExtraction
from .anonymization import anonymize_pages


class StructuringError(Exception):
    """Le document ne peut pas être envoyé à l'agent (secteur non pris en charge)."""


def build_text(pages: list[dict]) -> str:
    """Texte envoyé au LLM : les pages, chacune précédée de son numéro."""
    return '\n\n'.join(f"--- page {page['number']} ---\n{page['text']}" for page in pages)


def to_json(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def structure_document(document, pages: list[dict]) -> Extraction:
    """
    Anonymise les pages extraites du document et les fait structurer par l'agent, qui reconnaît
    lui-même le type du document : document commercial (lu selon le secteur de l'entreprise de
    l'audit) ou comptes annuels. Le résultat est enregistré dans une nouvelle `Extraction`.
    La correspondance jeton -> donnée personnelle reste en mémoire : le JSON enregistré garde
    les jetons (<PERSON_1>...).
    Lève StructuringError si le secteur de l'entreprise n'est pas pris en charge par l'agent.
    """
    sector = document.audit.company.industry.name.upper()
    if sector not in SECTEURS:
        raise StructuringError(
            f'Secteur « {document.audit.company.industry.name} » non pris en charge par l\'agent.'
        )
    anonymized_pages, _ = anonymize_pages(pages)
    # Enregistrée avant l'appel au LLM (plusieurs secondes) : statut « en cours » visible en base.
    extraction = Extraction.objects.create(document=document)
    try:
        result = extraire(build_text(anonymized_pages), sector)
    except Exception as exc:
        # Erreur inattendue : l'extraction ne doit pas rester « en cours ».
        extraction.status = StatutExtraction.A_VERIFIER
        extraction.errors = to_json([f'Erreur interne : {type(exc).__name__}: {exc}'])
        extraction.save()
        raise
    extraction.status = result['statut']
    extraction.attempts = result['tentatives']
    extraction.errors = to_json(result['erreurs'])
    # Échec après 3 essais : on garde la dernière réponse du LLM pour la vérification manuelle.
    extraction.json_extraction = to_json(result['extraction'] or result['extraction_brute'])
    extraction.json_variables = to_json(result['variables'])
    extraction.save()
    return extraction
