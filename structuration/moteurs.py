"""Moteur de calcul du cockpit (Module 3) : un moteur par secteur. Le code calcule, sans LLM.

Ce module ne connaît ni Django ni la base. Il reçoit :
- les indicateurs de l'audit (`companies.services.indicators.compute_indicators`) ;
- les réponses du dirigeant aux questions rattachées à une entrée (champ `variable` d'une
  question) : {cle: {"statut": en_attente | repondue | ignoree, "valeur": ..., "tour": n}} ;
- l'état du questionnaire : {"tours_ok": n, "dernier_tour_vide": bool} ;
- les paramètres du secteur (coefficient d'improductivité...).

Aucune formule n'est inventée. Statuts :
- entrée : ok (valeur connue) / manquant (à obtenir du dirigeant ou d'un document) /
  non_defini (méthode pas encore fixée) ;
- indicateur et composante de la perte : manquant si une de leurs entrées n'est pas ok (liste
  `manquants`), sinon non_defini si la méthode n'est pas fixée, sinon ok.
Une réponse du dirigeant remplace la valeur tirée des documents : la réalité prime sur les documents.

Quand Ny Aina valide une méthode, il suffit de remplacer ici un `calcul=None` (ou une entrée
non_defini) par le calcul : le format renvoyé au front ne change pas.
"""

from dataclasses import dataclass

OK, MANQUANT, NON_DEFINI = "ok", "manquant", "non_defini"
TYPES_REPONSE_NUMERIQUES = ("montant", "pourcentage", "nombre")

PARAMETRES = {
    # Cahier des charges : coefficient d'improductivité par défaut de 20 % dans le BTP (trajets,
    # approvisionnements, gestion). En points (20 = 20 %).
    "BTP": {"coefficient_improductivite": 20},
    "SERVICES": {},
    "INDUSTRIE": {},
}


@dataclass(frozen=True)
class Entree:
    label: str
    unite: str | None
    # Peut être demandée au dirigeant (variable d'une question). Non : seul un document la donne.
    demandable: bool = True


CATALOGUE = {
    # Communes
    "effectif": Entree("Effectif", "salariés"),
    "masse_salariale_mensuelle": Entree("Masse salariale mensuelle", "€"),
    "charges_fixes_structure": Entree("Charges fixes de structure mensuelles", "€"),
    "delai_reglement_moyen": Entree("Délai de règlement moyen", "j"),
    "acompte_moyen": Entree("Acompte moyen", "%"),
    # BTP
    "heures_facturables_mensuelles": Entree("Heures facturables réelles par mois", "h"),
    "coefficient_improductivite": Entree("Coefficient d'improductivité", "%", demandable=False),
    "taux_horaire_facture": Entree("Taux horaire facturé", "€/h"),
    "volume_heures_mensuel": Entree("Volume d'heures mensuel", "h"),
    # Services
    "heures_vendues_mensuelles": Entree("Heures facturables réellement vendues par mois", "h"),
    "tjm_vendu_regie": Entree("TJM vendu en régie", "€/j"),
    "tjm_implicite_forfaits": Entree("TJM implicite des forfaits", "€/j"),
    "taux_occupation": Entree("Taux d'occupation (part du temps facturée)", "%"),
    "heures_hors_forfait_mensuelles": Entree("Heures passées hors forfait, non facturées, par mois", "h"),
    "heures_execution_dirigeant_mensuelles": Entree("Heures d'exécution du dirigeant par mois", "h"),
    # Industrie
    "marge_sur_couts_variables": Entree("Marge sur coûts variables des commandes", "€", demandable=False),
    "stocks": Entree("Stocks", "€"),
    "dotations_amortissements": Entree("Dotations aux amortissements de l'exercice", "€", demandable=False),
    "installations_techniques_brut": Entree("Installations techniques (valeur brute)", "€", demandable=False),
    "installations_techniques_net": Entree("Installations techniques (valeur nette)", "€", demandable=False),
    "cout_non_qualite_annuel": Entree("Coût annuel des rebuts et de la non-qualité", "€"),
    "heures_arret_machine_mensuelles": Entree("Heures d'arrêt machine par mois", "h"),
}

SOURCES = {"comptes_annuels": "comptes annuels", "api": "données publiées", "documents": "documents",
           "questionnaire": "questionnaire", "parametre": "paramètre"}


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #

