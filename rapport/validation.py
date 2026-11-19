"""
Validation par le code des textes rédigés pour le rapport : ce que le schéma strict ne garantit pas.

Erreurs (renvoyées au LLM pour un nouvel essai de la rédaction) :
- texte vide, ou trop long (MOTS_MAX : le rapport doit tenir en 12 pages, une section par page) ;
- nombre d'éléments hors limites (paragraphes de la synthèse, points clés, actions d'un levier) ;
  pas exactement NB_LEVIERS leviers ;
- commentaire d'un indicateur absent du cockpit, en double, ou indicateur du cockpit sans commentaire ;
- montant en euros absent des données de l'audit : le rapport part chez le client, aucun montant ne
  doit être inventé. Un montant est accepté s'il est à TOLERANCE_MONTANT près d'un nombre des données
  envoyées au LLM, de ce nombre × 12 ou ÷ 12 (passage mensuel / annuel), ou d'un montant
  réglementaire (MONTANTS_REGLEMENTAIRES). Les pourcentages et les durées ne sont pas contrôlés ;
- mention interne (nom de l'équipe Alumny qui valide les méthodes, statut « non défini ») ou clé
  technique du cockpit (marge_sur_couts_variables...) : le rapport est destiné au client.
Corrections faites sans erreur : espaces retirés autour des textes, commentaires des indicateurs
remis dans l'ordre du cockpit.
"""
import re

NB_LEVIERS = 3
PARAGRAPHES_SYNTHESE = (2, 4)
POINTS_CLES = (3, 4)
ACTIONS_PAR_LEVIER = (2, 4)
# Longueur maximale de chaque texte, en mots : chaque section du rapport tient sur sa page (vérifié par
# companies.tests.test_report avec des textes à ces limites).
MOTS_MAX = {
    "paragraphe de la synthèse": 75,
    "point clé": 20,
    "commentaire de la perte": 80,
    "commentaire d'indicateur": 55,
    "titre de levier": 12,
    "constat de levier": 80,
    "action": 35,
    "gain attendu": 50,
    "indicateur de suivi": 35,
    "message de conclusion": 60,
}

# Écart relatif toléré entre un montant cité et un nombre des données (arrondi : « 48 k€ » pour 47 800).
TOLERANCE_MONTANT = 0.05
# Indemnité forfaitaire pour frais de recouvrement (art. L441-10 du Code de commerce).
MONTANTS_REGLEMENTAIRES = (40,)
# Mentions internes interdites dans le rapport client : motif -> consigne renvoyée au LLM
MENTIONS_INTERDITES = {
    re.compile(r"ny\s+aina", re.IGNORECASE):
        "ne pas citer de personne de l'équipe Alumny ; parler de méthode « en cours de finalisation »",
    re.compile(r"non[\s_]d[ée]fini", re.IGNORECASE):
        "« non défini » est un statut interne : dire que la méthode de calcul est « en cours de finalisation »",
}


def cles_techniques(donnees: dict) -> set[str]:
    """Clés du cockpit (entrées, indicateurs, composantes de la perte) : à remplacer par leur libellé dans les textes."""
    cockpit = donnees.get("cockpit") or {}
    elements = [*cockpit.get("entrees", []), *cockpit.get("indicateurs", []),
                *(cockpit.get("perte_annuelle") or {}).get("composantes", [])]
    return {e["cle"] for e in elements if "_" in e.get("cle", "")}

_ESPACES = "   "  # espace, espace insécable, espace fine insécable
# « 12 000 », « 12.000 », « 12 000,50 » ou « 12000 », « 12,5 » ; puis « k », « M » ou « millions d' » ; puis € / euros / EUR.
MONTANT = re.compile(
    rf"(?<![\d,.])(?P<nombre>\d{{1,3}}(?:[{_ESPACES}.]\d{{3}})+(?:,\d+)?|\d+(?:[,.]\d+)?)"
    rf"[{_ESPACES}]?(?P<multiple>k|K|M|millions?\s+d['’]|milliers?\s+d['’])?[{_ESPACES}]?"
    r"(?:€|euros?\b|EUR\b)"
)
MULTIPLES = {"k": 1_000, "m": 1_000_000, "millions": 1_000_000, "million": 1_000_000,
             "milliers": 1_000, "millier": 1_000}


