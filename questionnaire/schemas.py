"""Schéma de sortie de la rédaction : les questions d'un tour, mises au format par le LLM.

Compatible avec le mode strict de Groq (Structured Outputs), comme `structuration.schemas` :
- extra="forbid" -> "additionalProperties": false
- aucun champ n'a de valeur par défaut -> tous les champs sont "required"
- une valeur absente est représentée par null (type X | None)

La réponse proposée est un texte : le LLM ne peut pas choisir son type (nombre, booléen...) selon
la question en mode strict. La validation (validation.py) la convertit selon `answer_type`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TYPES_REPONSE = ("montant", "pourcentage", "nombre", "date", "oui_non", "choix", "texte")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionGeneree(Strict):
    label: str = Field(description="La question, courte, adressée au dirigeant. Une seule information demandée.")
    rationale: str = Field(
        description="Pourquoi la poser : la perte financière visée et le constat qui y mène (chiffres, document, page)."
    )
    answer_type: Literal[TYPES_REPONSE] = Field(
        description="Forme de la réponse attendue : montant (en euros), pourcentage, nombre, date, oui_non, "
                    "choix (une option parmi 'choices') ou texte (réponse libre, seulement si aucun autre type ne convient)."
    )
    choices: list[str] | None = Field(description="Options proposées si answer_type = choix (au moins 2), sinon null.")
    unit: str | None = Field(description="Unité de la réponse (€, %, jours, mois, heures...), null si sans objet.")
    document_ids: list[int] = Field(description="Identifiants des documents de l'audit qui ont motivé la question ; [] si aucun.")
    suggested_answer: str | None = Field(
        description="Réponse que les documents donnent déjà, à faire confirmer par le dirigeant ; null si les documents "
                    "ne la donnent pas. Montant, pourcentage ou nombre : chiffres seuls (14, 340000.50). Date : AAAA-MM-JJ. "
                    "oui_non : oui ou non. choix : une des options, recopiée telle quelle."
    )
    suggested_answer_source: str | None = Field(
        description="D'où vient la réponse proposée : document, page et passage cité. null si pas de réponse proposée."
    )


class QuestionsGenerees(Strict):
    analyse: str = Field(
        description="Synthèse de l'enquête : pertes repérées ou soupçonnées, chiffres à l'appui, et ce qu'il manque pour les "
                    "chiffrer. Si plus aucune question n'est utile : pourquoi le questionnaire peut s'arrêter."
    )
    questions: list[QuestionGeneree] = Field(
        description="Questions du tour, de la plus importante (perte la plus lourde) à la moins importante. "
                    "Liste vide : le questionnaire est terminé."
    )
