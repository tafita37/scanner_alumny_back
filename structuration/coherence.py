"""Contrôles arithmétiques : le LLM a-t-il bien recopié les nombres ?"""

from datetime import date

from .schemas import ExtractionBTP, ExtractionComptesAnnuels, ExtractionIndustrie, ExtractionServices, LigneChiffree


def _proche(a: float, b: float) -> bool:
    """Tolérance : 1 % ou 5 centimes (arrondis du document)."""
    return abs(a - b) <= max(0.05, 0.01 * abs(b))


def _controle_lignes(lignes: list[LigneChiffree], nom: str) -> list[str]:
    """quantité × prix unitaire = total de la ligne."""
    erreurs = []
    for i, l in enumerate(lignes, start=1):
        if None not in (l.quantite, l.prix_unitaire_ht, l.total_ht):
            attendu = l.quantite * l.prix_unitaire_ht
            if not _proche(attendu, l.total_ht):
                erreurs.append(f"{nom} {i} ({l.libelle}) : quantité × prix unitaire = {attendu:.2f}, "
                               f"mais total_ht = {l.total_ht:.2f}.")
    return erreurs


def _controle_somme(lignes: list[LigneChiffree], total_ht: float | None) -> list[str]:
    """Somme des lignes = total HT du document."""
    totaux = [l.total_ht for l in lignes]
    if total_ht is None or not totaux or None in totaux:
        return []
    if _proche(sum(totaux), total_ht):
        return []
    return [f"Somme des lignes = {sum(totaux):.2f}, mais total_ht du document = {total_ht:.2f}."]


def _controle_pied(e) -> list[str]:
    erreurs = []
    if e.total_ht is not None and e.total_ttc is not None and e.total_ttc < e.total_ht:
        erreurs.append(f"total_ttc ({e.total_ttc:.2f}) est inférieur à total_ht ({e.total_ht:.2f}).")
    if e.acompte_pourcentage is not None and not 0 <= e.acompte_pourcentage <= 100:
        erreurs.append(f"acompte_pourcentage = {e.acompte_pourcentage}, attendu entre 0 et 100.")
    return erreurs


def controles_btp(e: ExtractionBTP) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = [] if e.lignes else ["Aucune ligne extraite alors que le document n'est pas hors sujet."]
    return erreurs + _controle_lignes(e.lignes, "Ligne") + _controle_somme(e.lignes, e.total_ht) + _controle_pied(e)


def controles_services(e: ExtractionServices) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = [] if e.lignes else ["Aucune ligne extraite alors que le document n'est pas hors sujet."]
    return erreurs + _controle_lignes(e.lignes, "Ligne") + _controle_somme(e.lignes, e.total_ht) + _controle_pied(e)


def controles_industrie(e: ExtractionIndustrie) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = []
    if not e.lignes_commande and not e.fiches_prix_revient:
        erreurs.append("Ni ligne de commande ni fiche de prix de revient extraite.")

    erreurs += _controle_lignes(e.lignes_commande, "Ligne de commande")
    erreurs += _controle_somme(e.lignes_commande, e.total_ht)

    # Somme des coûts = coût de revient total (si tout est renseigné)
    for i, f in enumerate(e.fiches_prix_revient, start=1):
        couts = [f.cout_matiere, f.cout_main_oeuvre, f.cout_machine, f.autres_couts]
        if f.cout_revient_total is not None and None not in couts:
            if not _proche(sum(couts), f.cout_revient_total):
                erreurs.append(f"Fiche {i} : somme des coûts = {sum(couts):.2f}, "
                               f"mais cout_revient_total = {f.cout_revient_total:.2f}.")

    return erreurs + _controle_pied(e)


# Postes qui ne peuvent pas être négatifs (la variation de stock et le résultat le peuvent)
_POSTES_POSITIFS = (
    "installations_techniques_brut", "installations_techniques_net", "stocks", "creances_clients",
    "dettes_fournisseurs", "total_actif", "total_passif", "chiffre_affaires", "achats_matieres_premieres",
    "autres_achats_charges_externes", "impots_taxes", "salaires_traitements", "charges_sociales",
    "dotations_amortissements", "total_produits", "total_charges", "effectif_moyen",
)


def controles_comptes_annuels(e: ExtractionComptesAnnuels) -> list[str]:
    if e.type_document == "hors_sujet":
        return []
    erreurs = []
    if e.total_actif is None and e.total_passif is None and e.chiffre_affaires is None:
        erreurs.append("Ni total du bilan ni chiffre d'affaires extrait alors que le document n'est pas hors sujet.")

    # Bilan équilibré : une erreur de colonne (N-1, brut) le casse presque toujours
    if e.total_actif is not None and e.total_passif is not None and not _proche(e.total_actif, e.total_passif):
        erreurs.append(f"total_actif ({e.total_actif:.2f}) est différent de total_passif ({e.total_passif:.2f}).")

    if None not in (e.total_produits, e.total_charges, e.resultat_net):
        attendu = e.total_produits - e.total_charges
        if not _proche(attendu, e.resultat_net):
            erreurs.append(f"total_produits - total_charges = {attendu:.2f}, "
                           f"mais resultat_net = {e.resultat_net:.2f}.")

    if e.duree_exercice_mois is not None and not 1 <= e.duree_exercice_mois <= 24:
        erreurs.append(f"duree_exercice_mois = {e.duree_exercice_mois}, attendu entre 1 et 24.")

    if e.date_cloture is not None:
        try:
            date.fromisoformat(e.date_cloture)
        except ValueError:
            erreurs.append(f"date_cloture = {e.date_cloture!r}, attendu au format AAAA-MM-JJ.")

    if (e.installations_techniques_brut is not None and e.installations_techniques_net is not None
            and e.installations_techniques_net > e.installations_techniques_brut):
        erreurs.append(f"installations_techniques_net ({e.installations_techniques_net:.2f}) est supérieur au "
                       f"brut ({e.installations_techniques_brut:.2f}).")

    for nom in _POSTES_POSITIFS:
        valeur = getattr(e, nom)
        if valeur is not None and valeur < 0:
            erreurs.append(f"{nom} = {valeur:.2f}, ce poste ne peut pas être négatif.")

    return erreurs


CONTROLES_PAR_TYPE = {
    "BTP": controles_btp,
    "SERVICES": controles_services,
    "INDUSTRIE": controles_industrie,
    "COMPTES_ANNUELS": controles_comptes_annuels,
}