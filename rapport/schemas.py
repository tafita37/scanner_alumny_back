"""Schéma de sortie de la rédaction du rapport : les textes du rapport PDF rédigés par le LLM.

Compatible avec le mode strict des Structured Outputs, comme `questionnaire.schemas` :
- extra="forbid" -> "additionalProperties": false
- aucun champ n'a de valeur par défaut -> tous les champs sont "required"

Le LLM ne rédige que des textes : les chiffres affichés dans les tableaux et graphiques du rapport
(perte annuelle, indicateurs, entrées) sont mis en page par le code, à partir du cockpit.
"""

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommentaireIndicateur(Strict):
    cle: str = Field(description="Clé de l'indicateur du cockpit commenté (cockpit.indicateurs[].cle), recopiée telle quelle.")
    commentaire: str = Field(
        description="Deux à trois phrases pour le dirigeant : ce que l'indicateur mesure, ce que montre sa valeur "
                    "ou, s'il n'est pas chiffré, ce qu'il manque pour le chiffrer."
    )


class Levier(Strict):
    titre: str = Field(description="Titre court et actif du levier (ex. « Facturer les heures hors forfait »).")
    constat: str = Field(description="Ce que l'audit a montré et qui justifie ce levier, chiffres de l'audit à l'appui.")
    actions: list[str] = Field(
        description="Deux à quatre actions concrètes, chacune réalisable par l'entreprise dans les 30 prochains jours, "
                    "dans l'ordre où les mener."
    )
    gain_attendu: str = Field(
        description="Effet attendu du levier. Chiffré seulement avec un montant présent dans les données de l'audit ; "
                    "sinon, effet décrit sans montant."
    )
    indicateur_suivi: str = Field(description="Comment le dirigeant mesure, dans 30 jours, que le levier produit son effet.")


class RapportRedige(Strict):
    synthese_executive: list[str] = Field(
        description="Synthèse exécutive en trois à quatre paragraphes : situation, pertes repérées et chiffrées, "
                    "points non chiffrés, priorités. Un paragraphe par élément de la liste."
    )
    points_cles: list[str] = Field(description="Trois à quatre constats clés, une phrase courte chacun.")
    commentaire_perte: str = Field(
        description="Commentaire de la perte annuelle estimée et de ses composantes (deux à quatre phrases) ; "
                    "dire clairement si elle est partielle et ce qui n'est pas encore chiffré."
    )
    commentaires_indicateurs: list[CommentaireIndicateur] = Field(
        description="Un commentaire par indicateur du cockpit, dans l'ordre du cockpit."
    )
    leviers: list[Levier] = Field(
        description="Exactement trois leviers d'optimisation à mettre en place sous 30 jours, du plus rentable au "
                    "moins rentable."
    )
    message_conclusion: str = Field(
        description="Deux à trois phrases qui invitent le dirigeant à réserver un bilan stratégique avec Alumny pour "
                    "mettre en œuvre les leviers et chiffrer ce qui ne l'est pas encore."
    )
