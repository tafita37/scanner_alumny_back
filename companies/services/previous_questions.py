"""
Questions déjà posées lors des tours précédents du questionnaire adaptatif d'un audit, avec
leurs réponses : c'est ce qui permet au LLM de ne pas reposer une question, de creuser une
réponse et de juger s'il reste quelque chose d'important à demander.

Tout ce qui est enregistré en clair et peut contenir des noms est masqué avant d'être renvoyé
au LLM, comme le contexte et le texte des documents :
- les textes rédigés par le LLM (analyse, question, justification, source de la réponse proposée) :
  ils sont enregistrés avec les vrais noms (jetons dé-anonymisés et alias des parties remplacés
  par les noms), et peuvent citer une personne trouvée dans un document ;
- les réponses en texte libre (« mon client M. Dupont paie en retard ») et les choix (options
  rédigées par le LLM), réponse proposée comme réponse du dirigeant.
Masquer : remettre les alias des parties (PARTIE_1...) à la place de leurs noms, puis anonymiser
(jetons <PERSON_1>...). Les montants, pourcentages, nombres, dates et oui/non sont renvoyés tels quels.
Une proposition suivie d'une réponse différente indique au LLM que l'utilisateur l'a corrigée.

Ces questions sont placées par le code dans le message initial de l'agent du questionnaire :
l'agent en a toujours besoin, ce n'est donc pas un tool (il coûterait un appel au LLM de plus à
chaque tour).
"""
import json

from django.db.models import Prefetch

from ..models import Question, Questionnaire
from ..metier.question import TypeReponse
from ..metier.questionnaire import StatutQuestionnaire
from .anonymization import TOKEN_PATTERN, PseudonymMapping, anonymize_text
from .audit_context import ALIAS_PATTERN, PartyAliases

# Réponses qui sont du texte, donc susceptibles de contenir des noms
TEXT_ANSWER_TYPES = (TypeReponse.TEXTE, TypeReponse.CHOIX)


class TextMasker:
    """Masque un texte enregistré avant de l'envoyer au LLM : alias des parties, puis anonymisation."""

    def __init__(self, mapping: PseudonymMapping, aliases: PartyAliases | None = None):
        self.mapping = mapping
        self.aliases = aliases

    def mask(self, text: str | None) -> str | None:
        if not isinstance(text, str) or not text.strip():
            return text
        if self.aliases is not None:
            text = self.aliases.mask(text)
        # Presidio peut prendre un alias pour un nom de personne (« PARTIE_1 paie en retard ») :
        # un jeton qui ne couvre qu'un alias est remis en alias.
        return TOKEN_PATTERN.sub(self.keep_alias, anonymize_text(text, self.mapping))

    def keep_alias(self, match) -> str:
        value = self.mapping.values.get(match.group(0), '')
        return value if ALIAS_PATTERN.fullmatch(value) else match.group(0)

    def answer(self, question: Question, raw: str | None):
        """
        Réponse ou réponse proposée de la question (`raw` : valeur JSON enregistrée), décodée et
        masquée si c'est du texte.
        """
        if raw is None:
            return None
        answer = json.loads(raw)
        if question.answer_type in TEXT_ANSWER_TYPES and isinstance(answer, str):
            return self.mask(answer)
        return answer


def read_previous_questions(audit_id: int, mapping: PseudonymMapping,
                            aliases: PartyAliases | None = None) -> list[dict]:
    """
    Tours déjà générés (statut « ok ») de l'audit, du premier au dernier, avec leurs questions.
    Un tour en cours de génération ou en erreur n'est pas renvoyé.
    `mapping` reçoit les jetons des données personnelles trouvées : l'appelant le garde pour
    remettre les vraies valeurs dans la sortie du LLM (`deanonymize`). Une seule correspondance pour
    tous les tours : une même personne reçoit le même jeton partout.
    `aliases` : ceux du contexte de l'audit (`read_audit_context_with_aliases`), pour qu'une partie
    porte le même alias dans le contexte et dans les questions précédentes.
    """
    masker = TextMasker(mapping, aliases)
    questionnaires = (
        Questionnaire.objects
        .filter(audit_id=audit_id, status=StatutQuestionnaire.OK)
        .order_by('round_number')
        .prefetch_related(Prefetch('questions', queryset=Question.objects.order_by('display_order')))
    )
    return [
        {
            'tour': questionnaire.round_number,
            'analyse': masker.mask(questionnaire.analysis),
            'questions': [
                {
                    'question': masker.mask(question.label),
                    'justification': masker.mask(question.rationale),
                    'type_reponse': question.answer_type,
                    'unite': question.unit,
                    'statut': question.status,
                    'reponse_proposee': masker.answer(question, question.suggested_answer),
                    'source_reponse_proposee': masker.mask(question.suggested_answer_source),
                    'reponse': masker.answer(question, question.answer),
                }
                for question in questionnaire.questions.all()
            ],
        }
        for questionnaire in questionnaires
    ]
