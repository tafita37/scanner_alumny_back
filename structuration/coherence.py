"""Contrôles arithmétiques : le LLM a-t-il bien recopié les nombres ?"""

import re
from datetime import date

from .schemas import (
    DocumentCommercial,
    ExtractionBTP,
    ExtractionComptesAnnuels,
    ExtractionIndustrie,
    ExtractionServices,
    LigneChiffree,
    Partie,
)


def _proche(a: float, b: float) -> bool:
    """Tolérance : 1 % ou 5 centimes (arrondis du document)."""
    return abs(a - b) <= max(0.05, 0.01 * abs(b))


def _date(valeur: str | None) -> date | None:
    """Date AAAA-MM-JJ, ou None si absente ou mal écrite (signalé par _controle_format_date)."""
    try:
        return date.fromisoformat(valeur) if valeur else None
    except ValueError:
        return None


def _controle_format_date(valeur: str | None, nom: str) -> list[str]:
    if valeur is not None and _date(valeur) is None:
        return [f"{nom} = {valeur!r}, attendu au format AAAA-MM-JJ."]
    return []


def _controle_pourcentage(valeur: float | None, nom: str) -> list[str]:
    if valeur is not None and not 0 <= valeur <= 100:
        return [f"{nom} = {valeur}, attendu entre 0 et 100."]
    return []


def _controle_identifiant(valeur: str | None, nom: str, longueurs: tuple[int, ...]) -> list[str]:
    """SIRET / SIREN : espaces, points et tirets ignorés."""
    if valeur is None:
        return []
    chiffres = re.sub(r"[\s.\-]", "", valeur)
    if not chiffres.isdigit() or len(chiffres) not in longueurs:
        return [f"{nom} = {valeur!r}, attendu {' ou '.join(map(str, longueurs))} chiffres."]
    return []


# --------------------------------------------------------------------------- #
# Documents commerciaux : contrôles communs
# --------------------------------------------------------------------------- #

def _controle_lignes(lignes: list[LigneChiffree], nom: str) -> list[str]:
    """quantité × prix unitaire × (1 - remise) = total de la ligne."""
    erreurs = []
    for i, l in enumerate(lignes, start=1):
        if None not in (l.quantite, l.prix_unitaire_ht, l.total_ht):
            attendu = l.quantite * l.prix_unitaire_ht * (1 - (l.remise_pourcentage or 0) / 100)
            if not _proche(attendu, l.total_ht):
                erreurs.append(f"{nom} {i} ({l.libelle}) : quantité × prix unitaire (après remise) = "
                               f"{attendu:.2f}, mais total_ht = {l.total_ht:.2f}.")
        erreurs += _controle_pourcentage(l.remise_pourcentage, f"{nom} {i} : remise_pourcentage")
    return erreurs


def _controle_somme(lignes: list[LigneChiffree], e: DocumentCommercial) -> list[str]:
    """Somme des lignes = total HT du document (avant ou après la remise globale)."""
    totaux = [l.total_ht for l in lignes]
    total_ht = e.pied.total_ht
    if total_ht is None or not totaux or None in totaux:
        return []
    somme = sum(totaux)
    if _proche(somme, total_ht) or _proche(somme - (e.pied.remise_globale_ht or 0), total_ht):
        return []
    return [f"Somme des lignes = {somme:.2f}, mais total_ht du document = {total_ht:.2f}."]