def _nombre(x) -> float | int | None:
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _division(a, b) -> float | None:
    return a / b if b else None


def _fmt(x) -> str:
    """Nombre à la française : 704 000 ; 58 666,67."""
    if isinstance(x, float) and not x.is_integer():
        texte = f"{x:,.2f}"
    else:
        texte = f"{int(x):,}"
    return texte.replace(",", " ").replace(".", ",")


def _date_fr(iso: str | None) -> str | None:
    if not iso or len(iso) < 10:
        return iso
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def _comptes(ind: dict) -> dict:
    return ind.get("comptes_annuels") or {}


def _documents(ind: dict) -> dict:
    return ind.get("documents_commerciaux") or {}


def _cloture(ind: dict) -> str:
    date = _date_fr(_comptes(ind).get("date_cloture"))
    return f" (exercice clos le {date})" if date else ""


# --------------------------------------------------------------------------- #
# Entrées
# --------------------------------------------------------------------------- #

def _entree(cle: str, valeur=None, source: str | None = None, detail: str | None = None,
            statut: str | None = None, lignes: list | None = None) -> dict:
    """
    Entrée du cockpit. Statut par défaut : ok si la valeur est connue, manquant sinon.
    `lignes` : détail d'une valeur agrégée (marges par produit), null pour les autres entrées.
    """
    definition = CATALOGUE[cle]
    valeur = _nombre(valeur)
    if statut is None:
        statut = OK if valeur is not None else MANQUANT
    return {
        "cle": cle,
        "label": definition.label,
        "valeur": valeur,
        "unite": definition.unite,
        "source": source if valeur is not None else None,
        "detail": detail,
        "statut": statut,
        "lignes": lignes,
    }


def _non_defini(cle: str, detail: str) -> dict:
    return _entree(cle, None, detail=detail, statut=NON_DEFINI)


def _a_demander(cle: str, detail: str = "à demander au dirigeant") -> dict:
    return _entree(cle, None, detail=detail)


def _effectif(ind: dict) -> dict:
    effectif = ind.get("effectif") or {}
    source = effectif.get("source")
    if source == "comptes_annuels":
        detail = f"effectif moyen des comptes annuels{_cloture(ind)}"
    elif source == "api":
        detail = "effectif publié de l'établissement"
    else:
        detail = "à demander au dirigeant"
    return _entree("effectif", effectif.get("valeur"), source, detail)


def _depuis_comptes(ind: dict, cle: str, champ: str, detail: str) -> dict:
    """Entrée lue dans les comptes annuels retenus ; manquante s'ils sont absents ou muets."""
    valeur = _nombre(_comptes(ind).get(champ))
    if valeur is not None:
        return _entree(cle, valeur, "comptes_annuels", detail + _cloture(ind))
    pourquoi = "absent des comptes annuels" if ind.get("comptes_annuels") else "comptes annuels non fournis"
    suite = " : à demander au dirigeant" if CATALOGUE[cle].demandable else ""
    return _a_demander(cle, pourquoi + suite)


def _masse_salariale(ind: dict) -> tuple[dict, dict | None]:
    comptes = _comptes(ind)
    duree = comptes.get("duree_exercice_mois")
    entree = _depuis_comptes(ind, "masse_salariale_mensuelle", "masse_salariale_mensuelle",
                             f"(salaires + charges sociales) ÷ {duree or '?'} mois")
    etape = None
    if entree["statut"] == OK and _nombre(comptes.get("masse_salariale_annuelle")) is not None and duree:
        etape = {"libelle": "Masse salariale mensuelle",
                 "equation": f"{_fmt(comptes['masse_salariale_annuelle'])} € ÷ {duree} mois",
                 "resultat": entree["valeur"], "unite": "€"}
    return entree, etape


def _depuis_documents(ind: dict, cle: str, valeur, detail: str) -> dict:
    """Entrée tirée des documents commerciaux de vente ; manquante sinon (le dirigeant peut la donner)."""
    if _nombre(valeur) is not None:
        return _entree(cle, valeur, "documents", detail)
    documents = _documents(ind)
    if not documents:
        pourquoi = "aucun document commercial pris en compte"
    elif set(documents) == {"documents_achat_exclus"}:
        pourquoi = "seulement des documents d'achat (fournisseurs), sans prix de vente"
    else:
        pourquoi = "non trouvé dans les documents"
    return _a_demander(cle, pourquoi + " : à demander au dirigeant")


