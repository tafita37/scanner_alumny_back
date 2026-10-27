"""Indicateurs d'un audit : agrégation des extractions de tous ses documents. Le code calcule.

Seuls les indicateurs dont la formule est définie sont calculés. CHr, Emo, coût du temps, TRS...
attendent le questionnaire et la définition des termes manquants.
"""

from .calculs import CALCULS_PAR_TYPE
from .schemas import SCHEMAS_PAR_TYPE, SECTEURS, ExtractionIndustrie

TYPES_COMPTES_ANNUELS = ("comptes_annuels", "liasse_fiscale")


def _moyenne(valeurs) -> float | None:
    valeurs = [v for v in valeurs if v is not None]
    return round(sum(valeurs) / len(valeurs), 2) if valeurs else None


def _cle(texte: str | None) -> str | None:
    """Clé de rapprochement d'un produit : casse et espaces ignorés."""
    return " ".join(texte.lower().split()) if texte else None


# --------------------------------------------------------------------------- #
# Documents commerciaux
# --------------------------------------------------------------------------- #

def _document_fusionne(secteur: str, extractions: list[dict]):
    """Les lignes de tous les documents commerciaux réunies dans un seul document du secteur."""
    if secteur == "INDUSTRIE":
        contenu = {"type_document": "bon_de_commande",
                   "lignes_commande": [l for e in extractions for l in e["lignes_commande"]],
                   "fiches_prix_revient": [f for e in extractions for f in e["fiches_prix_revient"]]}
    else:
        contenu = {"type_document": "devis", "lignes": [l for e in extractions for l in e["lignes"]]}
    pied = {"total_ht": None, "total_ttc": None, "acompte_pourcentage": None, "delai_reglement_jours": None}
    return SCHEMAS_PAR_TYPE[secteur].model_validate(contenu | pied)


def _marges_croisees(e: ExtractionIndustrie) -> list[dict]:
    """
    Marge sur coûts variables par produit : prix du bon de commande − coûts variables de la fiche
    de prix de revient (matière + main-d'œuvre + machine), ramenés à l'unité.
    Le produit de la fiche est rapproché de la référence de la ligne, sinon de son libellé.
    """
    fiches = {_cle(f.produit): f for f in e.fiches_prix_revient if _cle(f.produit)}
    marges = []
    for l in e.lignes_commande:
        f = fiches.get(_cle(l.reference)) or fiches.get(_cle(l.libelle))
        if f is None or l.prix_unitaire_ht is None:
            continue
        couts = [c for c in (f.cout_matiere, f.cout_main_oeuvre, f.cout_machine) if c is not None]
        if not couts:
            continue
        cout_unitaire = sum(couts) / (f.quantite_reference or 1)
        marge = l.prix_unitaire_ht - cout_unitaire
        marges.append({
            "produit": l.libelle,
            "reference": l.reference,
            "prix_unitaire_ht": l.prix_unitaire_ht,
            "couts_variables_unitaires": round(cout_unitaire, 2),
            "marge_unitaire": round(marge, 2),
            "taux_marge": round(100 * marge / l.prix_unitaire_ht, 2) if l.prix_unitaire_ht else None,  # en %
            "quantite": l.quantite,
            "marge_totale": round(marge * l.quantite, 2) if l.quantite is not None else None,
        })
    return marges


def _commercial(secteur: str, extractions: list[dict]) -> dict | None:
    if secteur not in SECTEURS or not extractions:
        return None
    fusion = _document_fusionne(secteur, extractions)
    variables = CALCULS_PAR_TYPE[secteur](fusion)
    # Moyenne simple sur les documents qui indiquent la condition
    variables["conditions_de_paiement"] = {
        "acompte_pourcentage_moyen": _moyenne(e["acompte_pourcentage"] for e in extractions),
        "delai_reglement_jours_moyen": _moyenne(e["delai_reglement_jours"] for e in extractions),
    }
    if secteur == "INDUSTRIE":
        variables["marges_sur_couts_variables"] = _marges_croisees(fusion)
    return variables


# --------------------------------------------------------------------------- #
# Comptes annuels et données de l'API
# --------------------------------------------------------------------------- #

def _comptes_retenus(comptes: list[dict], annee: int | None) -> dict | None:
    """Comptes annuels clos l'année de l'audit, sinon les plus récents (variables déjà calculées)."""
    if not comptes:
        return None
    meme_annee = [c for c in comptes if (c["date_cloture"] or "")[:4] == str(annee)]
    if meme_annee:
        return meme_annee[-1]
    return max(comptes, key=lambda c: c["date_cloture"] or "")


def _valeur(comptes: dict | None, cle: str, valeur_api) -> dict:
    """Valeur des comptes annuels si elle existe, sinon celle publiée (API)."""
    if comptes is not None and comptes.get(cle) is not None:
        return {"valeur": comptes[cle], "source": "comptes_annuels"}
    if valeur_api is not None:
        return {"valeur": valeur_api, "source": "api"}
    return {"valeur": None, "source": None}


def calculer_indicateurs(secteur: str, extractions: list[tuple[dict, dict]], api: dict) -> dict:
    """
    secteur : "BTP", "SERVICES" ou "INDUSTRIE".
    extractions : (extraction, variables) de chaque document retenu, du plus ancien au plus récent.
    api : données publiées de l'audit (chiffre_affaires, resultat_net, effectif, annee).
    """
    commerciales = [x for x, _ in extractions if x["type_document"] not in TYPES_COMPTES_ANNUELS]
    comptes = [v for x, v in extractions if x["type_document"] in TYPES_COMPTES_ANNUELS]
    retenus = _comptes_retenus(comptes, api["annee"])

    return {
        "chiffre_affaires": _valeur(retenus, "chiffre_affaires", api["chiffre_affaires"]),
        "resultat_net": _valeur(retenus, "resultat_net", api["resultat_net"]),
        "effectif": _valeur(retenus, "effectif_moyen", api["effectif"]),
        "documents_commerciaux": _commercial(secteur, commerciales),
        "comptes_annuels": retenus,
    }
