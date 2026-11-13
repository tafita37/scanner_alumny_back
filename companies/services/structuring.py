"""
Structuration d'un document par l'agent IA (app `structuration`) : le texte extrait est
anonymisé, envoyé au LLM avec le secteur de l'entreprise, puis le résultat (données lues,
variables calculées, erreurs) est enregistré dans une `Extraction`.

Le texte des pages est du Markdown produit par Docling : les tableaux y figurent, et passent
donc par l'anonymisation comme le reste du texte.
"""
import json
import re

from structuration.graphe import extraire
from structuration.schemas import SECTEURS

from ..models import Extraction
from ..metier.extraction import StatutExtraction
from .anonymization import anonymize_pages, deanonymize


class StructuringError(Exception):
    """Le document ne peut pas être envoyé à l'agent (secteur non pris en charge)."""


# Séparateur de cellules d'un tableau Markdown (un « \| » échappé fait partie du contenu).
CELL_SEPARATOR = re.compile(r'(?<!\\)\|')
# Cellule de la ligne qui sépare l'en-tête du corps d'un tableau : « ------ », « :----: »...
SEPARATOR_CELL = re.compile(r':?-+:?')


def compact_table_row(line: str) -> str:
    """
    Ligne de tableau Markdown sans l'alignement des colonnes :
    « | Capital social   |   10 000 |      | » -> « | Capital social | 10 000 | | »,
    « |------------------|---------:|------| » -> « |---|---|---| ».
    """
    cells = [cell.strip() for cell in CELL_SEPARATOR.split(line.strip())[1:-1]]
    if not cells:
        return line.strip()
    if all(SEPARATOR_CELL.fullmatch(cell) for cell in cells):
        return '|' + '|'.join('---' for _ in cells) + '|'
    return '|' + '|'.join(f' {cell} ' if cell else ' ' for cell in cells) + '|'


def compact_tables(text: str) -> str:
    """
    Docling aligne les colonnes de ses tableaux avec des espaces et des tirets : sans intérêt
    pour le LLM, ils représentent une bonne part des tokens d'une liasse fiscale, faite presque
    entièrement de tableaux. Les autres lignes ne sont pas modifiées.
    """
    return '\n'.join(
        compact_table_row(line) if line.lstrip().startswith('|') and line.rstrip().endswith('|') else line
        for line in text.split('\n')
    )


def build_text(pages: list[dict]) -> str:
    """Texte envoyé au LLM : les pages, chacune précédée de son numéro, tableaux compactés."""
    return '\n\n'.join(f"--- page {page['number']} ---\n{compact_tables(page['text'])}" for page in pages)


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
    Les pages en clair sont enregistrées dans `json_pages` dès la création de l'extraction, même si
    la structuration échoue ensuite : l'agent du questionnaire peut les relire.
    Lève StructuringError si le secteur de l'entreprise n'est pas pris en charge par l'agent.
    """
    sector = document.audit.company.industry.name.upper()
    if sector not in SECTEURS:
        raise StructuringError(
            f'Secteur « {document.audit.company.industry.name} » non pris en charge par l\'agent.'
        )
    anonymized_pages, mapping = anonymize_pages(pages)
    extraction = Extraction.objects.create(
        document=document,
        json_pages=to_json([{'number': page['number'], 'text': page['text']} for page in pages]),
    )
    try:
        result = extraire(build_text(anonymized_pages), sector, document.audit.company.siren_number)
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