def _conditions_paiement(ind: dict) -> list[dict]:
    conditions = _documents(ind).get("conditions_de_paiement") or {}
    return [
        _depuis_documents(ind, "delai_reglement_moyen", conditions.get("delai_reglement_jours_moyen"),
                          "moyenne des documents de vente qui l'indiquent"),
        _depuis_documents(ind, "acompte_moyen", conditions.get("acompte_pourcentage_moyen"),
                          "moyenne des documents de vente qui l'indiquent"),
    ]


def _parametre(cle: str, parametres: dict, detail: str) -> dict:
    valeur = parametres.get(cle)
    if valeur is None:
        return _non_defini(cle, "paramètre non renseigné")
    return _entree(cle, valeur, "parametre", detail)


def _appliquer_reponses(entrees: list[dict], reponses: dict) -> set[str]:
    """
    Remplace la valeur d'une entrée par la réponse du dirigeant à la question qui porte sa clé
    (statut « repondue », valeur numérique). Les paramètres et les entrées non définies ne sont
    pas concernés. Renvoie les clés remplacées.
    """
    remplacees = set()
    for entree in entrees:
        reponse = reponses.get(entree["cle"])
        if not reponse or reponse.get("statut") != "repondue":
            continue
        if entree["statut"] == NON_DEFINI or entree["source"] == "parametre":
            continue
        valeur = _nombre(reponse.get("valeur"))
        if valeur is None:
            continue
        detail = f"réponse du dirigeant (tour {reponse.get('tour')})"
        if entree["valeur"] is not None and entree["valeur"] != valeur:
            unite = f" {entree['unite']}" if entree["unite"] else ""
            detail += f" ; {SOURCES.get(entree['source'], entree['source'])} : {_fmt(entree['valeur'])}{unite}"
        entree.update(valeur=valeur, source="questionnaire", statut=OK, detail=detail)
        remplacees.add(entree["cle"])
    return remplacees


def entrees_a_demander(entrees: list[dict], reponses: dict) -> list[dict]:
    """
    Entrées que l'agent du questionnaire peut rattacher à une question (champ `variable`) :
    - obligatoire : entrée manquante, à demander au dirigeant ;
    - non obligatoire : valeur tirée des documents, que le dirigeant peut confirmer ou corriger.
    Une entrée déjà demandée à un tour précédent (quel que soit le statut de la question, ignorée
    comprise) n'est plus proposée. Les comptes annuels, les paramètres, les entrées non définies et
    celles que seul un document donne ne sont jamais proposés.
    """
    resultat = []
    for entree in entrees:
        if entree["cle"] in reponses or not CATALOGUE[entree["cle"]].demandable:
            continue
        if entree["statut"] == MANQUANT:
            obligatoire = True
        elif entree["statut"] == OK and entree["source"] == "documents":
            obligatoire = False
        else:
            continue
        resultat.append({
            "cle": entree["cle"],
            "label": entree["label"],
            "unite": entree["unite"],
            "valeur": entree["valeur"],
            "source": entree["source"],
            "obligatoire": obligatoire,
        })
    return resultat


# --------------------------------------------------------------------------- #
# Indicateurs et composantes de la perte
# --------------------------------------------------------------------------- #

def _etat(valeurs: dict, entrees, calcul, dependances) -> tuple[float | None, list[str], str]:
    """
    (valeur, manquants, statut) d'un indicateur ou d'une composante.
    `entrees` : clés des entrées utilisées ; `dependances` : indicateurs utilisés (leurs manquants
    sont repris) ; `calcul` : fonction sans argument, None si la méthode n'est pas fixée.
    """
    manquants = [c for c in entrees if valeurs[c]["statut"] != OK]
    manquants += [m for d in dependances for m in d["manquants"]]
    manquants = list(dict.fromkeys(manquants))
    if manquants:
        return None, manquants, MANQUANT
    if calcul is None or any(d["statut"] != OK for d in dependances):
        return None, [], NON_DEFINI
    valeur = calcul()
    if valeur is None:  # division par zéro : entrée nulle
        return None, [], NON_DEFINI
    return round(valeur, 2), [], OK


