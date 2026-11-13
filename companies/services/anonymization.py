"""
Configuration de Presidio (regex + NER spaCy) pour détecter et anonymiser les données
personnelles d'un texte en français.

Le modèle spaCy `fr_core_news_lg` est lourd à charger : les moteurs sont instanciés une seule
fois, au premier appel, puis réutilisés.
"""
import copy
import re
import unicodedata
from functools import lru_cache, partial

import phonenumbers
from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpEngine, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
)
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import ConflictResolutionStrategy, OperatorConfig
from spacy.tokens import Span

LANGUAGE = 'fr'

# Pays dont les formats de numéro de téléphone sont reconnus (et normalisés).
PHONE_REGION = 'FR'

# Jeton qui remplace une donnée personnelle dans le texte envoyé au LLM, ex. <PERSON_1>.
TOKEN_FORMAT = '<{entity_type}_{number}>'
TOKEN_PATTERN = re.compile(r'(<[A-Z_]+_\d+>)')

# Types dont les valeurs détectées sont recherchées partout dans le document (propagation).
# Téléphones et IBAN n'en ont pas besoin : leur format est reconnu quelle que soit l'écriture.
PROPAGATED_ENTITIES = {'PERSON', 'LOCATION', 'EMAIL_ADDRESS'}
# En dessous de cette longueur, une valeur propagée remplacerait trop de mots ordinaires.
MIN_PROPAGATED_LENGTH = 3

# Lettres accentuées admises à la place de leur lettre de base dans la propagation.
ACCENTED_LETTERS = 'àáâãäåçèéêëìíîïñòóôõöùúûüýÿ'

# Le modèle français produit PER, LOC, ORG et MISC. ORG est ignoré : le nom d'une entreprise
# n'est pas une donnée personnelle, et spaCy confond souvent les libellés comptables avec
# des organisations. MISC est trop bruité pour être utile.
NLP_CONFIGURATION = {
    'nlp_engine_name': 'spacy',
    'models': [{'lang_code': LANGUAGE, 'model_name': 'fr_core_news_lg'}],
    'ner_model_configuration': {
        'model_to_presidio_entity_mapping': {
            'PER': 'PERSON',
            'LOC': 'LOCATION',
        },
        'labels_to_ignore': ['ORG', 'MISC'],
    },
}

# Adresses postales : spaCy ne reconnaît que les noms de villes, pas « 33 avenue de la Gare »
# ni « 16000 ». Toutes les adresses sont masquées, sans chercher à distinguer celle d'un client
# particulier de celle d'une entreprise.
# Espace horizontal : une adresse ne déborde jamais sur la ligne suivante.
SPACE = r'[^\S\n]'
STREET_TYPES = (
    r'rue|avenue|av|boulevard|bd|bld|bvd|chemin|chem|all[ée]e|impasse|imp|place|route|rte'
    r'|quai|square|passage|r[ée]sidence|lotissement|hameau|lieu[- ]dit|chauss[ée]e|faubourg'
    r'|fbg|sentier|esplanade|rond[- ]point|cit[ée]|villa|mont[ée]e|traverse|parvis'
)
# « 16000 Angoulême », « 17000 La Rochelle Cedex 9 » : code postal (département 01 à 98) suivi
# d'un nom avec majuscule (sauf une unité monétaire : « 12500 Euros »).
CEDEX = rf'cedex(?:{SPACE}+\d{{1,2}})?'
CITY_WORD = r"(?!cedex\b)(?-i:[A-ZÀ-Ý])[\w'’\-]*"
POSTAL_CODE_CITY = (
    rf'(?:0[1-9]|[1-8]\d|9[0-8])\d{{3}}{SPACE}+(?!(?:eur|euros?|ht|ttc)\b){CITY_WORD}'
    rf"(?:{SPACE}+(?:{CITY_WORD}|sur|sous|l[èe]s|en|de|du|des|la|le|aux?)){{0,4}}"
    rf'(?:{SPACE}+{CEDEX})?'
)
# Mots qui ouvrent une autre information sur la même ligne : ils arrêtent le nom de la voie.
STREET_STOP_WORDS = r't[ée]l|fax|e-?mail|mail|port|mobile|siret|siren|tva'
# « 33 avenue de la Gare », « 12 bis rue du 8 Mai 1945 16000 Angoulême » : numéro, type de voie,
# jusqu'à 6 mots (arrêtés par une virgule, une fin de ligne ou une cellule de tableau), puis
# éventuellement le code postal et la ville sur la même ligne.
STREET_REGEX = (
    rf'(?<![\w.,])\d{{1,4}}(?:{SPACE}?(?:bis|ter|quater|[a-d]))?,?{SPACE}+'
    rf'(?:{STREET_TYPES})\b\.?'
    rf"(?:{SPACE}+(?!\d{{5}}\b|(?:{STREET_STOP_WORDS})\b)[\w'’.\-]+){{1,6}}"
    rf'(?:,?{SPACE}+{POSTAL_CODE_CITY})?'
)
# Code postal et ville seuls (adresse sur deux lignes) : admis seulement en début de ligne,
# d'élément de liste ou de cellule de tableau, pour ne pas prendre « Soit 25000 Total » ou un
# numéro de facture pour un code postal.
POSTAL_CODE_REGEX = (
    rf'(?:(?<=^)|(?<=^{SPACE})|(?<=\|)|(?<=\|{SPACE})|(?<=^-{SPACE}))'
    rf'{POSTAL_CODE_CITY}'
)
# Score bas : quand une adresse chevauche en partie une autre entité (téléphone, nom en fin
# de ligne), c'est l'adresse qui est raccourcie, l'autre entité garde son jeton.
ADDRESS_SCORE = 0.3


