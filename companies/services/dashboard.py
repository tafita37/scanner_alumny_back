"""
Tableau de bord : compteurs, KPI, répartition par secteur, audits à traiter et tableau des dossiers,
calculés à chaque appel sur tous les audits (rien n'est enregistré, aucun appel au LLM).

- Statut et étape d'un audit : déduits de `remaining_step` (étape = 6 − remaining_step ;
  0 = rapport généré), comme côté front (`dossierDepuisApi`).
- Perte annuelle et score de santé : cockpit de l'audit (`compute_cockpit`), ignorés si le secteur
  n'a pas de moteur de calcul.
- Dernière activité : date la plus récente parmi la création de l'audit, le dépôt de ses documents,
  leurs extractions, le lancement des tours du questionnaire, les réponses aux questions et la
  génération du rapport.
"""
from django.db.models import Count, F, Max
from django.utils import timezone

from ..metier.question import StatutQuestion
from ..metier.questionnaire import StatutQuestionnaire
from ..metier.extraction import StatutExtraction
from ..metier.report import StatutRapport
from ..models import Audit, Extraction, Industry, Question, Questionnaire, Report
from .cockpit import UnsupportedSectorError, compute_cockpit
from .indicators import compute_indicators

NB_ETAPES = 5
A_TRAITER_MAX = 5

DOCUMENTS_EN_ATTENTE = 'documents_en_attente'
EN_COURS_ANALYSE = 'en_cours_analyse'
ANALYSE = 'analyse'
RAPPORT_GENERE = 'rapport_genere'

DOCUMENTS_MANQUANTS = 'documents_manquants'
EXTRACTION_A_VERIFIER = 'extraction_a_verifier'
QUESTIONS_EN_ATTENTE = 'questions_en_attente'
RAPPORT_A_GENERER = 'rapport_a_generer'
RAPPORT_EN_ERREUR = 'rapport_en_erreur'


def audit_step(remaining_step: int) -> int:
    """Étape à rouvrir (1 à 5) : 6 − remaining_step, la dernière si l'audit est terminé."""
    if remaining_step <= 0:
        return NB_ETAPES
    return max(1, NB_ETAPES + 1 - remaining_step)


def audit_status(remaining_step: int) -> str:
    if remaining_step <= 0:
        return RAPPORT_GENERE
    step = audit_step(remaining_step)
    if step <= 2:
        return DOCUMENTS_EN_ATTENTE
    if step == 3:
        return EN_COURS_ANALYSE
    return ANALYSE


def pending_reason(remaining_step: int, report_status: str | None, nb_documents: int,
                   nb_to_check: int, nb_pending_questions: int) -> tuple[str, int | None] | None:
    """
    Ce qui attend le consultant sur cet audit, selon l'étape où il en est : (motif, nb) ou None.
    `report_status` : statut du rapport (None s'il n'a jamais été lancé) ; `nb_to_check` : documents
    dont la dernière extraction est « à vérifier » ; `nb_pending_questions` : questions en attente.
    """
    if report_status == StatutRapport.ERREUR:
        return RAPPORT_EN_ERREUR, None
    if remaining_step <= 0:
        return None
    step = audit_step(remaining_step)
    if step <= 2:
        if nb_documents == 0:
            return DOCUMENTS_MANQUANTS, None
        if nb_to_check:
            return EXTRACTION_A_VERIFIER, nb_to_check
    elif step == 3:
        if nb_pending_questions:
            return QUESTIONS_EN_ATTENTE, nb_pending_questions
    elif step == NB_ETAPES and report_status != StatutRapport.EN_COURS:
        return RAPPORT_A_GENERER, None
    return None


def _report(audit) -> Report | None:
    try:
        return audit.report
    except Report.DoesNotExist:
        return None


def _local_date(value):
    """Date d'un datetime ; `report.generated_at` revient naïf (colonne SQL `TIMESTAMP` sans fuseau)."""
    if value is None:
        return None
    if timezone.is_naive(value):
        return value.date()
    return timezone.localtime(value).date()


def _latest_extractions_by_audit() -> dict:
    """{audit_id: {document_id: dernière extraction}}, en une requête (sans le texte des pages)."""
    extractions = (
        Extraction.objects
        .defer('json_pages')
        .annotate(audit_ref=F('document__audit_id'))
        .order_by('id')
    )
    by_audit = {}
    for extraction in extractions:
        by_audit.setdefault(extraction.audit_ref, {})[extraction.document_id] = extraction
    return by_audit


def _pending_questions_by_audit() -> dict:
    """{audit_id: nombre de questions en attente dans les tours « ok » du questionnaire}."""
    rows = (
        Question.objects
        .filter(questionnaire__status=StatutQuestionnaire.OK, status=StatutQuestion.EN_ATTENTE)
        .values('questionnaire__audit_id')
        .annotate(nb=Count('id'))
    )
    return {row['questionnaire__audit_id']: row['nb'] for row in rows}