def montants_cites(texte: str) -> list[tuple[str, float]]:
    """(texte du montant, valeur en euros) de chaque montant cité dans le texte."""
    resultat = []
    for m in MONTANT.finditer(texte):
        nombre = m.group("nombre")
        if "," in nombre:
            entier, decimales = nombre.rsplit(",", 1)
        elif re.fullmatch(r"\d+\.\d{1,2}", nombre):  # « 12.5 » : point décimal
            entier, decimales = nombre.split(".")
        else:
            entier, decimales = nombre, "0"
        valeur = float(re.sub(rf"[{_ESPACES}.]", "", entier) + "." + decimales)
        multiple = m.group("multiple")
        if multiple:
            valeur *= MULTIPLES[multiple.split()[0].lower()]
        resultat.append((m.group(0).strip(), valeur))
    return resultat


def nombres_des_donnees(valeur) -> set[float]:
    """Tous les nombres d'une valeur JSON (booléens exclus), en valeur absolue."""
    if isinstance(valeur, bool):
        return set()
    if isinstance(valeur, (int, float)):
        return {abs(float(valeur))}
    if isinstance(valeur, dict):
        valeur = list(valeur.values())
    if isinstance(valeur, list):
        return set().union(*(nombres_des_donnees(v) for v in valeur)) if valeur else set()
    return set()


def montants_autorises(donnees: dict) -> list[float]:
    nombres = nombres_des_donnees(donnees) | set(map(float, MONTANTS_REGLEMENTAIRES))
    return sorted({x for n in nombres for x in (n, n * 12, n / 12) if x > 0})


def montant_connu(valeur: float, autorises: list[float]) -> bool:
    return any(abs(valeur - a) <= max(1.0, TOLERANCE_MONTANT * a) for a in autorises)


CHAMPS_LEVIER = {"titre": "titre de levier", "constat": "constat de levier", "gain_attendu": "gain attendu",
                 "indicateur_suivi": "indicateur de suivi"}


def _textes(sortie: dict):
    """(chemin du champ, genre de texte (clé de MOTS_MAX), texte) de chaque texte de la sortie."""
    for i, p in enumerate(sortie["synthese_executive"], start=1):
        yield f"synthese_executive[{i}]", "paragraphe de la synthèse", p
    for i, p in enumerate(sortie["points_cles"], start=1):
        yield f"points_cles[{i}]", "point clé", p
    yield "commentaire_perte", "commentaire de la perte", sortie["commentaire_perte"]
    for c in sortie["commentaires_indicateurs"]:
        yield f"commentaires_indicateurs[{c['cle']}]", "commentaire d'indicateur", c["commentaire"]
    for i, levier in enumerate(sortie["leviers"], start=1):
        for champ, genre in CHAMPS_LEVIER.items():
            yield f"leviers[{i}].{champ}", genre, levier[champ]
        for j, action in enumerate(levier["actions"], start=1):
            yield f"leviers[{i}].actions[{j}]", "action", action
    yield "message_conclusion", "message de conclusion", sortie["message_conclusion"]


def _nettoyer(sortie: dict) -> dict:
    return {
        "synthese_executive": [p.strip() for p in sortie["synthese_executive"]],
        "points_cles": [p.strip() for p in sortie["points_cles"]],
        "commentaire_perte": sortie["commentaire_perte"].strip(),
        "commentaires_indicateurs": [
            {"cle": c["cle"].strip(), "commentaire": c["commentaire"].strip()} for c in sortie["commentaires_indicateurs"]
        ],
        "leviers": [
            {k: ([a.strip() for a in v] if k == "actions" else v.strip()) for k, v in levier.items()}
            for levier in sortie["leviers"]
        ],
        "message_conclusion": sortie["message_conclusion"].strip(),
    }


