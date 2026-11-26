"""
Avancement d'un audit dans ses étapes : `Audit.remaining_step` (étapes restant à faire).
4 à la création (onboarding fait) ; il ne fait que descendre :
- 4 → 3 : tous les documents PDF de l'audit ont été extraits (`ok` ou `a_verifier`) ;
- 3 → 2 : le questionnaire est terminé (l'agent rend un tour sans question) ;
- 2 → 1 : la génération du rapport démarre (résultats du cockpit validés) ;
- 1 → 0 : le rapport est généré.
"""
from django.db.models import Prefetch

from ..metier.extraction import StatutExtraction
from ..models import Audit, Document, Extraction

QUESTIONS = 3
COCKPIT = 2
REPORT = 1
DONE = 0

PDF_MIME_TYPE = 'application/pdf'


def advance_to(audit_id: int, remaining_step: int) -> None:
    """Passe l'audit à `remaining_step` s'il en est avant ; ne le fait jamais reculer."""
    Audit.objects.filter(pk=audit_id, remaining_step__gt=remaining_step).update(remaining_step=remaining_step)


def all_documents_extracted(audit_id: int) -> bool:
    """
    Au moins un document PDF, et la dernière extraction de chacun est terminée (`ok` ou `a_verifier`).
    Les autres fichiers ne comptent pas : seuls les PDF peuvent être extraits.
    """
    documents = (
        Document.objects
        .filter(audit_id=audit_id, mime_type=PDF_MIME_TYPE)
        .only('id')
        .prefetch_related(Prefetch('extractions', queryset=Extraction.objects.only('id', 'status', 'document_id')))
    )
    if not documents:
        return False
    for document in documents:
        latest = max(document.extractions.all(), key=lambda e: e.id, default=None)
        if latest is None or latest.status == StatutExtraction.EN_COURS:
            return False
    return True


def advance_if_documents_extracted(audit_id: int) -> None:
    """4 → 3 quand tous les documents PDF de l'audit ont été extraits."""
    if all_documents_extracted(audit_id):
        advance_to(audit_id, QUESTIONS)
