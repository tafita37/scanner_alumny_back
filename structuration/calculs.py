"""Calcul des variables à partir de l'extraction. Le LLM lit, le code calcule."""

import re
from datetime import date

from .schemas import DocumentCommercial, ExtractionBTP, ExtractionComptesAnnuels, ExtractionIndustrie, ExtractionServices

_UNITE_HEURE = re.compile(r"^\s*(h|hr|hrs|heures?)\.?\s*$", re.IGNORECASE)


def _est_en_heures(unite: str | None) -> bool:
    return bool(unite and _UNITE_HEURE.match(unite))


def _arrondi(x: float | None) -> float | None:
    return round(x, 2) if x is not None else None


def _division(a: float, b: float) -> float | None:
    return round(a / b, 2) if b else None


def _somme(valeurs) -> float | None:
    """Somme des valeurs renseignées, None s'il n'y en a aucune."""
    valeurs = [v for v in valeurs if v is not None]
    return _arrondi(sum(valeurs)) if valeurs else None


def _jours_entre(debut: str | None, fin: str | None) -> int | None:
    """Nombre de jours calendaires entre deux dates AAAA-MM-JJ (déjà contrôlées), sinon None."""
    if not debut or not fin:
        return None
    return (date.fromisoformat(fin) - date.fromisoformat(debut)).days


def _chiffres(identifiant: str | None) -> str:
    return re.sub(r"\D", "", identifiant or "")


# --------------------------------------------------------------------------- #
# Documents commerciaux : variables communes
# --------------------------------------------------------------------------- #

def delai_reglement(e: DocumentCommercial) -> int | None:
    """Délai écrit dans le document, sinon écart entre la date du document et l'échéance."""
    if e.conditions.delai_reglement_jours is not None:
        return e.conditions.delai_reglement_jours
    return _jours_entre(e.en_tete.date_document, e.en_tete.date_echeance)


def sens_document(e: DocumentCommercial, siren: str | None) -> str | None:
    """
    "vente" si l'entreprise auditée émet le document, "achat" si elle le reçoit, None si son SIREN
    n'apparaît ni chez l'émetteur ni chez le destinataire (un SIRET commence par le SIREN).
    """
    siren = _chiffres(siren)
    if len(siren) != 9:
        return None
    if _chiffres(e.emetteur.siret).startswith(siren):
        return "vente"
    if _chiffres(e.destinataire.siret).startswith(siren):
        return "achat"
    return None


def _variables_document(e: DocumentCommercial) -> dict:
    """Variables communes : seules celles que le code calcule (le reste se lit dans l'extraction)."""
    return {"delai_reglement_jours": delai_reglement(e)}


# --------------------------------------------------------------------------- #
# BTP
# --------------------------------------------------------------------------- #

def variables_btp(e: ExtractionBTP) -> dict:
    lignes_heures = [l for l in e.lignes
                     if l.nature == "main_oeuvre" and _est_en_heures(l.unite)
                     and l.quantite and l.total_ht is not None]
    heures = sum(l.quantite for l in lignes_heures)
    montant_heures = sum(l.total_ht for l in lignes_heures)

    situation = e.situation
    montant_situation = None
    if situation is not None and None not in (situation.montant_cumule_ht, situation.montant_deja_facture_ht):
        montant_situation = _arrondi(situation.montant_cumule_ht - situation.montant_deja_facture_ht)

    return _variables_document(e) | {
        "taux_horaire_main_oeuvre": _division(montant_heures, heures),
        "heures_main_oeuvre": heures or None,
        "montant_total_main_oeuvre": _somme(l.total_ht for l in e.lignes if l.nature == "main_oeuvre"),
        "montant_total_fournitures": _somme(l.total_ht for l in e.lignes if l.nature == "fourniture"),
        "marge_brute_apparente": None,  # méthode de calcul à définir avec Ny Aina
        "avancement_pourcentage": situation.avancement_pourcentage if situation else None,
        # Travaux facturés par cette situation : cumul - déjà facturé
        "montant_situation_ht": montant_situation,
        # Durée écrite en texte ("3 semaines") : conversion en jours non faite (jours ouvrés ou calendaires ?)
        "duree_travaux_jours": None,
    }


