"""
Nœuds du graphe du questionnaire : enquête (agent), rédaction (LLM sans tools), validation (code).

Pourquoi deux appels distincts plutôt qu'un agent qui rend directement le JSON : constaté sur Groq,
un même appel ne pouvait pas à la fois proposer des tools et imposer un format JSON strict (« json
mode cannot be combined with tool/function calling »), et le tool de sortie de `ToolStrategy` était
mal appelé par gpt-oss (nom de tool déformé, requête rejetée). L'agent enquête donc librement et
conclut en texte ; la rédaction met ses conclusions au format strict, comme l'extraction des
documents. Cette séparation ne dépend d'aucun fournisseur.

Modèle et nouveaux essais (limite par minute atteinte...) : voir `fournisseur_llm`, commun avec
l'extraction des documents.
"""
from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from fournisseur_llm import (
    ATTENTE_INITIALE,
    ATTENTE_MAX,
    MAX_NOUVEAUX_ESSAIS,
    avec_nouveaux_essais,
    erreur_passagere,
    modele,
)

from .etat import EtatQuestionnaire
from .limites import MAX_APPELS_ENQUETE, MAX_ESSAIS_REDACTION
from .prompts import (
    DEMANDE_CONCLUSIONS,
    DEMANDE_REDACTION,
    demande_correction,
    message_initial,
    prompt_enquete,
    prompt_redaction,
)
from .schemas import QuestionsGenerees
from .validation import valider_questions

# Plafond de sortie d'un appel : raisonnement du modèle + texte ou JSON produit
MAX_TOKENS = 8192
# L'enquête demande du jugement (quelles pistes, quoi vérifier) ; la rédaction recopie.
EFFORT_ENQUETE = "medium"
EFFORT_REDACTION = "low"


@wrap_model_call
def conclusions_au_dernier_appel(request, handler):
    """
    Au dernier appel autorisé, retire les tools et demande les conclusions : l'agent finit toujours
    par un message de conclusions, au lieu d'être coupé au milieu de son enquête.
    """
    appels_faits = sum(isinstance(message, AIMessage) for message in request.messages)
    if appels_faits >= MAX_APPELS_ENQUETE - 1:
        request = request.override(tools=[], messages=[*request.messages, HumanMessage(DEMANDE_CONCLUSIONS)])
    return handler(request)


@lru_cache
def _llm_redaction():
    return avec_nouveaux_essais(modele(EFFORT_REDACTION, MAX_TOKENS).with_structured_output(
        QuestionsGenerees,
        method="json_schema",  # Structured Outputs
        strict=True,           # sortie forcément conforme au schéma
        include_raw=True,      # pour récupérer les tokens consommés
    ))


def _secteur(etat: EtatQuestionnaire) -> str:
    return etat["contexte"].get("secteur") or "inconnu"


# 1. Enquête : l'agent lit le contexte, cherche dans les documents, calcule et conclut en texte
def enquete(etat: EtatQuestionnaire, outils: list[BaseTool]) -> dict:
    agent = create_agent(
        modele(EFFORT_ENQUETE, MAX_TOKENS),
        outils,
        system_prompt=prompt_enquete(_secteur(etat)),
        middleware=[
            conclusions_au_dernier_appel,
            ModelRetryMiddleware(max_retries=MAX_NOUVEAUX_ESSAIS, retry_on=erreur_passagere, on_failure="error",
                                 initial_delay=ATTENTE_INITIALE, backoff_factor=2, max_delay=ATTENTE_MAX),
        ],
    )
    initial = HumanMessage(message_initial(etat["contexte"], etat["questions_precedentes"]))
    try:
        resultat = agent.invoke({"messages": [initial]})
    except Exception as e:  # réseau, quota, appel de tool toujours rejeté...
        return {"erreurs": etat["erreurs"] + [f"Enquête, appel LLM : {type(e).__name__}: {e}"], "statut": "erreur"}

    messages = resultat["messages"]
    reponses = [m for m in messages if isinstance(m, AIMessage)]
    usages = [m.usage_metadata or {} for m in reponses]
    maj = {
        "messages": messages,
        "appels_tools": [{"tool": appel["name"], "arguments": appel["args"]} for m in reponses for appel in m.tool_calls],
        "tokens_entree": etat["tokens_entree"] + sum(u.get("input_tokens", 0) for u in usages),
        "tokens_sortie": etat["tokens_sortie"] + sum(u.get("output_tokens", 0) for u in usages),
    }
    if not reponses or reponses[-1].tool_calls or not reponses[-1].text.strip():
        return maj | {"erreurs": etat["erreurs"] + ["Enquête terminée sans message de conclusions."], "statut": "erreur"}
    return maj