# Natures grammaticales (étiquettes spaCy) admises dans un nom de personne ou de lieu :
# nom propre, ou mot inconnu du modèle (cas fréquent d'un nom de famille isolé).
PROPER_NOUN_TAGS = {'PROPN', 'X'}

def has_proper_noun(span: Span | None) -> bool:
    """
    Vrai si au moins un mot du passage est un nom propre (ou inconnu du modèle).
    Passage introuvable dans le Doc : on garde l'entité (mieux vaut masquer à tort que laisser fuir).
    """
    if span is None:
        return True
    return any(token.pos_ in PROPER_NOUN_TAGS for token in span)

def split_lines(result: RecognizerResult, text: str) -> list[RecognizerResult]:
    """
    Découpe une entité en un morceau par ligne, sans les espaces autour : une entité ne déborde
    jamais sur la ligne suivante. Docling sépare les blocs de la page par une ligne vide, et spaCy
    prend sinon « Élodie Guerin\\n\\nTél » pour un seul nom.
    """
    pieces = []
    for match in re.finditer(r'[^\n]+', text[result.start:result.end]):
        line = match.group()
        start = result.start + match.start() + len(line) - len(line.lstrip())
        end = result.start + match.start() + len(line.rstrip())
        if start < end:
            piece = copy.copy(result)
            piece.start, piece.end = start, end
            pieces.append(piece)
    return pieces


class FrSpacyRecognizer(SpacyRecognizer):
    """
    SpacyRecognizer qui découpe les entités ligne par ligne, puis rejette les morceaux composés
    uniquement de mots ordinaires.

    Sur le texte issu de l'OCR (une ligne par zone de texte, sans phrase autour), la NER de
    spaCy prend souvent un mot isolé avec majuscule pour une personne (ex. l'en-tête de colonne
    « Arrêts »), alors que l'analyse grammaticale du même modèle le classe bien en nom commun.
    """

    def analyze(self, text, entities, nlp_artifacts=None):
        results = super().analyze(text, entities, nlp_artifacts)
        if not results:
            return results
        doc = nlp_artifacts.tokens
        return [
            piece for result in results for piece in split_lines(result, text)
            if has_proper_noun(doc.char_span(piece.start, piece.end, alignment_mode='contract'))
        ]



@lru_cache(maxsize=1)
def get_nlp_engine() -> NlpEngine:
    """Charge le moteur NLP spaCy français au premier appel."""
    return NlpEngineProvider(nlp_configuration=NLP_CONFIGURATION).create_engine()