def _last_dates_by_audit(queryset, audit_field: str, date_field: str) -> dict:
    """{audit_id: date la plus récente de `date_field`} (les dates vides sont ignorées)."""
    rows = queryset.filter(**{f'{date_field}__isnull': False}).values(audit_field).annotate(last=Max(date_field))
    return {row[audit_field]: row['last'] for row in rows}


def _loss_and_score(audit, latest: dict) -> tuple[dict | None, int | float | None]:
    """(perte annuelle du cockpit, score de santé) ; (None, None) si le secteur n'a pas de moteur."""
    try:
        cockpit = compute_cockpit(audit, compute_indicators(audit, latest))
    except UnsupportedSectorError:
        return None, None
    return cockpit['perte_annuelle'], cockpit['score_sante']


def _sector_breakdown() -> list[dict]:
    """Tous les secteurs, même sans audit, du plus fourni au moins fourni."""
    industries = Industry.objects.annotate(nb=Count('companies__audits')).order_by('-nb', 'name')
    return [{'secteur': industry.name, 'nb': industry.nb} for industry in industries]


def _average_delay(audits_with_report: list[tuple]) -> dict:
    """Moyenne, en jours, de (génération du rapport − date d'audit) : [(audit_date, generated_at)]."""
    delays = [(_local_date(generated_at) - audit_date).days for audit_date, generated_at in audits_with_report]
    return {
        'valeur': round(sum(delays) / len(delays), 1) if delays else None,
        'nb_audits': len(delays),
    }


def compute_dashboard() -> dict:
    """Tableau de bord (format commenté au-dessus de `getDashboard` dans le front)."""
    audits = list(
        Audit.objects
        .select_related('company__industry', 'report')
        .annotate(nb_documents=Count('documents'), last_document=Max('documents__created_at'))
    )
    extractions = _latest_extractions_by_audit()
    pending_questions = _pending_questions_by_audit()
    last_rounds = _last_dates_by_audit(Questionnaire.objects, 'audit_id', 'created_at')
    last_answers = _last_dates_by_audit(Question.objects, 'questionnaire__audit_id', 'answered_at')

    dossiers, to_handle, losses, reports = [], [], [], []
    for audit in audits:
        latest = extractions.get(audit.id, {})
        report = _report(audit)
        loss, score = _loss_and_score(audit, latest)
        if loss is not None and loss['valeur'] is not None:
            losses.append(loss)
        if report is not None and report.generated_at is not None:
            reports.append((audit.audit_date, report.generated_at))

        last_activity = max(
            date for date in (
                audit.audit_date,
                audit.last_document,
                max((e.extraction_date for e in latest.values()), default=None),
                last_rounds.get(audit.id),
                last_answers.get(audit.id),
                _local_date(report.generated_at) if report is not None else None,
            ) if date is not None
        )
        reason = pending_reason(
            audit.remaining_step,
            report.status if report is not None else None,
            audit.nb_documents,
            sum(1 for e in latest.values() if e.status == StatutExtraction.A_VERIFIER),
            pending_questions.get(audit.id, 0),
        )
        if reason is not None:
            to_handle.append({
                'audit_id': audit.id,
                'company_name': audit.company.company_name,
                'motif': reason[0],
                'nb': reason[1],
                'depuis': last_activity,
            })
        dossiers.append({
            'audit_id': audit.id,
            'siret_number': audit.siret_number,
            'company_name': audit.company.company_name,
            'secteur': audit.company.industry.name,
            'statut': audit_status(audit.remaining_step),
            'etape': audit_step(audit.remaining_step),
            'perte_annuelle': loss['valeur'] if loss is not None else None,
            'perte_partielle': loss['partielle'] if loss is not None and loss['valeur'] is not None else False,
            'score_sante': score,
            'derniere_activite': last_activity,
        })

    # Le plus urgent d'abord : ce qui attend depuis le plus longtemps.
    to_handle.sort(key=lambda item: (item['depuis'], item['audit_id']))
    dossiers.sort(key=lambda item: (item['derniere_activite'], item['audit_id']), reverse=True)

    return {
        'date': timezone.localdate(),
        'compteurs': {
            'total': len(audits),
            'actifs': sum(1 for audit in audits if audit.remaining_step > 0),
            'a_traiter': len(to_handle),
            'en_analyse': sum(1 for d in dossiers if d['statut'] == EN_COURS_ANALYSE),
            'rapports_a_generer': sum(
                1 for item in to_handle if item['motif'] in (RAPPORT_A_GENERER, RAPPORT_EN_ERREUR)
            ),
        },
        'kpis': {
            'perte_cumulee': {
                'valeur': round(sum(loss['valeur'] for loss in losses), 2) if losses else None,
                'nb_audits': len(losses),
                'partielle': any(loss['partielle'] for loss in losses),
            },
            'score_moyen': None,  # pas de formule du score de santé pour l'instant
            'delai_moyen_jours': _average_delay(reports),
        },
        'repartition_secteurs': _sector_breakdown(),
        'a_traiter': to_handle[:A_TRAITER_MAX],
        'dossiers': dossiers,
    }
