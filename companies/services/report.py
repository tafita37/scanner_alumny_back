"""
Génération du rapport PDF d'un audit (10 à 12 pages, remis au client), une fois le questionnaire
terminé. Une seule version est conservée par audit : une régénération remplace la précédente.

Déroulé de `generate_report` :
1. Vérifications et passage du rapport « en_cours », sous verrou de l'audit (`prepare_report`) :
   deux demandes simultanées ne génèrent pas deux rapports.
2. Données de l'audit, masquées pour le LLM comme pour le questionnaire (alias des parties, jetons
   des données personnelles) : entreprise, données publiées, indicateurs, cockpit et questions des
   tours précédents (`read_report_data`).
3. Rédaction des textes par le LLM (`rapport.redaction`) : synthèse exécutive, commentaires, 3 leviers
   à 30 jours, conclusion. Long, donc hors de toute transaction.
4. Les vrais noms sont remis dans les textes, le PDF est mis en page (`report_pdf`, chiffres du
   cockpit en clair) et écrit dans UPLOAD_DIR/reports ; la ligne est mise à jour, puis l'ancien PDF
   supprimé.
Si la génération échoue, la version précédente (texte et PDF) reste disponible ; `errors` dit pourquoi.
Un rapport resté « en_cours » (serveur arrêté pendant la génération) bloque l'audit : le passer en
« erreur » à la main pour le relancer.
"""
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from rapport.redaction import rediger_rapport

from ..models import Audit, Question, Report
from ..metier.question import StatutQuestion
from ..metier.questionnaire import StatutQuestionnaire
from ..metier.report import StatutRapport
from .anonymization import PseudonymMapping, deanonymize
from .audit_context import read_audit_context_with_aliases
from .cockpit import askable_entries, compute_cockpit
from .previous_questions import read_previous_questions
from .questionnaire import is_finished
from .report_pdf import build_report_context, render_report_pdf
from .structuring import to_json

REPORTS_SUBDIR = 'reports'


class ReportError(Exception):
    """Le rapport ne peut pas être généré ; le message est destiné à l'utilisateur."""


def report_dir() -> Path:
    return Path(settings.UPLOAD_DIR) / REPORTS_SUBDIR


def report_path(report: Report) -> Path | None:
    return report_dir() / report.stored_name if report.stored_name else None


def prepare_report(audit_id: int) -> Report:
    """
    Vérifie que le rapport peut être généré et renvoie sa ligne au statut « en_cours » (créée au
    premier rapport de l'audit).
    Lève ReportError (lien Calendly non configuré, questionnaire non terminé, génération déjà en
    cours), UnsupportedSectorError (secteur sans moteur de calcul) ou Audit.DoesNotExist.
    """
    if not settings.CALENDLY_URL:
        raise ReportError("Le lien Calendly de l'appel à l'action n'est pas configuré (variable CALENDLY_URL).")
    with transaction.atomic():
        audit = Audit.objects.select_related('company__industry').select_for_update(of=('self',)).get(pk=audit_id)
        compute_cockpit(audit)  # lève UnsupportedSectorError
        rounds = list(audit.questionnaires.order_by('round_number').prefetch_related(
            Prefetch('questions', queryset=Question.objects.only('id', 'questionnaire_id'))
        ))
        if not is_finished(rounds, askable_entries(audit)):
            raise ReportError(
                "Le questionnaire de l'audit n'est pas terminé : le rapport est généré une fois le dernier tour passé."
            )

        report = Report.objects.filter(audit=audit).first()
        if report is None:
            return Report.objects.create(audit=audit, status=StatutRapport.EN_COURS)
        if report.status == StatutRapport.EN_COURS:
            raise ReportError('Le rapport de cet audit est déjà en cours de génération.')
        report.status = StatutRapport.EN_COURS
        report.errors = None
        report.save(update_fields=['status', 'errors'])
        return report