def _nombre(champ: str, liste: list, bornes: tuple[int, int], erreurs: list[str]):
    mini, maxi = bornes
    if not mini <= len(liste) <= maxi:
        erreurs.append(f"{champ} : {len(liste)} élément(s), il en faut de {mini} à {maxi}.")


def valider_rapport(sortie: dict, cles_indicateurs: list[str], donnees: dict) -> tuple[dict | None, list[str]]:
    """
    (rapport corrigé, erreurs) ; rapport None s'il y a des erreurs.
    `sortie` : RapportRedige.model_dump() ; `cles_indicateurs` : clés des indicateurs du cockpit, dans
    l'ordre ; `donnees` : données de l'audit envoyées au LLM (montants autorisés).
    """
    sortie = _nettoyer(sortie)
    erreurs = []

    _nombre("synthese_executive", sortie["synthese_executive"], PARAGRAPHES_SYNTHESE, erreurs)
    _nombre("points_cles", sortie["points_cles"], POINTS_CLES, erreurs)
    if len(sortie["leviers"]) != NB_LEVIERS:
        erreurs.append(f"leviers : {len(sortie['leviers'])} levier(s), il en faut exactement {NB_LEVIERS}.")
    for i, levier in enumerate(sortie["leviers"], start=1):
        _nombre(f"leviers[{i}].actions", levier["actions"], ACTIONS_PAR_LEVIER, erreurs)

    vus = []
    for c in sortie["commentaires_indicateurs"]:
        if c["cle"] not in cles_indicateurs:
            erreurs.append(f"commentaires_indicateurs : « {c['cle']} » n'est pas un indicateur du cockpit "
                           f"(clés possibles : {', '.join(cles_indicateurs)}).")
        elif c["cle"] in vus:
            erreurs.append(f"commentaires_indicateurs : indicateur « {c['cle']} » commenté deux fois.")
        vus.append(c["cle"])
    manquants = [cle for cle in cles_indicateurs if cle not in vus]
    if manquants:
        erreurs.append(f"commentaires_indicateurs : indicateur(s) sans commentaire : {', '.join(manquants)}.")

    autorises = montants_autorises(donnees)
    cles = cles_techniques(donnees)
    for champ, genre, texte in _textes(sortie):
        if not texte:
            erreurs.append(f"{champ} : texte vide.")
            continue
        mots = len(texte.split())
        if mots > MOTS_MAX[genre]:
            erreurs.append(f"{champ} : {mots} mots, {MOTS_MAX[genre]} au plus (le rapport doit tenir en 12 pages) : "
                           "raccourcir sans perdre les chiffres.")
        for motif, consigne in MENTIONS_INTERDITES.items():
            trouve = motif.search(texte)
            if trouve:
                erreurs.append(f"{champ} : « {trouve.group(0)} » : {consigne}.")
        for cle in sorted(cles):
            if re.search(rf"\b{re.escape(cle)}\b", texte):
                erreurs.append(f"{champ} : clé technique « {cle} » : la remplacer par le libellé de la donnée, "
                               "en français courant.")
        for cite, valeur in montants_cites(texte):
            if not montant_connu(valeur, autorises):
                erreurs.append(f"{champ} : montant « {cite} » absent des données de l'audit. Ne citer que des "
                               "montants présents dans les données, ou décrire l'effet sans montant.")

    if erreurs:
        return None, erreurs
    ordre = {cle: i for i, cle in enumerate(cles_indicateurs)}
    sortie["commentaires_indicateurs"].sort(key=lambda c: ordre[c["cle"]])
    return sortie, []