# --------------------------------------------------------------------------- #
# SERVICES
# --------------------------------------------------------------------------- #

def _tjm_par_profil(lignes) -> dict | None:
    """TJM vendu en régie par profil : montant des lignes au jour du profil / nombre de jours."""
    montants, jours = {}, {}
    for l in lignes:
        montants[l.profil] = montants.get(l.profil, 0) + l.total_ht
        jours[l.profil] = jours.get(l.profil, 0) + l.quantite
    tjm = {profil: _division(montants[profil], jours[profil]) for profil in montants}
    return tjm or None


def variables_services(e: ExtractionServices) -> dict:
    regie_jour = [l for l in e.lignes if l.mode_facturation == "regie_jour" and l.quantite and l.total_ht is not None]
    regie_heure = [l for l in e.lignes if l.mode_facturation == "regie_heure" and l.quantite and l.total_ht is not None]
    forfaits = [l for l in e.lignes if l.mode_facturation == "forfait" and l.total_ht is not None]
    forfaits_chiffres = [l for l in forfaits if l.jours_estimes]
    frais = [l for l in e.lignes if l.mode_facturation == "frais"]

    jours_regie = sum(l.quantite for l in regie_jour)
    jours_forfaits = sum(l.jours_estimes for l in forfaits_chiffres)

    return _variables_document(e) | {
        # TJM vendu en régie : montant des lignes au jour / nombre de jours
        "tjm_vendu_regie": _division(sum(l.total_ht for l in regie_jour), jours_regie),
        "tjm_par_profil": _tjm_par_profil([l for l in regie_jour if l.profil]),
        # Taux horaire vendu en régie (pas converti en jours : nb d'heures par jour inconnu)
        "taux_horaire_vendu_regie": _division(sum(l.total_ht for l in regie_heure),
                                              sum(l.quantite for l in regie_heure)),
        # TJM implicite des forfaits : montant / jours estimés (seulement si les jours sont indiqués)
        "tjm_implicite_forfaits": _division(sum(l.total_ht for l in forfaits_chiffres), jours_forfaits),
        "jours_vendus": (jours_regie + jours_forfaits) or None,
        "montant_total_forfaits": _somme(l.total_ht for l in forfaits),
        "montant_total_frais": _somme(l.total_ht for l in frais),
        "montant_frais_au_reel": _somme(l.total_ht for l in frais if l.au_reel),
        "nb_echeances": len(e.echeancier) or None,
        "nb_participants": e.nb_participants,
        # Base à définir : total HT du document ou seules les lignes de formation (hors frais) ?
        "prix_par_participant": None,
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
    marge_revient = None
    if f.cout_revient_total is not None and f.prix_vente is not None:
        marge_revient = round(f.prix_vente - f.cout_revient_total, 2)
    return {
        "produit": f.produit,
        "quantite_reference": f.quantite_reference,
        "couts_variables": _arrondi(couts_variables),
        "prix_vente": f.prix_vente,
        "marge_sur_couts_variables": marge,
        "taux_marge_sur_couts_variables": taux,  # en %
        "cout_revient_unitaire": (_division(f.cout_revient_total, f.quantite_reference or 1)
                                  if f.cout_revient_total is not None else None),
        "marge_sur_cout_revient": marge_revient,
        # Coefficient réellement appliqué : prix de vente / coût de revient total
        "coefficient_applique": (_division(f.prix_vente, f.cout_revient_total)
                                 if None not in (f.prix_vente, f.cout_revient_total) else None),
        # Prise en compte du taux de rebut et des frais généraux (base de calcul) : à définir avec Ny Aina
        "cout_revient_corrige": None,
    }


def variables_industrie(e: ExtractionIndustrie) -> dict:
    return _variables_document(e) | {
        "marges_par_produit": [_marge_fiche(f) for f in e.fiches_prix_revient],
    }


# --------------------------------------------------------------------------- #
# COMPTES ANNUELS
# --------------------------------------------------------------------------- #

def variables_comptes_annuels(e: ExtractionComptesAnnuels, siren: str | None = None) -> dict:
    """`siren` : celui de l'entreprise auditée, enregistré en base (il n'est pas demandé au LLM)."""
    facteur = 1000 if e.unite == "milliers_euros" else 1
    ident, actif, passif, cr, annexe = e.identification, e.actif, e.passif, e.compte_resultat, e.annexe

    def en_euros(x: float | None) -> float | None:
        return _arrondi(x * facteur) if x is not None else None

    personnel = [c for c in (cr.salaires_traitements, cr.charges_sociales) if c is not None]
    masse_salariale = en_euros(sum(personnel)) if personnel else None

    amortissements_installations = None
    if None not in (actif.installations_techniques_brut, actif.installations_techniques_net):
        amortissements_installations = en_euros(actif.installations_techniques_brut
                                                - actif.installations_techniques_net)

    return {
        "raison_sociale": ident.raison_sociale,
        "siren": siren,
        "date_cloture": ident.date_cloture,
        "duree_exercice_mois": ident.duree_exercice_mois,
        "compte_resultat_present": e.compte_resultat_present,
        # Communes
        "chiffre_affaires": en_euros(cr.chiffre_affaires),
        "resultat_exploitation": en_euros(cr.resultat_exploitation),
        "resultat_financier": en_euros(cr.resultat_financier),
        "resultat_exceptionnel": en_euros(cr.resultat_exceptionnel),
        "resultat_net": en_euros(cr.resultat_net),
        "creances_clients": en_euros(actif.creances_clients),
        "dettes_fournisseurs": en_euros(passif.dettes_fournisseurs),
        "disponibilites": en_euros(actif.disponibilites),
        "total_capitaux_propres": en_euros(passif.total_capitaux_propres),
        "emprunts_dettes_financieres": en_euros(passif.emprunts_dettes_financieres),
        "interets_charges_assimilees": en_euros(cr.interets_charges_assimilees),
        "effectif_moyen": annexe.effectif_moyen,
        "repartition_effectif": [r.model_dump() for r in annexe.repartition_effectif],
        "excedent_brut_exploitation": None,  # formule (postes retenus) à valider avec Ny Aina
        "besoin_fonds_roulement": None,      # composition à valider avec Ny Aina
        # Créances TTC rapportées à un CA HT : convention à définir avant de calculer
        "delai_moyen_clients_jours": None,
        "delai_moyen_fournisseurs_jours": None,
        # BTP / Services
        "masse_salariale_annuelle": masse_salariale,
        "masse_salariale_mensuelle": (_division(masse_salariale, ident.duree_exercice_mois)
                                      if masse_salariale is not None else None),
        "charges_fixes_structure": None,  # composition à définir avec Ny Aina
        "autres_achats_charges_externes": en_euros(cr.autres_achats_charges_externes),
        "impots_taxes": en_euros(cr.impots_taxes),
        # Industrie
        "achats_marchandises": en_euros(cr.achats_marchandises),
        "variation_stock_marchandises": en_euros(cr.variation_stock_marchandises),
        "achats_matieres_premieres": en_euros(cr.achats_matieres_premieres),
        "variation_stock_matieres": en_euros(cr.variation_stock_matieres),
        "stocks": en_euros(actif.stocks),
        "installations_techniques_brut": en_euros(actif.installations_techniques_brut),
        "installations_techniques_net": en_euros(actif.installations_techniques_net),
        "amortissements_cumules_installations": amortissements_installations,
        "dotations_amortissements": en_euros(cr.dotations_amortissements),
        "credit_bail_redevances_exercice": en_euros(annexe.credit_bail_redevances_exercice),
        "credit_bail_valeur_origine": en_euros(annexe.credit_bail_valeur_origine),
    }


CALCULS_PAR_TYPE = {
    "BTP": variables_btp,
    "SERVICES": variables_services,
    "INDUSTRIE": variables_industrie,
    "COMPTES_ANNUELS": variables_comptes_annuels,
}
