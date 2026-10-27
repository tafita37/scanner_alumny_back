from langgraph.graph import END, START, StateGraph

from . import noeuds
from .etat import EtatExtraction
from .schemas import SECTEURS


def construire_graphe():
    g = StateGraph(EtatExtraction)

    g.add_node("classification", noeuds.classification)
    g.add_node("extraction", noeuds.extraction)
    g.add_node("validation", noeuds.validation)
    g.add_node("calcul", noeuds.calcul)
    g.add_node("a_verifier", noeuds.a_verifier)

    g.add_edge(START, "classification")
    g.add_conditional_edges("classification", noeuds.apres_classification,
                            {"extraction": "extraction", "a_verifier": "a_verifier"})
    g.add_edge("extraction", "validation")
    g.add_conditional_edges("validation", noeuds.apres_validation,
                            {"calcul": "calcul", "extraction": "extraction", "a_verifier": "a_verifier"})
    g.add_edge("calcul", END)
    g.add_edge("a_verifier", END)

    return g.compile()


graphe = construire_graphe()


def extraire(texte_anonymise: str, secteur: str) -> dict:
    secteur = secteur.upper()
    if secteur not in SECTEURS:
        raise ValueError(f"Secteur inconnu : {secteur}. Attendu : {list(SECTEURS)}.")

    return graphe.invoke({
        "texte": texte_anonymise,
        "secteur": secteur,
        "type_extraction": None,
        "modele": noeuds.MODELE,
        "tentatives": 0,
        "extraction_brute": None,
        "erreurs_derniere_tentative": [],
        "erreurs": [],
        "extraction": None,
        "variables": None,
        "tokens_entree": 0,
        "tokens_sortie": 0,
        "statut": "en_cours",
    })