def build_registry() -> RecognizerRegistry:
    """
    Reconnaisseurs actifs en français. Les reconnaisseurs prédéfinis de Presidio ne sont
    enregistrés que pour l'anglais : ils sont redéclarés ici avec un contexte en français.
    """
    registry = RecognizerRegistry(supported_languages=[LANGUAGE])
    registry.add_recognizer(FrSpacyRecognizer(
        supported_language=LANGUAGE,
        supported_entities=['PERSON', 'LOCATION'],
    ))
    registry.add_recognizer(EmailRecognizer(
        supported_language=LANGUAGE,
        context=['mail', 'e-mail', 'courriel'],
    ))
    registry.add_recognizer(PhoneRecognizer(
        supported_language=LANGUAGE,
        supported_regions=[PHONE_REGION],
        context=['tél', 'téléphone', 'portable', 'mobile', 'fixe', 'fax'],
        leniency=0
    ))
    registry.add_recognizer(IbanRecognizer(
        supported_language=LANGUAGE,
        context=['iban', 'rib', 'compte', 'bancaire'],
    ))
    registry.add_recognizer(PatternRecognizer(
        supported_entity='ADDRESS',
        supported_language=LANGUAGE,
        patterns=[
            Pattern('street', STREET_REGEX, ADDRESS_SCORE),
            Pattern('postal_code_city', POSTAL_CODE_REGEX, ADDRESS_SCORE),
        ],
    ))
    return registry


@lru_cache(maxsize=1)
def get_analyzer() -> AnalyzerEngine:
    """Moteur de détection des données personnelles, configuré pour le français."""
    return AnalyzerEngine(
        nlp_engine=get_nlp_engine(),
        registry=build_registry(),
        supported_languages=[LANGUAGE],
    )


def find_personal_data(text: str) -> list[dict]:
    """
    Données personnelles détectées dans le texte, dans l'ordre d'apparition :
    type d'entité, valeur trouvée, position (début, fin) et score de confiance.
    """
    results = get_analyzer().analyze(text=text, language=LANGUAGE)
    return [
        {
            'entity_type': result.entity_type,
            'value': text[result.start:result.end],
            'start': result.start,
            'end': result.end,
            'score': round(result.score, 2),
        }
        for result in sorted(results, key=lambda result: result.start)
    ]


@lru_cache(maxsize=1)
def get_anonymizer() -> AnonymizerEngine:
    """Moteur de remplacement des entités détectées (indépendant de la langue)."""
    return AnonymizerEngine()


def normalize_value(entity_type: str, value: str) -> str:
    """
    Forme canonique d'une valeur, pour qu'une même donnée écrite de plusieurs façons reçoive
    le même jeton : « 06 12 34 56 78 » = « +33612345678 », « DUPONT » = « Dupont » = « dupont ».
    """
    if entity_type == 'PHONE_NUMBER':
        try:
            number = phonenumbers.parse(value, PHONE_REGION)
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            return re.sub(r'\D', '', value)
    if entity_type == 'IBAN_CODE':
        return re.sub(r'[^0-9A-Z]', '', value.upper())
    return normalize_text(value)


def strip_accents(value: str) -> str:
    """« Angoulême » -> « Angouleme »."""
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()


def normalize_text(value: str) -> str:
    """Minuscules, sans accents, espaces réduits : « JEAN  Dupônt » -> « jean dupont »."""
    return ' '.join(strip_accents(value).lower().split())


class PseudonymMapping:
    """
    Correspondance entre les jetons et les données personnelles d'un document.
    Une seule instance par document : une même donnée reçoit le même jeton sur toutes les pages.
    Contient les données en clair : à garder en mémoire le temps de la requête, jamais en base
    ni dans les logs.
    """

    def __init__(self):
        self.tokens = {}    # (type d'entité, valeur normalisée) -> jeton
        self.values = {}    # jeton -> valeur d'origine (première écriture rencontrée)
        self.counters = {}  # type d'entité -> dernier numéro attribué

    def token_for(self, entity_type: str, value: str) -> str:
        """Jeton de la valeur : celui déjà attribué, sinon un nouveau (<TYPE_n+1>)."""
        key = (entity_type, normalize_value(entity_type, value))
        if key not in self.tokens:
            self.counters[entity_type] = self.counters.get(entity_type, 0) + 1
            token = TOKEN_FORMAT.format(entity_type=entity_type, number=self.counters[entity_type])
            self.tokens[key] = token
            self.values[token] = value
        return self.tokens[key]


