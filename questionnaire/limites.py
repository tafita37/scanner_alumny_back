"""Limites d'un tour du questionnaire, citées dans les prompts et vérifiées par le code."""

# Questions par tour : assez pour couvrir les pistes principales, peu pour ne pas lasser le dirigeant.
MAX_QUESTIONS = 8
# Appels au LLM pendant l'enquête (chacun renvoie tout l'historique). Le dernier se fait sans tools :
# l'agent doit alors écrire ses conclusions.
MAX_APPELS_ENQUETE = 8
# Essais de la rédaction : le premier, plus un nouvel essai si la validation trouve des erreurs
# (l'enquête, elle, n'est pas refaite).
MAX_ESSAIS_REDACTION = 2
