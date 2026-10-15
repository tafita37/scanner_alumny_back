"""
Configuration de Presidio (regex + NER spaCy) pour détecter et anonymiser les données
personnelles d'un texte en français.

Le modèle spaCy `fr_core_news_lg` est lourd à charger : les moteurs sont instanciés une seule
fois, au premier appel, puis réutilisés.
"""
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngine, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
)
from presidio_anonymizer import AnonymizerEngine
from spacy.tokens import Span

LANGUAGE = 'fr'

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

class FrSpacyRecognizer(SpacyRecognizer):
    """
    SpacyRecognizer qui rejette les entités composées uniquement de mots ordinaires.

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
            result for result in results
            if has_proper_noun(doc.char_span(result.start, result.end))
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
        supported_regions=['FR'],
        context=['tél', 'téléphone', 'portable', 'mobile', 'fixe', 'fax'],
        leniency=0
    ))
    registry.add_recognizer(IbanRecognizer(
        supported_language=LANGUAGE,
        context=['iban', 'rib', 'compte', 'bancaire'],
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