def _indicateur(valeurs: dict, cle: str, nom: str, unite: str | None, formule: str, entrees=(), calcul=None,
                dependances=(), pivot: bool = False, comparaison: str | None = None) -> dict:
    valeur, manquants, statut = _etat(valeurs, entrees, calcul, dependances)
    return {"cle": cle, "nom": nom, "valeur": valeur, "unite": unite, "formule": formule, "pivot": pivot,
            "comparaison": comparaison, "manquants": manquants, "statut": statut}


def _composante(valeurs: dict, cle: str, label: str, entrees=(), calcul=None, dependances=()) -> dict:
    valeur, manquants, statut = _etat(valeurs, entrees, calcul, dependances)
    return {"cle": cle, "label": label, "valeur": valeur, "manquants": manquants, "statut": statut}


def _perte(composantes: list[dict]) -> dict:
    """Perte annuelle : somme des composantes calculées ; partielle si une composante ne l'est pas."""
    connues = [c["valeur"] for c in composantes if c["statut"] == OK]
    return {
        "valeur": round(sum(connues), 2) if connues else None,
        "partielle": any(c["statut"] != OK for c in composantes),
        "composantes": composantes,
    }


def _v(valeurs: dict, cle: str):
    return valeurs[cle]["valeur"]


def _rappel(valeurs: dict, cle: str, prefixe: str) -> str | None:
    """« prefixe : valeur unité » si l'entrée est connue, pour la ligne de comparaison d'un indicateur."""
    entree = valeurs[cle]
    if entree["valeur"] is None:
        return None
    unite = f" {entree['unite']}" if entree["unite"] else ""
    return f"{prefixe} : {_fmt(entree['valeur'])}{unite}"


# --------------------------------------------------------------------------- #
# BTP : « Chantiers & marge brute »
# --------------------------------------------------------------------------- #

def entrees_btp(ind: dict, parametres: dict) -> tuple[list[dict], dict]:
    documents = _documents(ind)
    masse, etape_masse = _masse_salariale(ind)
    taux = _depuis_documents(ind, "taux_horaire_facture", documents.get("taux_horaire_main_oeuvre"),
                             "montant ÷ heures des lignes de main-d'œuvre en heures (documents de vente)")
    etapes = {"masse_salariale_mensuelle": etape_masse}
    if taux["statut"] == OK and _nombre(documents.get("heures_main_oeuvre")):
        etapes["taux_horaire_facture"] = {
            "libelle": "Taux horaire facturé",
            "equation": f"montant des lignes de main-d'œuvre en heures ÷ {_fmt(documents['heures_main_oeuvre'])} h",
            "resultat": taux["valeur"], "unite": "€/h"}
    entrees = [
        _effectif(ind),
        masse,
        _non_defini("charges_fixes_structure", "postes à retenir non définis (à valider avec Ny Aina)"),
        _a_demander("heures_facturables_mensuelles"),
        _parametre("coefficient_improductivite", parametres, "valeur par défaut du BTP (cahier des charges)"),
        taux,
        _a_demander("volume_heures_mensuel"),
        *_conditions_paiement(ind),
    ]
    return entrees, etapes


def calculs_btp(valeurs: dict) -> tuple[list[dict], list[dict]]:
    coefficient = _v(valeurs, "coefficient_improductivite")
    chr_ = _indicateur(
        valeurs, "chr", "Coût Horaire Chargé Réel (CHr)", "€/h",
        "CHr = (masse salariale mensuelle + charges fixes de structure)\n      ÷ heures facturables réelles\n"
        f"Coefficient d'improductivité ({_fmt(coefficient) if coefficient is not None else '?'} %) : "
        "emplacement dans la formule à valider",
        entrees=("masse_salariale_mensuelle", "charges_fixes_structure", "heures_facturables_mensuelles",
                 "coefficient_improductivite"),
        calcul=None,  # emplacement du coefficient d'improductivité non fixé
        pivot=True,
        comparaison=_rappel(valeurs, "taux_horaire_facture", "taux horaire facturé"),
    )
    emo = _indicateur(
        valeurs, "emo", "Écart de Facturation Main-d'œuvre (Emo)", "€/mois",
        "Emo = (CHr − taux horaire facturé) × volume d'heures mensuel",
        entrees=("taux_horaire_facture", "volume_heures_mensuel"),
        calcul=lambda: (chr_["valeur"] - _v(valeurs, "taux_horaire_facture")) * _v(valeurs, "volume_heures_mensuel"),
        dependances=(chr_,),
    )
    bfr = _indicateur(
        valeurs, "indice_bfr", "Indice de Risque BFR / Trésorerie", None,
        "f(délai moyen de paiement, coût d'encours de chantier) : méthode à définir",
        entrees=("delai_reglement_moyen",),
        comparaison=_rappel(valeurs, "delai_reglement_moyen", "délai de règlement moyen détecté"),
    )
    composantes = [
        _composante(valeurs, "emo_annuel", "Écart main-d'œuvre annuel (Emo × 12)",
                    calcul=lambda: emo["valeur"] * 12, dependances=(emo,)),
        _composante(valeurs, "retards_acompte", "Pertes sur retards d'acompte"),
        _composante(valeurs, "surcouts_administratifs", "Surcoûts administratifs hors devis"),
    ]
    return [chr_, emo, bfr], composantes


