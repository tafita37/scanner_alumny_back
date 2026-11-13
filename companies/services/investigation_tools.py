"""
Tools d'enquête de l'agent du questionnaire : chercher et lire dans le texte des documents d'un
audit ce que les données extraites ne contiennent pas (clause de révision de prix, pénalités de
retard, retenue de garantie, franco de port, frais inclus dans un forfait...).

- `rechercher_dans_documents(termes)` : comme un Ctrl+F sur tous les documents ; renvoie de courts
  extraits autour des passages trouvés, avec le document et la page.
- `lire_pages_document(document_id, pages)` : texte complet de quelques pages, quand un extrait ne
  suffit pas.

Le texte vient de la dernière extraction de chaque document (`Extraction.json_pages`, en clair). Il
est anonymisé avant d'être renvoyé au LLM, document par document, au premier besoin, avec la
correspondance du tour : une même personne garde le même jeton dans tous les documents, dans les
réponses aux questions précédentes et dans la sortie de l'agent (dé-anonymisée avec elle).

La logique (recherche, découpage des extraits, limites, anonymisation) est dans `AuditTexts`, qui
ne lit pas la base : elle est testée sur des pages écrites à la main. `make_investigation_tools`
charge le texte de l'audit et crée les tools.

Une erreur (document d'un autre audit, page absente, trop de termes...) est renvoyée au LLM sous la
forme {"erreur": "..."} : il peut la lire et corriger sa demande, au lieu de faire échouer le tour.
"""
import json
import re

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..models import Document
from .anonymization import PseudonymMapping, anonymize_pages, deanonymize, normalize_text, value_regex
from .indicators import latest_extractions
from .structuring import compact_tables

MAX_TERMS = 5
MAX_RESULTS = 10
# Caractères gardés avant et après un passage trouvé : un extrait fait environ 400 caractères.
SNIPPET_RADIUS = 200
# Des passages proches sont réunis dans un même extrait, sans qu'il dépasse cette longueur
# (sinon un mot présent sur chaque ligne d'un tableau renverrait la page entière).
MAX_SNIPPET_LENGTH = 800
MAX_PAGES_PER_READ = 3
ELLIPSIS = '…'
WHITESPACE = re.compile(r'\s')

SEARCH_TOOL_NAME = 'rechercher_dans_documents'
SEARCH_TOOL_DESCRIPTION = (
    "Recherche des mots dans le texte des documents de l'audit (devis, factures, conditions "
    "générales, annexe des comptes annuels...), pour vérifier la présence ou l'absence d'une "
    "information que les données extraites ne contiennent pas : clause de révision de prix, "
    "pénalités de retard, retenue de garantie, franco de port, frais inclus dans un forfait, "
    "dépréciations... Donner plusieurs formulations d'une même idée (5 termes au maximum) ; un "
    "passage est trouvé s'il contient l'un d'eux. Un terme trouve aussi les mots qui commencent par "
    "lui (« révis » trouve révision, révisable), sans tenir compte des majuscules ni des accents. "
    "Renvoie, pour chaque passage trouvé, le document, sa page, les termes trouvés et un extrait "
    "d'environ 400 caractères ; 10 extraits au maximum, 'nombre_total' donne le nombre réel (le "
    "dépasser : préciser la recherche). Aucun résultat : l'information n'est écrite dans aucun des "
    "documents cherchés ; 'documents_sans_texte' liste ceux dont le texte n'est pas disponible et "
    "qui n'ont donc pas pu être cherchés. Les données personnelles sont remplacées par des jetons "
    "(<PERSON_1>, <LOCATION_1>...), que l'on peut aussi chercher."
)
READ_TOOL_NAME = 'lire_pages_document'
READ_TOOL_DESCRIPTION = (
    "Lit le texte complet de pages d'un document de l'audit (3 pages au maximum par appel), quand "
    "un extrait renvoyé par rechercher_dans_documents ne suffit pas pour comprendre une clause ou un "
    "tableau. Les tableaux sont en Markdown. Pour des comptes annuels, seules les pages utiles "
    "(bilan, compte de résultat, annexe) sont disponibles. Les données personnelles sont remplacées "
    "par des jetons (<PERSON_1>, <LOCATION_1>...)."
)


class SearchArguments(BaseModel):
    termes: list[str] = Field(
        description='Mots ou expressions à chercher, 5 au maximum. Ex. : ["révision", "actualisation", "prix ferme"].'
    )


class ReadArguments(BaseModel):
    document_id: int = Field(description="Identifiant du document (dans le contexte ou un résultat de recherche).")
    pages: list[int] = Field(description='Numéros des pages à lire, 3 au maximum. Ex. : [12, 13].')


