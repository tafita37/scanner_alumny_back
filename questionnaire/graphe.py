"""
Graphe d'un tour du questionnaire adaptatif :

    enquete ──► redaction ──► validation ──► fin
       │            ▲              │
       ▼            └── 1 essai ───┘   (erreurs de validation renvoyées au LLM)
     echec  ◄──────────────────────┘   (enquête sans conclusions, ou rédaction toujours invalide)

Seule l'enquête est un agent (create_agent) : elle choisit elle-même ses tools (recherche et lecture
dans les documents, calculs) selon ce qu'elle découvre. La rédaction et la validation sont des
étapes fixes, comme dans l'extraction.

Ce module ne connaît ni Django ni la base : le contexte de l'audit, les questions précédentes (déjà
masqués) et les tools (liés à l'audit) sont fournis par l'appelant.
"""
from functools import partial

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from . import noeuds
from .etat import EtatQuestionnaire


def construire_graphe(outils: list[BaseTool]):
    """Graphe d'un tour ; construit à chaque appel, car les tools sont liés à un audit."""
    g = StateGraph(EtatQuestionnaire)

    g.add_node("enquete", partial(noeuds.enquete, outils=outils))
    g.add_node("redaction", noeuds.redaction)
    g.add_node("validation", noeuds.validation)
    g.add_node("echec", noeuds.echec)

    g.add_edge(START, "enquete")
    g.add_conditional_edges("enquete", noeuds.apres_enquete, {"redaction": "redaction", "echec": "echec"})
    g.add_edge("redaction", "validation")
    g.add_conditional_edges("validation", noeuds.apres_validation,
                            {"fin": END, "redaction": "redaction", "echec": "echec"})
    g.add_edge("echec", END)

    return g.compile()


def generer_questions(contexte: dict, questions_precedentes: list[dict], outils: list[BaseTool]) -> dict:
    """
    Génère les questions d'un tour. Renvoie l'état final : `statut` (ok / erreur), `resultat`
    ({analyse, questions} si ok ; questions vides : questionnaire terminé), `erreurs`, `appels_tools`,
    `tokens_entree`, `tokens_sortie`.
    `contexte` : read_audit_context ; `questions_precedentes` : read_previous_questions ; les deux
    avec la même correspondance de jetons que les tools, qui sert ensuite à dé-anonymiser le résultat.
    """
    return construire_graphe(outils).invoke({
        "contexte": contexte,
        "questions_precedentes": questions_precedentes,
        "messages": [],
        "appels_tools": [],
        "essais_redaction": 0,
        "sortie_brute": None,
        "erreurs_a_corriger": [],
        "erreurs": [],
        "resultat": None,
        "tokens_entree": 0,
        "tokens_sortie": 0,
        "statut": "en_cours",
    })
