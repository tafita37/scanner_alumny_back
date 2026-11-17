"""
Modèle de langage commun à l'extraction des documents (`structuration`) et au questionnaire
adaptatif (`questionnaire`) : gpt-oss-120b chez Cerebras, par son API compatible OpenAI
(`ChatOpenAI` + `base_url`). Clé : CEREBRAS_API_KEY ; modèle : CEREBRAS_MODELE (facultatif).

Groq, utilisé auparavant, limite les comptes gratuits à 8 000 tokens par minute : trop peu pour un
agent, qui renvoie tout l'historique à chaque appel, et pour les longs documents.

Une limite atteinte (429 : requêtes ou tokens par minute) n'est pas une erreur : l'appel est relancé
après une attente, jusqu'à ce que la minute soit passée. Les deux modules partagent les limites du
compte (sur l'offre d'essai : 5 requêtes et 30 000 tokens par minute).
"""
import os

import openai
from dotenv import load_dotenv
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

load_dotenv()
URL_CEREBRAS = "https://api.cerebras.ai/v1"
MODELE = os.getenv("CEREBRAS_MODELE", "gpt-oss-120b")

# Erreurs passagères (limite par minute atteinte, réseau, panne du fournisseur) : l'appel est relancé
# après 15 s, puis 30 s, puis 60 s... (attentes cumulées : un peu plus de 2 minutes au total).
ERREURS_PASSAGERES = (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)
MAX_NOUVEAUX_ESSAIS = 4
ATTENTE_INITIALE = 15
ATTENTE_MAX = 60


def erreur_passagere(erreur: Exception) -> bool:
    return isinstance(erreur, ERREURS_PASSAGERES)


def modele(effort_raisonnement: str, max_tokens: int) -> ChatOpenAI:
    """Client du modèle ; `effort_raisonnement` : low, medium ou high (raisonnement de gpt-oss)."""
    return ChatOpenAI(
        model=MODELE,
        base_url=URL_CEREBRAS,
        api_key=os.getenv("CEREBRAS_API_KEY"),
        temperature=0,
        max_retries=0,            # nouveaux essais gérés ici, avec des attentes adaptées aux limites
        max_tokens=max_tokens,
        reasoning_effort=effort_raisonnement,
        use_responses_api=False,  # API Chat Completions, celle que Cerebras propose
    )


def avec_nouveaux_essais(runnable: Runnable) -> Runnable:
    """Relance l'appel après une attente en cas d'erreur passagère (pour un appel hors agent)."""
    return runnable.with_retry(
        retry_if_exception_type=ERREURS_PASSAGERES,
        wait_exponential_jitter=True,
        exponential_jitter_params={"initial": ATTENTE_INITIALE, "max": ATTENTE_MAX},
        stop_after_attempt=MAX_NOUVEAUX_ESSAIS + 1,
    )