def anonymize_text(text: str, mapping: PseudonymMapping) -> str:
    """Remplace chaque donnée personnelle détectée dans le texte par son jeton dans `mapping`."""
    results = get_analyzer().analyze(text=text, language=LANGUAGE)
    operators = {
        entity_type: OperatorConfig('custom', {'lambda': partial(mapping.token_for, entity_type)})
        for entity_type in {result.entity_type for result in results}
    }
    # Une entité contenue dans une autre est écartée (« Angoulême » dans l'adresse complète) ;
    # deux entités qui se chevauchent en partie sont raccourcies au lieu de se superposer.
    return get_anonymizer().anonymize(
        text=text,
        analyzer_results=results,
        operators=operators,
        conflict_resolution=ConflictResolutionStrategy.REMOVE_INTERSECTIONS,
    ).text


def value_regex(normalized_value: str) -> str:
    """
    Regex d'une valeur normalisée qui la retrouve quels que soient ses accents et ses espaces
    (la casse est ignorée par le drapeau IGNORECASE) : « jean dupont » trouve aussi
    « JEAN  DUPONT » ou « Jéan\\nDupont ».
    """
    parts = []
    for char in normalized_value:
        if char == ' ':
            parts.append(r'\s+')
            continue
        variants = [char] + [letter for letter in ACCENTED_LETTERS if strip_accents(letter) == char]
        parts.append(f"[{''.join(map(re.escape, variants))}]" if len(variants) > 1 else re.escape(char))
    return ''.join(parts)


def propagate_tokens(text: str, mapping: PseudonymMapping) -> str:
    """
    Remplace dans le texte les autres écritures des valeurs déjà détectées ailleurs dans le
    document : « Jean Dupont » détecté page 1 fait aussi remplacer « JEAN DUPONT » page 2, que
    spaCy n'a pas reconnu. Les jetons déjà présents dans le texte ne sont pas touchés.
    """
    lookup = {
        normalized: token
        for (entity_type, normalized), token in mapping.tokens.items()
        if entity_type in PROPAGATED_ENTITIES and len(normalized) >= MIN_PROPAGATED_LENGTH
    }
    if not lookup:
        return text
    # Valeurs les plus longues d'abord : « jean dupont » doit l'emporter sur « jean ».
    alternatives = '|'.join(value_regex(value) for value in sorted(lookup, key=len, reverse=True))
    pattern = re.compile(rf'(?<!\w)(?:{alternatives})(?!\w)', re.IGNORECASE)
    segments = TOKEN_PATTERN.split(text)
    # Indices pairs : texte entre les jetons ; indices impairs : jetons, laissés tels quels.
    for index in range(0, len(segments), 2):
        segments[index] = pattern.sub(
            lambda match: lookup.get(normalize_text(match.group(0)), match.group(0)),
            segments[index],
        )
    return ''.join(segments)


def anonymize_pages(pages: list[dict], mapping: PseudonymMapping | None = None) -> tuple[list[dict], PseudonymMapping]:
    """
    Anonymise le texte de chaque page extraite (même format que extract_pdf) avec une
    correspondance commune à tout le document. Renvoie les pages anonymisées et la correspondance.
    `mapping` : correspondance à compléter, partagée par plusieurs appels (une même donnée garde
    alors le même jeton dans tous les documents) ; une nouvelle par défaut.
    """
    mapping = mapping if mapping is not None else PseudonymMapping()
    anonymized_pages = [{**page, 'text': anonymize_text(page['text'], mapping)} for page in pages]
    # Seconde passe, une fois toutes les pages analysées : une valeur détectée page 3 est aussi
    # remplacée page 1.
    anonymized_pages = [
        {**page, 'text': propagate_tokens(page['text'], mapping)} for page in anonymized_pages
    ]
    return anonymized_pages, mapping


def deanonymize(value, mapping: PseudonymMapping):
    """
    Remet les données personnelles à la place des jetons dans une valeur JSON (texte, liste,
    dictionnaire), par exemple la réponse du LLM. Un jeton inconnu de `mapping` reste tel quel.
    """
    if isinstance(value, str):
        return TOKEN_PATTERN.sub(lambda match: mapping.values.get(match.group(0), match.group(0)), value)
    if isinstance(value, list):
        return [deanonymize(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: deanonymize(item, mapping) for key, item in value.items()}
    return value