def _controle_pied(e: DocumentCommercial) -> list[str]:
    p = e.pied
    erreurs = []
    if p.total_ht is not None and p.total_ttc is not None and p.total_ttc < p.total_ht:
        erreurs.append(f"total_ttc ({p.total_ttc:.2f}) est inférieur à total_ht ({p.total_ht:.2f}).")
    if None not in (p.total_ht, p.total_tva, p.total_ttc) and not _proche(p.total_ht + p.total_tva, p.total_ttc):
        erreurs.append(f"total_ht + total_tva = {p.total_ht + p.total_tva:.2f}, "
                       f"mais total_ttc = {p.total_ttc:.2f}.")

    for i, v in enumerate(p.ventilation_tva, start=1):
        if None not in (v.taux, v.base_ht, v.montant_tva) and not _proche(v.base_ht * v.taux / 100, v.montant_tva):
            erreurs.append(f"Ventilation TVA {i} : base_ht × taux = {v.base_ht * v.taux / 100:.2f}, "
                           f"mais montant_tva = {v.montant_tva:.2f}.")
    montants = [v.montant_tva for v in p.ventilation_tva]
    if p.total_tva is not None and montants and None not in montants and not _proche(sum(montants), p.total_tva):
        erreurs.append(f"Somme de la ventilation TVA = {sum(montants):.2f}, mais total_tva = {p.total_tva:.2f}.")
    return erreurs


def _controle_conditions(e: DocumentCommercial) -> list[str]:
    c = e.conditions
    return (_controle_pourcentage(c.acompte_pourcentage, "acompte_pourcentage")
            + _controle_pourcentage(c.escompte_pourcentage, "escompte_pourcentage"))


def _controle_dates(e: DocumentCommercial) -> list[str]:
    t = e.en_tete
    erreurs = []
    for nom in ("date_document", "date_echeance", "date_validite", "date_debut_execution", "date_fin_execution"):
        erreurs += _controle_format_date(getattr(t, nom), nom)

    emission, echeance = _date(t.date_document), _date(t.date_echeance)
    if emission and echeance and echeance < emission:
        erreurs.append(f"date_echeance ({echeance}) est antérieure à date_document ({emission}).")
    debut, fin = _date(t.date_debut_execution), _date(t.date_fin_execution)
    if debut and fin and fin < debut:
        erreurs.append(f"date_fin_execution ({fin}) est antérieure à date_debut_execution ({debut}).")
    return erreurs


def _controle_parties(*parties: tuple[Partie, str]) -> list[str]:
    return [err for p, nom in parties for err in _controle_identifiant(p.siret, f"{nom}.siret", (9, 14))]


def _controles_document(e: DocumentCommercial) -> list[str]:
    """Contrôles du pied, des conditions, des dates et des parties, communs aux trois secteurs."""
    return (_controle_pied(e) + _controle_conditions(e) + _controle_dates(e)
            + _controle_parties((e.emetteur, "emetteur"), (e.destinataire, "destinataire")))


# --------------------------------------------------------------------------- #
# Contrôles par secteur
# --------------------------------------------------------------------------- #

def controles_btp(e: ExtractionBTP) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = [] if e.lignes else ["Aucune ligne extraite alors que le document n'est pas hors sujet."]
    erreurs += _controle_lignes(e.lignes, "Ligne") + _controle_somme(e.lignes, e) + _controles_document(e)
    erreurs += _controle_pourcentage(e.retenue_garantie_pourcentage, "retenue_garantie_pourcentage")

    if e.type_document == "situation_travaux" and e.situation is None:
        erreurs.append("type_document = situation_travaux, mais situation est null.")
    if e.situation is not None:
        erreurs += _controle_pourcentage(e.situation.avancement_pourcentage, "situation.avancement_pourcentage")
    return erreurs


def controles_services(e: ExtractionServices) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = [] if e.lignes else ["Aucune ligne extraite alors que le document n'est pas hors sujet."]
    erreurs += _controle_lignes(e.lignes, "Ligne") + _controle_somme(e.lignes, e) + _controles_document(e)

    # Échéancier en pourcentages : il doit couvrir tout le montant
    parts = [ech.pourcentage for ech in e.echeancier]
    if parts and None not in parts and not _proche(sum(parts), 100):
        erreurs.append(f"Somme des pourcentages de l'échéancier = {sum(parts):.2f}, attendu 100.")
    for i, ech in enumerate(e.echeancier, start=1):
        erreurs += _controle_format_date(ech.date, f"echeancier {i} : date")
    return erreurs


def _controle_taux_horaire(heures, taux, cout, nom: str) -> list[str]:
    if None not in (heures, taux, cout) and not _proche(heures * taux, cout):
        return [f"{nom} : heures × taux horaire = {heures * taux:.2f}, mais coût = {cout:.2f}."]
    return []


