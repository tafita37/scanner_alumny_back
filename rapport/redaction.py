"""
Rédaction des textes du rapport d'audit par le LLM : un appel en sortie structurée (pas d'agent :
toutes les données sont fournies), validé par le code, avec un nouvel essai si la validation trouve
des erreurs (la réponse précédente et ses erreurs sont renvoyées au LLM).

Ce module ne connaît ni Django ni la base : les données de l'audit (déjà masquées) sont fournies
par l'appelant, qui dé-anonymise le résultat.
Modèle et nouveaux essais (limite par minute atteinte...) : voir `fournisseur_llm`.
"""
import json
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from fournisseur_llm import avec_nouveaux_essais, modele

from .prompts import demande_correction, message_donnees, prompt_redaction
from .schemas import RapportRedige
from .validation import valider_rapport

# Raisonnement + textes du rapport (~3 000 tokens de texte)
MAX_TOKENS = 12000
# Rédiger un rapport client demande du jugement (quels leviers, quel ton) : effort moyen.
EFFORT_REDACTION = "medium"
# Le premier essai, plus un nouvel essai si la validation trouve des erreurs.
MAX_ESSAIS = 2


@lru_cache
def _llm():
    return avec_nouveaux_essais(modele(EFFORT_REDACTION, MAX_TOKENS).with_structured_output(
        RapportRedige,
        method="json_schema",  # Structured Outputs
        strict=True,           # sortie forcément conforme au schéma
        include_raw=True,      # pour récupérer les tokens consommés
    ))


def rediger_rapport(donnees: dict) -> dict:
    """
    Textes du rapport. Renvoie {statut (ok / erreur), resultat (RapportRedige validé si ok), erreurs,
    tokens_entree, tokens_sortie}.
    `donnees` : données de l'audit DÉJÀ masquées (entreprise, donnees_publiees, indicateurs_documents,
    cockpit, questionnaire) ; leurs nombres sont les seuls montants autorisés dans les textes.
    """
    cockpit = donnees["cockpit"]
    cles_indicateurs = [i["cle"] for i in cockpit["indicateurs"]]
    messages = [SystemMessage(prompt_redaction(cockpit["secteur"])), HumanMessage(message_donnees(donnees))]
    etat = {"statut": "erreur", "resultat": None, "erreurs": [], "tokens_entree": 0, "tokens_sortie": 0}

    for _ in range(MAX_ESSAIS):
        try:
            reponse = _llm().invoke(messages)
        except Exception as e:  # réseau, quota dépassé...
            etat["erreurs"].append(f"Rédaction, appel LLM : {type(e).__name__}: {e}")
            return etat

        usage = getattr(reponse["raw"], "usage_metadata", None) or {}
        etat["tokens_entree"] += usage.get("input_tokens", 0)
        etat["tokens_sortie"] += usage.get("output_tokens", 0)
        if reponse["parsing_error"] is not None:
            etat["erreurs"].append(f"Rédaction, JSON illisible : {reponse['parsing_error']}")
            continue
        try:
            sortie = RapportRedige.model_validate(reponse["parsed"].model_dump()).model_dump()
        except ValidationError as e:
            erreurs = [f"Schéma : {'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors()]
        else:
            resultat, erreurs = valider_rapport(sortie, cles_indicateurs, donnees)
            if not erreurs:
                return etat | {"statut": "ok", "resultat": resultat}
            messages += [AIMessage(json.dumps(sortie, ensure_ascii=False))]
        etat["erreurs"] += erreurs
        messages.append(HumanMessage(demande_correction(erreurs)))
    return etat
