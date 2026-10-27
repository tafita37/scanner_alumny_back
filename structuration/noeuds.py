import json
import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import ValidationError

from .calculs import CALCULS_PAR_TYPE
from .coherence import CONTROLES_PAR_TYPE
from .etat import EtatExtraction
from .prompts import PROMPT_CLASSIFICATION, PROMPTS_PAR_TYPE
from .schemas import SCHEMAS_PAR_TYPE, Classification
load_dotenv()
MODELE = os.getenv("GROQ_MODELE")
MAX_TENTATIVES = 3
# Le début du document suffit pour savoir de quel type il est
LONGUEUR_CLASSIFICATION = 4000


@lru_cache
def _llm(schema: type):
    """Client Groq en mode strict, créé une seule fois par schéma de sortie."""
    return ChatGroq(model=MODELE, temperature=0, max_retries=2).with_structured_output(
        schema,
        method="json_schema",  # Structured Outputs de Groq
        strict=True,           # sortie forcément conforme au schéma
        include_raw=True,      # pour récupérer les tokens consommés
    )


def _tokens(etat: EtatExtraction, reponse: dict) -> dict:
    usage = getattr(reponse["raw"], "usage_metadata", None) or {}
    return {"tokens_entree": etat["tokens_entree"] + usage.get("input_tokens", 0),
            "tokens_sortie": etat["tokens_sortie"] + usage.get("output_tokens", 0)}


# 0. Classification : document commercial ou comptes annuels ?
def classification(etat: EtatExtraction) -> dict:
    messages = [SystemMessage(PROMPT_CLASSIFICATION), HumanMessage(etat["texte"][:LONGUEUR_CLASSIFICATION])]
    try:
        reponse = _llm(Classification).invoke(messages)
    except Exception as e:  # réseau, quota dépassé, clé invalide...
        return {"erreurs": etat["erreurs"] + [f"Classification, appel LLM : {type(e).__name__}: {e}"]}

    maj = _tokens(etat, reponse)
    if reponse["parsing_error"] is not None:
        return maj | {"erreurs": etat["erreurs"] + [f"Classification, JSON illisible : {reponse['parsing_error']}"]}

    categorie = reponse["parsed"].categorie
    if categorie == "commercial":
        return maj | {"type_extraction": etat["secteur"]}
    if categorie == "comptes_annuels":
        return maj | {"type_extraction": "COMPTES_ANNUELS"}
    return maj | {"erreurs": etat["erreurs"] + ["Document non reconnu : ni document commercial, ni comptes annuels."]}


# 1. Extraction : appel au LLM
def extraction(etat: EtatExtraction) -> dict:
    type_extraction = etat["type_extraction"]
    messages = [SystemMessage(PROMPTS_PAR_TYPE[type_extraction]), HumanMessage(etat["texte"])]

    # À partir du 2e essai : on montre au LLM sa réponse précédente et ses erreurs
    if etat["extraction_brute"] is not None and etat["erreurs_derniere_tentative"]:
        messages.append(AIMessage(json.dumps(etat["extraction_brute"], ensure_ascii=False)))
        messages.append(HumanMessage(
            "Ta réponse contient ces erreurs. Relis le document et corrige :\n- "
            + "\n- ".join(etat["erreurs_derniere_tentative"])
        ))

    maj = {"tentatives": etat["tentatives"] + 1}
    try:
        reponse = _llm(SCHEMAS_PAR_TYPE[type_extraction]).invoke(messages)
    except Exception as e:  # réseau, quota dépassé, clé invalide...
        err = [f"Appel LLM : {type(e).__name__}: {e}"]
        return maj | {"extraction_brute": None, "erreurs_derniere_tentative": err,
                      "erreurs": etat["erreurs"] + err}

    maj |= _tokens(etat, reponse)

    if reponse["parsing_error"] is not None:
        err = [f"JSON illisible : {reponse['parsing_error']}"]
        return maj | {"extraction_brute": None, "erreurs_derniere_tentative": err,
                      "erreurs": etat["erreurs"] + err}

    return maj | {"extraction_brute": reponse["parsed"].model_dump(), "erreurs_derniere_tentative": []}


# 2. Validation : schéma Pydantic puis contrôles arithmétiques
def validation(etat: EtatExtraction) -> dict:
    # Appel LLM ou JSON en échec : les erreurs sont déjà notées par l'extraction
    if etat["extraction_brute"] is None:
        return {}

    type_extraction = etat["type_extraction"]
    try:
        objet = SCHEMAS_PAR_TYPE[type_extraction].model_validate(etat["extraction_brute"])
    except ValidationError as e:
        err = [f"Schéma : {'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors()]
        return {"erreurs_derniere_tentative": err, "erreurs": etat["erreurs"] + err}

    err = CONTROLES_PAR_TYPE[type_extraction](objet)
    if err:
        return {"erreurs_derniere_tentative": err, "erreurs": etat["erreurs"] + err}

    maj = {"extraction": etat["extraction_brute"]}
    # Hors sujet : réponse valide, inutile de réessayer, mais un humain doit regarder
    if objet.type_document == "hors_sujet":
        maj["erreurs"] = etat["erreurs"] + [f"Document hors sujet pour le type {type_extraction}."]
    return maj


# 3. Calcul : le code Python calcule les variables
def calcul(etat: EtatExtraction) -> dict:
    type_extraction = etat["type_extraction"]
    objet = SCHEMAS_PAR_TYPE[type_extraction].model_validate(etat["extraction"])
    return {"variables": CALCULS_PAR_TYPE[type_extraction](objet), "statut": "ok"}


# 4. Échec : document non reconnu, hors sujet, ou 3 essais sans réponse correcte
def a_verifier(etat: EtatExtraction) -> dict:
    return {"statut": "a_verifier"}


# Fonctions de routage
def apres_classification(etat: EtatExtraction) -> str:
    return "extraction" if etat["type_extraction"] is not None else "a_verifier"


def apres_validation(etat: EtatExtraction) -> str:
    if etat["extraction"] is not None and etat["extraction"]["type_document"] == "hors_sujet":
        return "a_verifier"
    if not etat["erreurs_derniere_tentative"]:
        return "calcul"
    if etat["tentatives"] < MAX_TENTATIVES:
        return "extraction"
    return "a_verifier"
