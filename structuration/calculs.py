"""Calcul des variables à partir de l'extraction. Le LLM lit, le code calcule."""

import re

from .schemas import ExtractionBTP, ExtractionComptesAnnuels, ExtractionIndustrie, ExtractionServices

_UNITE_HEURE = re.compile(r"^\s*(h|hr|hrs|heures?)\.?\s*$", re.IGNORECASE)


def _est_en_heures(unite: str | None) -> bool:
    return bool(unite and _UNITE_HEURE.match(unite))


def _arrondi(x: float | None) -> float | None:
    return round(x, 2) if x is not None else None


def _division(a: float, b: float) -> float | None:
    return round(a / b, 2) if b else None


def _conditions_paiement(e) -> dict:
    return {"acompte_pourcentage": e.acompte_pourcentage, "delai_reglement_jours": e.delai_reglement_jours}


# --------------------------------------------------------------------------- #
# BTP
# --------------------------------------------------------------------------- #

def variables_btp(e: ExtractionBTP) -> dict:
    lignes_heures = [l for l in e.lignes
                     if l.nature == "main_oeuvre" and _est_en_heures(l.unite)
                     and l.quantite and l.total_ht is not None]
    heures = sum(l.quantite for l in lignes_heures)
    montant_heures = sum(l.total_ht for l in lignes_heures)

    fournitures = [l.total_ht for l in e.lignes if l.nature == "fourniture" and l.total_ht is not None]

    return {
        "taux_horaire_main_oeuvre": _division(montant_heures, heures),
        "heures_main_oeuvre": heures or None,
        "montant_total_fournitures": _arrondi(sum(fournitures)) if fournitures else None,
        "marge_brute_apparente": None,  # méthode de calcul à définir avec Ny Aina
        "conditions_de_paiement": _conditions_paiement(e),
        "libelles_prestations": [l.libelle for l in e.lignes],
    }


# --------------------------------------------------------------------------- #
# SERVICES
# --------------------------------------------------------------------------- #

def variables_services(e: ExtractionServices) -> dict:
    regie_jour = [l for l in e.lignes if l.mode_facturation == "regie_jour" and l.quantite and l.total_ht is not None]
    regie_heure = [l for l in e.lignes if l.mode_facturation == "regie_heure" and l.quantite and l.total_ht is not None]
    forfaits = [l for l in e.lignes if l.mode_facturation == "forfait" and l.total_ht is not None]
    forfaits_chiffres = [l for l in forfaits if l.jours_estimes]

    jours_regie = sum(l.quantite for l in regie_jour)
    jours_forfaits = sum(l.jours_estimes for l in forfaits_chiffres)

    return {
        # TJM vendu en régie : montant des lignes au jour / nombre de jours
        "tjm_vendu_regie": _division(sum(l.total_ht for l in regie_jour), jours_regie),
        # Taux horaire vendu en régie (pas converti en jours : nb d'heures par jour inconnu)
        "taux_horaire_vendu_regie": _division(sum(l.total_ht for l in regie_heure),
                                              sum(l.quantite for l in regie_heure)),
        # TJM implicite des forfaits : montant / jours estimés (seulement si les jours sont indiqués)
        "tjm_implicite_forfaits": _division(sum(l.total_ht for l in forfaits_chiffres), jours_forfaits),
        "jours_vendus": (jours_regie + jours_forfaits) or None,
        "montant_total_forfaits": _arrondi(sum(l.total_ht for l in forfaits)) if forfaits else None,
        "conditions_de_paiement": _conditions_paiement(e),
        "libelles_prestations": [l.libelle for l in e.lignes],
    }


# --------------------------------------------------------------------------- #
# INDUSTRIE
# --------------------------------------------------------------------------- #

def _marge_fiche(f) -> dict:
    couts = [f.cout_matiere, f.cout_main_oeuvre, f.cout_machine]
    couts_variables = sum(c for c in couts if c is not None) if any(c is not None for c in couts) else None
    marge = None
    taux = None
    if couts_variables is not None and f.prix_vente is not None:
        marge = round(f.prix_vente - couts_variables, 2)
        taux = round(100 * marge / f.prix_vente, 2) if f.prix_vente else None
    return {
        "produit": f.produit,
        "quantite_reference": f.quantite_reference,
        "couts_variables": _arrondi(couts_variables),
        "prix_vente": f.prix_vente,
        "marge_sur_couts_variables": marge,
        "taux_marge_sur_couts_variables": taux,  # en %
    }


def variables_industrie(e: ExtractionIndustrie) -> dict:
    lignes = [l for l in e.lignes_commande if l.total_ht is not None]
    return {
        "chiffre_affaires_commande": _arrondi(sum(l.total_ht for l in lignes)) if lignes else None,
        "produits_commandes": [l.libelle for l in e.lignes_commande],
        # Prix et quantité par produit : croisés plus tard avec la fiche de prix de revient (par référence)
        "lignes_commande": [
            {"produit": l.libelle, "reference": l.reference, "quantite": l.quantite,
             "unite": l.unite, "prix_unitaire_ht": l.prix_unitaire_ht}
            for l in e.lignes_commande
        ],
        "marges_par_produit": [_marge_fiche(f) for f in e.fiches_prix_revient],
        "conditions_de_paiement": _conditions_paiement(e),
    }


# --------------------------------------------------------------------------- #
# COMPTES ANNUELS
# --------------------------------------------------------------------------- #

def variables_comptes_annuels(e: ExtractionComptesAnnuels) -> dict:
    facteur = 1000 if e.unite == "milliers_euros" else 1

    def en_euros(x: float | None) -> float | None:
        return _arrondi(x * facteur) if x is not None else None

    personnel = [c for c in (e.salaires_traitements, e.charges_sociales) if c is not None]
    masse_salariale = en_euros(sum(personnel)) if personnel else None

    return {
        "date_cloture": e.date_cloture,
        "duree_exercice_mois": e.duree_exercice_mois,
        "compte_resultat_present": e.compte_resultat_present,
        # Communes
        "chiffre_affaires": en_euros(e.chiffre_affaires),
        "resultat_net": en_euros(e.resultat_net),
        "creances_clients": en_euros(e.creances_clients),
        "dettes_fournisseurs": en_euros(e.dettes_fournisseurs),
        "effectif_moyen": e.effectif_moyen,
        # BTP / Services
        "masse_salariale_annuelle": masse_salariale,
        "masse_salariale_mensuelle": (_division(masse_salariale, e.duree_exercice_mois)
                                      if masse_salariale is not None else None),
        "charges_fixes_structure": None,  # composition à définir avec Ny Aina
        "autres_achats_charges_externes": en_euros(e.autres_achats_charges_externes),
        "impots_taxes": en_euros(e.impots_taxes),
        # Industrie
        "achats_matieres_premieres": en_euros(e.achats_matieres_premieres),
        "variation_stock_matieres": en_euros(e.variation_stock_matieres),
        "stocks": en_euros(e.stocks),
        "installations_techniques_brut": en_euros(e.installations_techniques_brut),
        "installations_techniques_net": en_euros(e.installations_techniques_net),
        "dotations_amortissements": en_euros(e.dotations_amortissements),
    }


CALCULS_PAR_TYPE = {
    "BTP": variables_btp,
    "SERVICES": variables_services,
    "INDUSTRIE": variables_industrie,
    "COMPTES_ANNUELS": variables_comptes_annuels,
}