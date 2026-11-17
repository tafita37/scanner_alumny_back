from typing import TypedDict


class EtatQuestionnaire(TypedDict):
    contexte: dict                        # contexte de l'audit, DÉJÀ masqué (read_audit_context)
    questions_precedentes: list[dict]     # tours précédents, réponses DÉJÀ anonymisées (read_previous_questions)
    messages: list                        # historique de l'enquête : message initial, appels et résultats
                                          # des tools, conclusions ; repris par la rédaction
    appels_tools: list[dict]              # {tool, arguments} de chaque appel, dans l'ordre (trace, évaluation)
    essais_redaction: int
    sortie_brute: dict | None             # dernière réponse de la rédaction
    erreurs_a_corriger: list[str]         # erreurs de la dernière rédaction, renvoyées au LLM
    erreurs: list[str]                    # historique complet
    resultat: dict | None                 # {analyse, questions} validé ; questions vides : questionnaire terminé
    tokens_entree: int
    tokens_sortie: int
    statut: str                           # en_cours / ok / erreur