# --------------------------------------------------------------------------- #
# SERVICES : « Temps / TJM & taux d'occupation »
# --------------------------------------------------------------------------- #

def entrees_services(ind: dict, parametres: dict) -> tuple[list[dict], dict]:
    documents = _documents(ind)
    masse, etape_masse = _masse_salariale(ind)
    entrees = [
        _effectif(ind),
        masse,
        _non_defini("charges_fixes_structure", "postes à retenir non définis (à valider avec Ny Aina)"),
        _a_demander("heures_vendues_mensuelles"),
        _depuis_documents(ind, "tjm_vendu_regie", documents.get("tjm_vendu_regie"),
                          "montant ÷ jours des lignes en régie au jour (documents de vente)"),
        _depuis_documents(ind, "tjm_implicite_forfaits", documents.get("tjm_implicite_forfaits"),
                          "montant ÷ jours estimés des forfaits qui les indiquent (documents de vente)"),
        _a_demander("taux_occupation"),
        _a_demander("heures_hors_forfait_mensuelles"),
        _a_demander("heures_execution_dirigeant_mensuelles"),
        *_conditions_paiement(ind),
    ]
    return entrees, {"masse_salariale_mensuelle": etape_masse}


def calculs_services(valeurs: dict) -> tuple[list[dict], list[dict]]:
    cout = _indicateur(
        valeurs, "cout_du_temps", "Coût du temps (coût horaire réel)", "€/h",
        "Coût du temps = (masse salariale mensuelle + frais fixes de structure)\n"
        "      ÷ heures facturables réellement vendues par mois",
        entrees=("masse_salariale_mensuelle", "charges_fixes_structure", "heures_vendues_mensuelles"),
        calcul=lambda: _division(_v(valeurs, "masse_salariale_mensuelle") + _v(valeurs, "charges_fixes_structure"),
                                 _v(valeurs, "heures_vendues_mensuelles")),
        pivot=True,
        comparaison=_rappel(valeurs, "tjm_vendu_regie", "TJM vendu en régie"),
    )
    ecart = _indicateur(
        valeurs, "ecart_tjm", "Écart TJM réel chargé / TJM vendu", "€/j",
        "TJM réel chargé − TJM vendu (conversion du coût horaire en coût journalier à définir)",
        entrees=("tjm_vendu_regie",), dependances=(cout,),
    )
    bfr = _indicateur(
        valeurs, "indice_bfr", "Indice de Risque BFR / Trésorerie", None,
        "f(délais de paiement clients, impayés) : méthode à définir",
        entrees=("delai_reglement_moyen",),
        comparaison=_rappel(valeurs, "delai_reglement_moyen", "délai de règlement moyen détecté"),
    )
    composantes = [
        _composante(valeurs, "temps_non_facturable", "Temps non facturable (taux d'occupation)",
                    entrees=("taux_occupation",)),
        _composante(valeurs, "scope_creep", "Heures hors forfait non facturées (scope creep)",
                    entrees=("heures_hors_forfait_mensuelles",)),
        _composante(valeurs, "valeur_dirigeant", "Temps d'exécution du dirigeant (perte d'opportunité)",
                    entrees=("heures_execution_dirigeant_mensuelles",)),
    ]
    return [cout, ecart, bfr], composantes


# --------------------------------------------------------------------------- #
# INDUSTRIE : « Coûts de revient & stocks / machines »
# --------------------------------------------------------------------------- #

