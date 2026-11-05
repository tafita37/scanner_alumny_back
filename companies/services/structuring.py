"""
Structuration d'un document par l'agent IA (app `structuration`) : le texte extrait est
anonymisé, envoyé au LLM avec le secteur de l'entreprise, puis le résultat (données lues,
variables calculées, erreurs) est enregistré dans une `Extraction`.

Le texte des pages est du Markdown produit par Docling : les tableaux y figurent, et passent
donc par l'anonymisation comme le reste du texte.
"""
import json

from structuration.graphe import extraire
from structuration.schemas import SECTEURS

from ..models import Extraction
from ..metier.extraction import StatutExtraction
from .anonymization import anonymize_pages, deanonymize


class StructuringError(Exception):
    """Le document ne peut pas être envoyé à l'agent (secteur non pris en charge)."""


def build_text(pages: list[dict]) -> str:
    """Texte envoyé au LLM : les pages, chacune précédée de son numéro."""
    return '\n\n'.join(f"--- page {page['number']} ---\n{page['text']}" for page in pages)


def to_json(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def structure_document(document, pages: list[dict], conversion_errors: list[str]) -> Extraction:
    """
    Anonymise les pages extraites du document et les fait structurer par l'agent, qui reconnaît
    lui-même le type du document : document commercial (lu selon le secteur de l'entreprise de
    l'audit) ou comptes annuels. Le résultat est enregistré dans une nouvelle `Extraction`.
    Le LLM ne reçoit que des jetons (<PERSON_1>...) ; la correspondance jeton -> donnée
    personnelle reste en mémoire et sert à remettre les vraies valeurs dans le résultat
    avant de l'enregistrer.
    `conversion_errors` (pages que Docling n'a pas pu lire) est placé en tête des erreurs, et
    l'extraction passe alors « à vérifier » : une donnée de ces pages peut manquer ou être
    fausse sans que l'agent le sache.
    Lève StructuringError si le secteur de l'entreprise n'est pas pris en charge par l'agent.
    """
    sector = document.audit.company.industry.name.upper()
    if sector not in SECTEURS:
        raise StructuringError(
            f'Secteur « {document.audit.company.industry.name} » non pris en charge par l\'agent.'
        )
    anonymized_pages, mapping = anonymize_pages(pages)
    #afficher mapping pour debug
    print(f'--- Mapping pour le document {document.pk} ---')
    for token, value in mapping.values.items():
        print(f'{token:<20} = {value!r}')
    # Enregistrée avant l'appel au LLM (plusieurs secondes) : statut « en cours » visible en base.
    extraction = Extraction.objects.create(document=document)
    try:
        result = extraire(build_text(anonymized_pages), sector)
    except Exception as exc:
        # Erreur inattendue : l'extraction ne doit pas rester « en cours ».
        extraction.status = StatutExtraction.A_VERIFIER
        extraction.errors = to_json([*conversion_errors, f'Erreur interne : {type(exc).__name__}: {exc}'])
        extraction.save()
        raise
    # Conversion partielle : même si l'agent n'a rien relevé, un humain doit vérifier.
    extraction.status = StatutExtraction.A_VERIFIER if conversion_errors else result['statut']
    extraction.attempts = result['tentatives']
    extraction.input_tokens = result['tokens_entree']
    extraction.output_tokens = result['tokens_sortie']
    extraction.errors = to_json([*conversion_errors, *deanonymize(result['erreurs'], mapping)])
    # Échec après 3 essais : on garde la dernière réponse du LLM pour la vérification manuelle.
    extraction.json_extraction = to_json(
        deanonymize(result['extraction'] or result['extraction_brute'], mapping)
    )
    extraction.json_variables = to_json(deanonymize(result['variables'], mapping))
    extraction.save()
    return extraction
