"""
Validation par le code de la sortie de la rédaction : ce que le schéma strict ne garantit pas.

Erreurs (renvoyées au LLM pour un nouvel essai de la rédaction) :
- plus de MAX_QUESTIONS questions ;
- question ou justification vide ;
- question en double dans le tour, ou déjà posée à un tour précédent (même texte, casse, accents et
  ponctuation ignorés) ;
- document qui n'appartient pas à l'audit ;
- type choix sans au moins deux options ;
- réponse proposée qui ne correspond pas au type (« environ 14 » pour un nombre, « peut-être » pour
  oui_non...), ou sans source.
Corrections faites sans erreur (sans conséquence sur le sens) : options retirées d'une question qui
n'est pas un choix, source retirée quand il n'y a pas de réponse proposée, unité par défaut (€ pour
un montant, % pour un pourcentage), documents en double retirés.

La réponse proposée validée est convertie au format JSON de `Question.answer` : nombre pour
montant, pourcentage et nombre, booléen pour oui_non, texte sinon.
"""
import re
import unicodedata
from datetime import date

from .limites import MAX_QUESTIONS

UNITES_PAR_DEFAUT = {"montant": "€", "pourcentage": "%"}
OUI = {"oui", "true", "vrai"}
NON = {"non", "false", "faux"}
# Espaces (dont insécables) et symboles tolérés dans un nombre : « 340 000 € », « 5 % »
CARACTERES_IGNORES_NOMBRE = re.compile(r"[\s  €%]|eur(os?)?$", re.IGNORECASE)
NOMBRE = re.compile(r"-?\d+(\.\d+)?")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def normaliser(texte: str) -> str:
    """Sans accents, casse ni ponctuation, espaces réduits : sert à repérer les doublons."""
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", texte).split())


def convertir_reponse(answer_type: str, valeur: str, choices: list[str] | None):
    """Réponse proposée convertie selon le type de la question. Lève ValueError (message pour le LLM)."""
    valeur = valeur.strip()
    if answer_type in ("montant", "pourcentage", "nombre"):
        texte = CARACTERES_IGNORES_NOMBRE.sub("", valeur).replace(",", ".")
        if not NOMBRE.fullmatch(texte):
            raise ValueError(f"« {valeur} » n'est pas un nombre (chiffres seuls attendus, ex. 340000.50)")
        nombre = float(texte)
        return int(nombre) if nombre.is_integer() else nombre
    if answer_type == "date":
        try:
            if not DATE.fullmatch(valeur):
                raise ValueError
            return date.fromisoformat(valeur).isoformat()
        except ValueError:
            raise ValueError(f"« {valeur} » n'est pas une date au format AAAA-MM-JJ") from None
    if answer_type == "oui_non":
        mot = normaliser(valeur)
        if mot in OUI | NON:
            return mot in OUI
        raise ValueError(f"« {valeur} » n'est ni oui ni non")
    if answer_type == "choix":
        for option in choices or []:
            if normaliser(option) == normaliser(valeur):
                return option
        raise ValueError(f"« {valeur} » ne fait pas partie des options")
    return valeur


def valider_questions(sortie: dict, documents_audit: set[int], questions_precedentes: list[str]) -> tuple[dict, list[str]]:
    """
    (sortie corrigée, erreurs). `sortie` : QuestionsGenerees en dictionnaire.
    `documents_audit` : identifiants des documents de l'audit ; `questions_precedentes` : textes des
    questions des tours précédents.
    """
    erreurs = []
    questions = sortie["questions"]
    if len(questions) > MAX_QUESTIONS:
        erreurs.append(f"{len(questions)} questions : {MAX_QUESTIONS} au maximum. Garde les plus importantes.")

    deja_posees = {normaliser(q) for q in questions_precedentes}
    vues = set()
    corrigees = []
    for numero, question in enumerate(questions, start=1):
        question = dict(question)
        prefixe = f"Question {numero}"
        label, rationale = question["label"].strip(), question["rationale"].strip()
        question["label"], question["rationale"] = label, rationale
        if not label:
            erreurs.append(f"{prefixe} : texte de la question vide.")
        if not rationale:
            erreurs.append(f"{prefixe} : justification vide.")
        cle = normaliser(label)
        if cle and cle in deja_posees:
            erreurs.append(f"{prefixe} : déjà posée à un tour précédent (« {label} »). Remplace-la ou retire-la.")
        elif cle and cle in vues:
            erreurs.append(f"{prefixe} : en double dans ce tour (« {label} »).")
        vues.add(cle)

        answer_type = question["answer_type"]
        if answer_type == "choix":
            options = [o.strip() for o in question["choices"] or [] if o and o.strip()]
            options = list(dict.fromkeys(options))  # sans doublon, dans l'ordre
            if len(options) < 2:
                erreurs.append(f"{prefixe} : type choix sans au moins deux options dans choices.")
            question["choices"] = options
        else:
            question["choices"] = None

        question["unit"] = (question["unit"] or "").strip() or UNITES_PAR_DEFAUT.get(answer_type)

        document_ids = list(dict.fromkeys(question["document_ids"]))
        inconnus = [d for d in document_ids if d not in documents_audit]
        if inconnus:
            erreurs.append(
                f"{prefixe} : documents {inconnus} absents de l'audit "
                f"(documents de l'audit : {sorted(documents_audit)})."
            )
        question["document_ids"] = document_ids

        proposee = (question["suggested_answer"] or "").strip()
        source = (question["suggested_answer_source"] or "").strip()
        if proposee:
            try:
                question["suggested_answer"] = convertir_reponse(answer_type, proposee, question["choices"])
            except ValueError as e:
                erreurs.append(f"{prefixe} : réponse proposée invalide pour le type {answer_type} : {e}.")
            if not source:
                erreurs.append(f"{prefixe} : réponse proposée sans source (document, page, passage).")
            question["suggested_answer_source"] = source or None
        else:
            question["suggested_answer"] = None
            question["suggested_answer_source"] = None
        corrigees.append(question)

    return {"analyse": sortie["analyse"].strip(), "questions": corrigees}, erreurs