def term_pattern(term: str) -> re.Pattern:
    """
    Regex d'un terme : sans tenir compte des majuscules, des accents ni des espaces (« révision de
    prix » trouve « Revision\\nde  prix »). Le terme doit commencer un mot (« port » ne trouve pas
    « rapport ») mais peut ne pas le finir (« révis » trouve « révisable »).
    """
    return re.compile(rf'(?<!\w){value_regex(normalize_text(term))}', re.IGNORECASE)


def clean_terms(terms) -> list[str]:
    """Termes non vides, sans doublon, dans l'ordre donné."""
    cleaned = []
    for term in terms or []:
        term = term.strip() if isinstance(term, str) else ''
        if term and normalize_text(term) not in {normalize_text(t) for t in cleaned}:
            cleaned.append(term)
    return cleaned


def format_ranges(numbers) -> str:
    """[1, 2, 3, 4, 12, 13, 20] -> « 1 à 4, 12 à 13, 20 »."""
    numbers = sorted(numbers)
    ranges = []
    for number in numbers:
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return ', '.join(str(a) if a == b else f'{a} à {b}' for a, b in ranges)


def find_windows(text: str, patterns: list[tuple[str, re.Pattern]]) -> list[dict]:
    """
    Passages de la page qui contiennent un des termes : fenêtre de SNIPPET_RADIUS caractères de
    part et d'autre, les fenêtres qui se chevauchent étant réunies (dans la limite de
    MAX_SNIPPET_LENGTH). `first` / `last` : début du premier passage et fin du dernier.
    """
    matches = sorted(
        (match.start(), match.end(), term)
        for term, pattern in patterns
        for match in pattern.finditer(text)
    )
    windows = []
    for start, end, term in matches:
        low, high = max(0, start - SNIPPET_RADIUS), min(len(text), end + SNIPPET_RADIUS)
        current = windows[-1] if windows else None
        if current and low <= current['high'] and high - current['low'] <= MAX_SNIPPET_LENGTH:
            current['high'] = max(current['high'], high)
            current['last'] = max(current['last'], end)
            if term not in current['terms']:
                current['terms'].append(term)
        else:
            windows.append({'low': low, 'high': high, 'first': start, 'last': end, 'terms': [term]})
    return windows


def cut_snippet(text: str, window: dict) -> str:
    """
    Extrait de la fenêtre, coupé entre deux mots (jamais au milieu, ni avant ou après les passages
    trouvés), précédé ou suivi de « … » quand la page continue.
    """
    low, high = window['low'], window['high']
    if low > 0:
        space = WHITESPACE.search(text, low, window['first'])
        if space:
            low = space.end()
    if high < len(text):
        spaces = [space.start() for space in WHITESPACE.finditer(text, window['last'], high)]
        if spaces:
            high = spaces[-1]
    return (ELLIPSIS if low > 0 else '') + text[low:high].strip() + (ELLIPSIS if high < len(text) else '')


