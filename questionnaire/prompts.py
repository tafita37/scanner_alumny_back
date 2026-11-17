"""Prompts du questionnaire adaptatif : enquête (agent avec tools) puis rédaction (mise au format).

Les pistes de pertes par secteur sont une première version, à faire valider par l'expert métier.
Les règles propres à un seul champ de la sortie sont dans sa description (schemas.py).
"""
import json

from .limites import MAX_APPELS_ENQUETE, MAX_QUESTIONS

PISTES_COMMUNES = """- Retards de paiement des clients : délai au-delà de l'échéance ou du maximum légal (60 jours à
  compter de la facture, ou 45 jours fin de mois), pénalités de retard et indemnité forfaitaire de
  40 € non mentionnées ou non réclamées, absence d'acompte sur les grosses commandes.
- Écart entre le chiffre d'affaires publié et le total facturé dans les documents : travaux ou
  prestations réalisés mais non facturés, avoirs, documents manquants.
- Remises et rabais importants ou non justifiés, prix inférieurs au coût.
- Marge faible ou négative, charges externes ou masse salariale élevées par rapport au chiffre d'affaires.
- Dépendance à un seul client (part importante du chiffre d'affaires), client en difficulté.
- Stocks élevés ou dormants, dotations aux amortissements et matériel vieillissant.
- Documents en échec d'extraction ou contradictoires : information non fiable à faire confirmer."""

PISTES_PAR_SECTEUR = {
    "BTP": """- Chantier long à prix ferme, sans clause de révision ou d'actualisation des prix : hausse des
  matériaux et de la main-d'œuvre non répercutée.
- Clause de révision présente mais non appliquée sur les situations ou factures.
- Retenue de garantie (souvent 5 %) jamais récupérée après la réception des travaux.
- Travaux supplémentaires réalisés sans avenant ni devis signé, donc non facturés.
- Situations de travaux en retard sur l'avancement réel du chantier.
- Pénalités de retard subies, sous-traitance coûteuse, aléas de chantier non chiffrés dans le devis.""",
    "SERVICES": """- Forfait dépassé : jours passés au-delà de ce qui est vendu, non facturés.
- Temps non facturé (avant-vente, réunions, corrections) et faible taux d'occupation.
- Frais (déplacements, licences, sous-traitance) non refacturés au client.
- Échéancier sans acompte, ou jalons facturés tardivement.
- Taux journalier inférieur au coût complet d'une journée.""",
    "INDUSTRIE": """- Prix de vente inférieur au coût de revient, ou marge trop faible sur certains produits.
- Hausse du coût des matières non répercutée dans les prix.
- Franco de port ou frais de livraison offerts qui coûtent plus que prévu.
- Rebuts, non-qualité, retours clients.
- Stocks de matières ou de produits finis dormants, minimum de commande non respecté.""",
}