def _marge_sur_couts_variables(ind: dict) -> tuple[dict, dict | None]:
    """
    Somme des marges totales des produits rapprochés entre bons de commande et fiches de prix de
    revient (`indicateurs._marges_croisees`), avec le détail par produit dans `lignes`. Les produits
    sans quantité commandée n'ont pas de marge totale : ils restent dans les lignes, hors somme.
    """
    lignes = _documents(ind).get("marges_sur_couts_variables") or []
    totales = [l["marge_totale"] for l in lignes if _nombre(l.get("marge_totale")) is not None]
    if not lignes:
        pourquoi = ("aucun document commercial pris en compte" if not _documents(ind)
                    else "aucun produit rapproché entre bons de commande et fiches de prix de revient")
        return _entree("marge_sur_couts_variables", None, detail=pourquoi + " : documents à fournir"), None
    detail = f"{len(totales)} produit(s) rapproché(s) entre bons de commande et fiches de prix de revient"
    if len(totales) < len(lignes):
        detail += f", {len(lignes) - len(totales)} sans quantité (hors somme)"
    valeur = round(sum(totales), 2) if totales else None
    entree = _entree("marge_sur_couts_variables", valeur, "documents", detail, lignes=lignes)
    etape = None
    if valeur is not None:
        etape = {"libelle": "Marge sur coûts variables des commandes",
                 "equation": f"Σ (prix unitaire − coûts variables unitaires) × quantité, {len(totales)} produit(s)",
                 "resultat": valeur, "unite": "€"}
    return entree, etape


def _taux_marge(valeurs: dict) -> float | None:
    """Taux de marge sur coûts variables : marge ÷ chiffre d'affaires des mêmes lignes, en %."""
    lignes = [l for l in valeurs["marge_sur_couts_variables"]["lignes"] or []
              if _nombre(l.get("marge_totale")) is not None and _nombre(l.get("prix_unitaire_ht")) is not None]
    chiffre_affaires = sum(l["prix_unitaire_ht"] * l["quantite"] for l in lignes)
    marge = _division(sum(l["marge_totale"] for l in lignes), chiffre_affaires)
    return 100 * marge if marge is not None else None


def entrees_industrie(ind: dict, parametres: dict) -> tuple[list[dict], dict]:
    marge, etape_marge = _marge_sur_couts_variables(ind)
    entrees = [
        _effectif(ind),
        marge,
        _depuis_comptes(ind, "stocks", "stocks", "stocks à l'actif"),
        _depuis_comptes(ind, "dotations_amortissements", "dotations_amortissements", "compte de résultat"),
        _depuis_comptes(ind, "installations_techniques_brut", "installations_techniques_brut", "actif immobilisé"),
        _depuis_comptes(ind, "installations_techniques_net", "installations_techniques_net", "actif immobilisé"),
        _a_demander("cout_non_qualite_annuel"),
        _a_demander("heures_arret_machine_mensuelles"),
        *_conditions_paiement(ind),
    ]
    return entrees, {"marge_sur_couts_variables": etape_marge}


def calculs_industrie(valeurs: dict) -> tuple[list[dict], list[dict]]:
    taux = _indicateur(
        valeurs, "taux_marge_sur_couts_variables", "Taux de marge sur coûts variables", "%",
        "Taux = marge sur coûts variables ÷ chiffre d'affaires des mêmes lignes de commande",
        entrees=("marge_sur_couts_variables",), calcul=lambda: _taux_marge(valeurs), pivot=True,
    )
    trs = _indicateur(
        valeurs, "trs", "Taux de Rendement Synthétique (TRS)", "%",
        "TRS = disponibilité × performance × qualité (données de production à définir)",
    )
    arret = _indicateur(
        valeurs, "cout_arret_machine", "Coût des arrêts machine", "€/mois",
        "heures d'arrêt × coût horaire machine (base de calcul du coût horaire à définir)",
        entrees=("heures_arret_machine_mensuelles", "dotations_amortissements"),
    )
    stockage = _indicateur(
        valeurs, "cout_sur_stockage", "Coût du sur-stockage (BFR)", "€/an",
        "stocks × taux de portage (taux à définir)",
        entrees=("stocks",),
        comparaison=_rappel(valeurs, "stocks", "stocks"),
    )
    composantes = [
        _composante(valeurs, "cout_non_qualite", "Coût de non-qualité (rebuts)",
                    entrees=("cout_non_qualite_annuel",), calcul=lambda: _v(valeurs, "cout_non_qualite_annuel")),
        _composante(valeurs, "arret_machine", "Temps d'arrêt machine", dependances=(arret,)),
        _composante(valeurs, "sur_stockage", "Coût de sur-stockage", dependances=(stockage,)),
    ]
    return [taux, trs, arret, stockage], composantes