def controles_industrie(e: ExtractionIndustrie) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = []
    if not e.lignes_commande and not e.fiches_prix_revient:
        erreurs.append("Ni ligne de commande ni fiche de prix de revient extraite.")

    erreurs += _controle_lignes(e.lignes_commande, "Ligne de commande")
    erreurs += _controle_somme(e.lignes_commande, e)
    erreurs += _controle_format_date(e.livraison.date_livraison, "livraison.date_livraison")

    # La somme des composants n'est pas comparée au coût matière : pertes et rebuts peuvent s'y ajouter.
    for i, f in enumerate(e.fiches_prix_revient, start=1):
        couts = [f.cout_matiere, f.cout_main_oeuvre, f.cout_machine, f.autres_couts]
        if f.cout_revient_total is not None and None not in couts:
            if not _proche(sum(couts), f.cout_revient_total):
                erreurs.append(f"Fiche {i} : somme des coûts = {sum(couts):.2f}, "
                               f"mais cout_revient_total = {f.cout_revient_total:.2f}.")
        erreurs += _controle_taux_horaire(f.heures_main_oeuvre, f.taux_horaire_main_oeuvre, f.cout_main_oeuvre,
                                          f"Fiche {i}, main-d'œuvre")
        erreurs += _controle_taux_horaire(f.heures_machine, f.taux_horaire_machine, f.cout_machine,
                                          f"Fiche {i}, machine")
        erreurs += _controle_pourcentage(f.taux_frais_generaux, f"Fiche {i} : taux_frais_generaux")
        erreurs += _controle_pourcentage(f.taux_rebut, f"Fiche {i} : taux_rebut")

    return erreurs + _controles_document(e)


# --------------------------------------------------------------------------- #
# Comptes annuels
# --------------------------------------------------------------------------- #

# Postes qui ne peuvent pas être négatifs (variations de stock, résultats, report à nouveau,
# production stockée et impôt sur les bénéfices le peuvent)
_POSTES_POSITIFS = {
    "actif": (
        "immobilisations_incorporelles_net", "terrains_net", "constructions_net", "installations_techniques_brut",
        "installations_techniques_net", "autres_immobilisations_corporelles_net", "immobilisations_financieres_net",
        "total_actif_immobilise_brut", "total_actif_immobilise_net", "stocks", "creances_clients",
        "autres_creances", "valeurs_mobilieres_placement", "disponibilites", "charges_constatees_avance",
        "total_actif",
    ),
    "passif": (
        "capital_social", "provisions_risques_charges", "emprunts_dettes_financieres", "dettes_fournisseurs",
        "dettes_fiscales_sociales", "autres_dettes", "produits_constates_avance", "total_passif",
    ),
    "compte_resultat": (
        "ventes_marchandises", "production_vendue_biens", "production_vendue_services", "chiffre_affaires",
        "subventions_exploitation", "total_produits_exploitation", "achats_marchandises",
        "achats_matieres_premieres", "autres_achats_charges_externes", "impots_taxes", "salaires_traitements",
        "charges_sociales", "dotations_amortissements", "dotations_provisions", "total_charges_exploitation",
        "produits_financiers", "charges_financieres", "interets_charges_assimilees", "produits_exceptionnels",
        "charges_exceptionnelles", "participation_salaries", "total_produits", "total_charges",
    ),
    "annexe": ("effectif_moyen", "credit_bail_redevances_exercice", "credit_bail_valeur_origine"),
}


def _controle_difference(a, b, resultat, libelle: str, nom_resultat: str) -> list[str]:
    """a - b = résultat (si les trois sont renseignés)."""
    if None not in (a, b, resultat) and not _proche(a - b, resultat):
        return [f"{libelle} = {a - b:.2f}, mais {nom_resultat} = {resultat:.2f}."]
    return []