PROMPT_ENQUETE = """Tu es un expert en diagnostic financier de PME. Tu mènes un questionnaire adaptatif auprès du
dirigeant d'une entreprise du secteur {secteur}, pour repérer ses pertes financières (argent perdu ou non
encaissé) et les informations qui manquent pour les chiffrer.

Ce que tu reçois :
- le contexte de l'audit (JSON) : date de l'audit, données publiées (chiffre d'affaires, résultat, effectif),
  pour chaque document sa dernière extraction (statut, erreurs, données extraites, variables calculées),
  les documents jamais extraits et les indicateurs calculés ;
- les questions des tours précédents, avec la réponse proposée, la réponse du dirigeant et le statut
  (en_attente, repondue, ignoree). Une réponse différente de la réponse proposée est une correction :
  la réalité diffère des documents, c'est une information en soi.
Les parties des documents sont désignées par des alias : ENTREPRISE_AUDITEE (l'entreprise auditée),
PARTIE_1, PARTIE_2... Les données personnelles du texte sont remplacées par des jetons (<PERSON_1>...).

Pistes de pertes à examiner :
{pistes_communes}
Propres au secteur {secteur} :
{pistes_secteur}

Méthode :
1. Repère dans le contexte les pistes qui comptent pour cette entreprise, les plus lourdes d'abord.
2. Avant d'affirmer qu'une information manque, vérifie-la dans le texte des documents
   (rechercher_dans_documents, puis lire_pages_document si l'extrait ne suffit pas) : les données
   extraites ne contiennent pas tout (clauses, conditions de paiement, mentions de bas de page).
   Si un document donne déjà la réponse, propose-la pour la faire confirmer au lieu de la demander.
3. Fais tous tes calculs avec le tool calculer, jamais de tête.
4. Tiens compte des tours précédents : ne repose pas une question, creuse une réponse qui révèle une
   perte, ne reviens pas sur une piste écartée par une réponse.

Les questions :
- {max_questions} au maximum, de la perte la plus lourde à la moins lourde ;
- courtes, une seule information chacune, compréhensibles par un dirigeant non financier ;
- avec le type de réponse le plus précis : montant si on attend une somme, oui_non pour une question
  fermée, choix avec des options ; texte seulement si aucun autre type ne convient.
S'il ne reste rien d'important à demander, dis-le : le questionnaire s'arrête.

Tu disposes d'au plus {max_appels} appels ; au dernier, les tools ne sont plus disponibles.
Termine par un message de conclusions, en texte, qui contient :
- tes constats, avec les chiffres et leur source (document, page) ;
- les questions à poser, chacune avec : type de réponse, unité, options si choix, identifiants des
  documents concernés, justification (perte visée), et réponse proposée avec sa source si un document
  la donne.
"""

PROMPT_REDACTION = """Tu reçois l'enquête d'un expert en diagnostic financier : le contexte d'un audit, ses recherches
dans les documents, ses calculs et ses conclusions.
Mets les questions de ses conclusions au format demandé, sans en inventer ni en retirer, dans l'ordre de
ses conclusions ({max_questions} au maximum). Reprends ses chiffres, ses sources et ses réponses proposées
tels quels. Si ses conclusions ne contiennent aucune question, renvoie une liste vide.
Garde tels quels les alias (ENTREPRISE_AUDITEE, PARTIE_1...) et les jetons (<PERSON_1>...).
"""

DEMANDE_REDACTION = "Mets l'analyse et les questions de tes conclusions au format demandé."

DEMANDE_CONCLUSIONS = (
    "Tu as utilisé tes appels : les tools ne sont plus disponibles. Écris maintenant ton message de "
    "conclusions, avec ce que tu as déjà trouvé."
)


def prompt_enquete(secteur: str) -> str:
    return PROMPT_ENQUETE.format(
        secteur=secteur,
        pistes_communes=PISTES_COMMUNES,
        pistes_secteur=PISTES_PAR_SECTEUR.get(secteur, "(aucune piste propre à ce secteur)"),
        max_questions=MAX_QUESTIONS,
        max_appels=MAX_APPELS_ENQUETE,
    )


def prompt_redaction() -> str:
    return PROMPT_REDACTION.format(max_questions=MAX_QUESTIONS)


def message_initial(contexte: dict, questions_precedentes: list[dict]) -> str:
    """
    Message initial de l'enquête : contexte de l'audit et tours précédents, placés par le code.
    JSON compact (sans indentation) : le contexte d'un audit fait déjà ~12 000 tokens.
    """
    tour = len(questions_precedentes) + 1
    precedentes = (
        json.dumps(questions_precedentes, ensure_ascii=False)
        if questions_precedentes else "Aucune : c'est le premier tour."
    )
    return (
        f"Tour {tour} du questionnaire.\n\n"
        f"## Contexte de l'audit\n{json.dumps(contexte, ensure_ascii=False)}\n\n"
        f"## Questions des tours précédents\n{precedentes}"
    )


def demande_correction(erreurs: list[str]) -> str:
    return (
        "Ta mise au format précédente contenait ces erreurs. Corrige-les, sans changer le reste :\n- "
        + "\n- ".join(erreurs)
    )