MOTEURS = {
    "BTP": (entrees_btp, calculs_btp),
    "SERVICES": (entrees_services, calculs_services),
    "INDUSTRIE": (entrees_industrie, calculs_industrie),
}


# --------------------------------------------------------------------------- #
# Contrôles et assemblage
# --------------------------------------------------------------------------- #

def _liste(labels: list[str]) -> str:
    return ", ".join(label[0].lower() + label[1:] for label in labels)


def _controles(secteur: str, ind: dict, entrees: list[dict], reponses: dict, questionnaire: dict) -> list[dict]:
    controles = [{"ok": True, "texte": f"Secteur {secteur} choisi à l'onboarding"}]

    comptes = ind.get("comptes_annuels")
    controles.append({"ok": comptes is not None,
                      "texte": f"Comptes annuels présents{_cloture(ind)}" if comptes else "Comptes annuels non fournis"})

    pris = ind.get("documents_pris_en_compte") or 0
    controles.append({"ok": pris > 0,
                      "texte": f"{pris} document(s) pris en compte" if pris else "Aucun document pris en compte"})
    a_verifier = ind.get("documents_a_verifier") or 0
    controles.append({"ok": a_verifier == 0,
                      "texte": f"{a_verifier} document(s) à vérifier" if a_verifier else "Aucun document à vérifier"})
    achats = _documents(ind).get("documents_achat_exclus")
    if achats:
        controles.append({"ok": True, "texte": f"{achats} document(s) d'achat (fournisseurs) exclus des prix de vente"})

    obligatoires = [e["label"] for e in entrees_a_demander(entrees, reponses) if e["obligatoire"]]
    if not questionnaire.get("tours_ok"):
        controles.append({"ok": False, "texte": "Questionnaire de l'agent pas encore commencé"})
    elif not questionnaire.get("dernier_tour_vide"):
        controles.append({"ok": False, "texte": "Questionnaire de l'agent non terminé"})
    elif obligatoires:
        controles.append({"ok": False, "texte": "Questionnaire terminé, mais il reste à demander : "
                                                f"{_liste(obligatoires)} (tour supplémentaire possible)"})
    else:
        controles.append({"ok": True, "texte": "Questionnaire de l'agent terminé"})

    ignorees = [e["label"] for e in entrees
                if e["statut"] == MANQUANT and (reponses.get(e["cle"]) or {}).get("statut") == "ignoree"]
    if ignorees:
        controles.append({"ok": False, "texte": f"Question ignorée par le dirigeant : {_liste(ignorees)}"})
    return controles


def calculer_cockpit(secteur: str, indicateurs: dict, reponses: dict, questionnaire: dict,
                     parametres: dict | None = None) -> dict:
    """
    Cockpit de l'audit : entrées, indicateurs, étapes de calcul, perte annuelle, score de santé et
    contrôles (format commenté au-dessus de `getCockpit` dans le front).
    `parametres` : ceux du secteur ; PARAMETRES par défaut.
    Lève ValueError si le secteur n'a pas de moteur.
    """
    if secteur not in MOTEURS:
        raise ValueError(f"Secteur « {secteur} » non pris en charge par le moteur de calcul.")
    construire_entrees, calculer = MOTEURS[secteur]
    parametres = PARAMETRES.get(secteur, {}) if parametres is None else parametres

    entrees, etapes = construire_entrees(indicateurs, parametres)
    remplacees = _appliquer_reponses(entrees, reponses)
    indicateurs_cockpit, composantes = calculer({e["cle"]: e for e in entrees})
    return {
        "secteur": secteur,
        "entrees": entrees,
        "indicateurs": indicateurs_cockpit,
        # Une valeur remplacée par la réponse du dirigeant n'a plus d'étape de calcul.
        "etapes_calcul": [etape for cle, etape in etapes.items() if etape is not None and cle not in remplacees],
        "perte_annuelle": _perte(composantes),
        "score_sante": None,  # aucune formule ne relie le score aux indicateurs (à définir avec Ny Aina)
        "controles": _controles(secteur, indicateurs, entrees, reponses, questionnaire),
    }