class AuditTexts:
    """
    Texte des documents d'un audit, pour les tools d'enquête.
    `documents` : {document_id: {'type_document': str | None, 'pages': {numéro: texte} | None}},
    texte en clair ; `pages` vaut None si le texte n'est pas disponible (document jamais extrait,
    ou extrait avant l'enregistrement du texte).
    `mapping` : correspondance des jetons du tour, complétée à chaque document anonymisé.
    """

    def __init__(self, documents: dict[int, dict], mapping: PseudonymMapping):
        self.documents = documents
        self.mapping = mapping
        self.anonymized = {}  # document_id -> {numéro: texte anonymisé, tableaux compactés}

    def anonymized_pages(self, document_id: int) -> dict[int, str]:
        """
        Pages anonymisées du document, calculées au premier besoin puis gardées pour le tour.
        Tout le document est anonymisé d'un coup : un nom détecté page 3 est aussi remplacé page 1.
        """
        if document_id not in self.anonymized:
            pages = [{'number': number, 'text': text} for number, text in self.documents[document_id]['pages'].items()]
            anonymized, _ = anonymize_pages(pages, self.mapping)
            self.anonymized[document_id] = {page['number']: compact_tables(page['text']) for page in anonymized}
        return self.anonymized[document_id]

    def documents_without_text(self) -> list[int]:
        return [document_id for document_id, document in self.documents.items() if document['pages'] is None]

    def search(self, terms) -> dict:
        terms = clean_terms(terms)
        if not terms:
            return {'erreur': 'Aucun terme à rechercher.'}
        if len(terms) > MAX_TERMS:
            return {'erreur': f'{MAX_TERMS} termes au maximum par recherche ({len(terms)} reçus).'}
        patterns = [(term, term_pattern(term)) for term in terms]
        # Pour ne pas anonymiser inutilement : un document n'est anonymisé que si son texte en clair
        # contient un des termes (un jeton cherché est d'abord remplacé par sa valeur).
        clear_patterns = [term_pattern(deanonymize(term, self.mapping)) for term in terms]

        results = []
        for document_id, document in self.documents.items():
            if document['pages'] is None:
                continue
            if not any(pattern.search(text) for pattern in clear_patterns for text in document['pages'].values()):
                continue
            for number, text in self.anonymized_pages(document_id).items():
                for window in find_windows(text, patterns):
                    results.append({
                        'document_id': document_id,
                        'type_document': document['type_document'],
                        'page': number,
                        'termes_trouves': window['terms'],
                        'extrait': cut_snippet(text, window),
                    })
        return {
            'resultats': results[:MAX_RESULTS],
            'nombre_total': len(results),
            'documents_sans_texte': self.documents_without_text(),
        }

    def read(self, document_id: int, pages) -> dict:
        if document_id not in self.documents:
            return {'erreur': (
                f"Le document {document_id} n'appartient pas à cet audit. "
                f"Documents de l'audit : {', '.join(map(str, self.documents)) or 'aucun'}."
            )}
        document = self.documents[document_id]
        if document['pages'] is None:
            return {'erreur': (
                f"Texte non disponible pour le document {document_id} : il n'a jamais été extrait, "
                "ou sa dernière extraction est antérieure à l'enregistrement du texte."
            )}
        numbers = sorted({number for number in pages or [] if isinstance(number, int)})
        if not numbers:
            return {'erreur': 'Aucune page demandée.'}
        if len(numbers) > MAX_PAGES_PER_READ:
            return {'erreur': f'{MAX_PAGES_PER_READ} pages au maximum par lecture ({len(numbers)} demandées).'}
        available = format_ranges(document['pages'])
        found = [number for number in numbers if number in document['pages']]
        missing = [number for number in numbers if number not in document['pages']]
        if not found:
            return {'erreur': (
                f"Pages {', '.join(map(str, missing))} absentes du document {document_id}. "
                f"Pages disponibles : {available}."
            )}
        anonymized = self.anonymized_pages(document_id)
        result = {
            'document_id': document_id,
            'type_document': document['type_document'],
            'pages': [{'page': number, 'texte': anonymized[number]} for number in found],
        }
        if missing:
            result['pages_absentes'] = missing
            result['pages_disponibles'] = available
        return result


def load_audit_documents(audit_id: int) -> dict[int, dict]:
    """
    Documents de l'audit au format de `AuditTexts` : type et texte (en clair) de la dernière
    extraction de chacun. Seul accès à la base des tools d'enquête.
    """
    latest = latest_extractions(audit_id, with_pages=True)
    documents = {}
    for document_id in Document.objects.filter(audit_id=audit_id).order_by('id').values_list('id', flat=True):
        extraction = latest.get(document_id)
        data = json.loads(extraction.json_extraction) if extraction and extraction.json_extraction else None
        pages = json.loads(extraction.json_pages) if extraction and extraction.json_pages else None
        documents[document_id] = {
            'type_document': data.get('type_document') if isinstance(data, dict) else None,
            'pages': {page['number']: page['text'] for page in sorted(pages, key=lambda p: p['number'])} if pages else None,
        }
    return documents


def make_investigation_tools(audit_id: int, mapping: PseudonymMapping) -> list[BaseTool]:
    """
    Tools d'enquête liés à un audit : l'identifiant de l'audit est fixé ici, pas choisi par le LLM,
    qui ne peut donc lire que les documents de cet audit. Le texte est chargé une fois, à la
    création ; chaque document est anonymisé au premier besoin avec `mapping`, la correspondance du
    tour, que l'appelant garde pour dé-anonymiser la sortie de l'agent.
    """
    texts = AuditTexts(load_audit_documents(audit_id), mapping)

    @tool(SEARCH_TOOL_NAME, description=SEARCH_TOOL_DESCRIPTION, args_schema=SearchArguments)
    def rechercher_dans_documents(termes: list[str]) -> str:
        return json.dumps(texts.search(termes), ensure_ascii=False)

    @tool(READ_TOOL_NAME, description=READ_TOOL_DESCRIPTION, args_schema=ReadArguments)
    def lire_pages_document(document_id: int, pages: list[int]) -> str:
        return json.dumps(texts.read(document_id, pages), ensure_ascii=False)

    return [rechercher_dans_documents, lire_pages_document]
