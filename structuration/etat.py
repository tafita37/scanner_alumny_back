from typing import TypedDict


class EtatExtraction(TypedDict):
    texte: str                            # texte DÉJÀ anonymisé, envoyé au LLM
    secteur: str                          # "BTP", "SERVICES" ou "INDUSTRIE"
    type_extraction: str | None           # fixé par la classification : le secteur ou "COMPTES_ANNUELS"
    modele: str
    tentatives: int
    extraction_brute: dict | None         # dernière réponse du LLM (renvoyée au LLM en cas d'erreur)
    erreurs_derniere_tentative: list[str] # sert à décider : calcul, nouvel essai ou à vérifier
    erreurs: list[str]                    # historique complet, enregistré en base
    extraction: dict | None               # réponse sans erreur
    variables: dict | None                # variables calculées
    tokens_entree: int
    tokens_sortie: int
    statut: str                           # en_cours / ok / a_verifier