def read_report_data(audit_id: int, mapping: PseudonymMapping):
    """
    (audit, données pour le LLM, alias des parties). Les données sont masquées : contexte de l'audit
    (`read_audit_context_with_aliases`, dont seuls l'entreprise, les données publiées et les
    indicateurs sont repris : les extractions des documents ont déjà servi au questionnaire),
    cockpit (aucune donnée personnelle) et questions précédentes masquées avec les mêmes alias.
    """
    context, aliases = read_audit_context_with_aliases(audit_id)
    audit = Audit.objects.select_related('company__industry', 'company__city', 'company__company_type').get(pk=audit_id)
    company = audit.company
    data = {
        'entreprise': {
            'raison_sociale': company.company_name,
            'secteur': context['secteur'],
            'code_naf': company.naf_code,
            'forme_juridique': company.company_type.label,
            'commune': company.city.name,
            'date_creation': company.creation_date.isoformat(),
            'date_audit': context['date_audit'],
        },
        'donnees_publiees': context['donnees_publiees'],
        'indicateurs_documents': context['indicateurs'],
        'cockpit': compute_cockpit(audit, context['indicateurs']),
        'questionnaire': read_previous_questions(audit_id, mapping, aliases),
    }
    return audit, data, aliases


def read_answered_questions(audit) -> list[dict]:
    """Questions répondues ou ignorées des tours « ok », en clair, dans l'ordre des tours (page des réponses)."""
    return list(
        Question.objects
        .filter(questionnaire__audit=audit, questionnaire__status=StatutQuestionnaire.OK,
                status__in=[StatutQuestion.REPONDUE, StatutQuestion.IGNOREE])
        .order_by('questionnaire__round_number', 'display_order')
        .values('label', 'answer_type', 'unit', 'status', 'answer', 'variable')
    )


def render_pdf(audit, data: dict, content: dict) -> tuple[bytes, int]:
    """(PDF, nombre de pages) du rapport : `data` de `read_report_data`, `content` noms remis."""
    company = audit.company
    context = build_report_context(
        company={
            'name': company.company_name,
            'siren': company.siren_number,
            'siret': audit.siret_number,
            'naf': company.naf_code,
            'legal_form': company.company_type.label,
            'city': company.city.name,
            'creation_date': company.creation_date,
            'sector': company.industry.name,
        },
        published=data['donnees_publiees'],
        indicators=data['indicateurs_documents'],
        cockpit=data['cockpit'],
        content=content,
        questions=read_answered_questions(audit),
        calendly_url=settings.CALENDLY_URL,
        audit_date=audit.audit_date,
        generated_on=timezone.localdate(),
    )
    return render_report_pdf(context)


def store_pdf(pdf: bytes) -> str:
    """Écrit le PDF dans UPLOAD_DIR/reports sous un nom unique ; renvoie ce nom."""
    report_dir().mkdir(parents=True, exist_ok=True)
    stored_name = uuid.uuid4().hex + '.pdf'
    (report_dir() / stored_name).write_bytes(pdf)
    return stored_name


def generate_report(audit_id: int) -> Report:
    """
    Génère le rapport PDF de l'audit et l'enregistre. Le rapport renvoyé est « ok » (nouvelle version
    enregistrée) ou « erreur » (`errors` dit pourquoi ; la version précédente reste en place).
    Lève ReportError, UnsupportedSectorError ou Audit.DoesNotExist si le rapport ne peut pas être
    généré ; une erreur inattendue passe le rapport en « erreur » puis est relevée.
    """
    report = prepare_report(audit_id)
    try:
        mapping = PseudonymMapping()
        audit, data, aliases = read_report_data(audit_id, mapping)
        state = rediger_rapport(data)
        report.input_tokens = state['tokens_entree']
        report.output_tokens = state['tokens_sortie']
        if state['statut'] != 'ok':
            report.status = StatutRapport.ERREUR
            report.errors = to_json(aliases.restore(deanonymize(state['erreurs'], mapping)))
            report.save(update_fields=['status', 'errors', 'input_tokens', 'output_tokens'])
            return report

        content = aliases.restore(deanonymize(state['resultat'], mapping))
        pdf, page_count = render_pdf(audit, data, content)
        previous_path = report_path(report)
        stored_name = store_pdf(pdf)
        try:
            report.content = to_json(content)
            report.stored_name = stored_name
            report.page_count = page_count
            report.status = StatutRapport.OK
            report.errors = None
            report.generated_at = timezone.now()
            report.save()
        except Exception:
            (report_dir() / stored_name).unlink(missing_ok=True)
            raise
        if previous_path is not None:
            previous_path.unlink(missing_ok=True)
        return report
    except Exception as exc:
        # Erreur inattendue : le rapport ne doit pas rester « en_cours », sinon il bloque l'audit.
        report.status = StatutRapport.ERREUR
        report.errors = to_json([f'Erreur inattendue : {type(exc).__name__}: {exc}'])
        report.save(update_fields=['status', 'errors', 'input_tokens', 'output_tokens'])
        raise