def controles_comptes_annuels(e: ExtractionComptesAnnuels) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    ident, actif, passif, cr = e.identification, e.actif, e.passif, e.compte_resultat
    erreurs = []
    if actif.total_actif is None and passif.total_passif is None and cr.chiffre_affaires is None:
        erreurs.append("Ni total du bilan ni chiffre d'affaires extrait alors que le document n'est pas hors sujet.")

    # Bilan équilibré : une erreur de colonne (N-1, brut) le casse presque toujours
    if actif.total_actif is not None and passif.total_passif is not None \
            and not _proche(actif.total_actif, passif.total_passif):
        erreurs.append(f"total_actif ({actif.total_actif:.2f}) est différent de total_passif "
                       f"({passif.total_passif:.2f}).")

    for brut, net, nom in ((actif.installations_techniques_brut, actif.installations_techniques_net,
                            "installations_techniques"),
                           (actif.total_actif_immobilise_brut, actif.total_actif_immobilise_net,
                            "total_actif_immobilise")):
        if brut is not None and net is not None and net > brut:
            erreurs.append(f"{nom}_net ({net:.2f}) est supérieur au brut ({brut:.2f}).")

    # Compte de résultat : chaque résultat intermédiaire, puis le résultat net
    erreurs += _controle_difference(cr.total_produits, cr.total_charges, cr.resultat_net,
                                    "total_produits - total_charges", "resultat_net")
    erreurs += _controle_difference(cr.total_produits_exploitation, cr.total_charges_exploitation,
                                    cr.resultat_exploitation, "produits - charges d'exploitation",
                                    "resultat_exploitation")
    erreurs += _controle_difference(cr.produits_financiers, cr.charges_financieres, cr.resultat_financier,
                                    "produits - charges financières", "resultat_financier")
    erreurs += _controle_difference(cr.produits_exceptionnels, cr.charges_exceptionnelles,
                                    cr.resultat_exceptionnel, "produits - charges exceptionnels",
                                    "resultat_exceptionnel")
    # Participation et impôt absents : aucune ligne dans le document, donc 0
    if None not in (cr.resultat_exploitation, cr.resultat_financier, cr.resultat_exceptionnel, cr.resultat_net):
        attendu = (cr.resultat_exploitation + cr.resultat_financier + cr.resultat_exceptionnel
                   - (cr.participation_salaries or 0) - (cr.impots_benefices or 0))
        if not _proche(attendu, cr.resultat_net):
            erreurs.append(f"exploitation + financier + exceptionnel - participation - impôt = {attendu:.2f}, "
                           f"mais resultat_net = {cr.resultat_net:.2f}.")
    if None not in (passif.resultat_exercice, cr.resultat_net) and not _proche(passif.resultat_exercice,
                                                                                 cr.resultat_net):
        erreurs.append(f"resultat_exercice au passif ({passif.resultat_exercice:.2f}) est différent du "
                       f"resultat_net ({cr.resultat_net:.2f}).")

    # Identification
    if ident.duree_exercice_mois is not None and not 1 <= ident.duree_exercice_mois <= 24:
        erreurs.append(f"duree_exercice_mois = {ident.duree_exercice_mois}, attendu entre 1 et 24.")
    erreurs += _controle_format_date(ident.date_ouverture, "date_ouverture")
    erreurs += _controle_format_date(ident.date_cloture, "date_cloture")
    ouverture, cloture = _date(ident.date_ouverture), _date(ident.date_cloture)
    if ouverture and cloture and cloture <= ouverture:
        erreurs.append(f"date_cloture ({cloture}) n'est pas postérieure à date_ouverture ({ouverture}).")
    erreurs += _controle_identifiant(ident.siren, "siren", (9,))

    for bloc, noms in _POSTES_POSITIFS.items():
        for nom in noms:
            valeur = getattr(getattr(e, bloc), nom)
            if valeur is not None and valeur < 0:
                erreurs.append(f"{nom} = {valeur:.2f}, ce poste ne peut pas être négatif.")

    return erreurs


CONTROLES_PAR_TYPE = {
    "BTP": controles_btp,
    "SERVICES": controles_services,
    "INDUSTRIE": controles_industrie,
    "COMPTES_ANNUELS": controles_comptes_annuels,
}