# 2. Rédaction : met les conclusions de l'enquête au format strict, sans tools
def redaction(etat: EtatQuestionnaire) -> dict:
    messages = [SystemMessage(prompt_redaction()), *etat["messages"], HumanMessage(DEMANDE_REDACTION)]
    # Nouvel essai : seules les erreurs sont renvoyées, pas la réponse précédente (elles citent déjà
    # les questions fautives).
    if etat["erreurs_a_corriger"]:
        messages.append(HumanMessage(demande_correction(etat["erreurs_a_corriger"])))

    maj = {"essais_redaction": etat["essais_redaction"] + 1, "sortie_brute": None}
    try:
        reponse = _llm_redaction().invoke(messages)
    except Exception as e:  # réseau, quota dépassé...
        return maj | {"erreurs": etat["erreurs"] + [f"Rédaction, appel LLM : {type(e).__name__}: {e}"]}

    usage = getattr(reponse["raw"], "usage_metadata", None) or {}
    maj |= {"tokens_entree": etat["tokens_entree"] + usage.get("input_tokens", 0),
            "tokens_sortie": etat["tokens_sortie"] + usage.get("output_tokens", 0)}
    if reponse["parsing_error"] is not None:
        return maj | {"erreurs": etat["erreurs"] + [f"Rédaction, JSON illisible : {reponse['parsing_error']}"]}
    return maj | {"sortie_brute": reponse["parsed"].model_dump()}


# 3. Validation : schéma puis règles vérifiées par le code
def validation(etat: EtatQuestionnaire) -> dict:
    if etat["sortie_brute"] is None:  # appel ou JSON en échec : erreur déjà notée par la rédaction
        return {"erreurs_a_corriger": []}
    try:
        sortie = QuestionsGenerees.model_validate(etat["sortie_brute"]).model_dump()
    except ValidationError as e:
        err = [f"Schéma : {'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors()]
        return {"erreurs_a_corriger": err, "erreurs": etat["erreurs"] + err}

    contexte = etat["contexte"]
    documents_audit = {d["document_id"] for d in contexte.get("documents", [])}
    documents_audit |= set(contexte.get("documents_sans_extraction", []))
    deja_posees = [q["question"] for tour in etat["questions_precedentes"] for q in tour["questions"]]

    resultat, err = valider_questions(sortie, documents_audit, deja_posees, contexte.get("entrees_a_demander"))
    if err:
        return {"erreurs_a_corriger": err, "erreurs": etat["erreurs"] + err}
    return {"erreurs_a_corriger": [], "resultat": resultat, "statut": "ok"}


# 4. Échec : enquête sans conclusions, ou rédaction toujours invalide
def echec(etat: EtatQuestionnaire) -> dict:
    return {"statut": "erreur"}


# Fonctions de routage
def apres_enquete(etat: EtatQuestionnaire) -> str:
    return "echec" if etat["statut"] == "erreur" else "redaction"


def apres_validation(etat: EtatQuestionnaire) -> str:
    if etat["statut"] == "ok":
        return "fin"
    if etat["essais_redaction"] < MAX_ESSAIS_REDACTION:
        return "redaction"
    return "echec"
