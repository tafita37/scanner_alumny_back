"""
Indicateurs d'un audit : regroupe les extractions de ses documents et les données publiées de
l'audit, puis délègue le calcul à `structuration.indicateurs`. Rien n'est enregistré : les
indicateurs sont recalculés à chaque appel (quelques requêtes SQL, aucun appel au LLM).
"""
import json

from structuration.indicateurs import calculer_indicateurs

from ..models import Extraction
from ..metier.extraction import StatutExtraction


def latest_extractions(audit, with_pages: bool = False) -> dict:
    """
    Dernière extraction de chaque document de l'audit (quel que soit son statut), par id de document.
    `audit` : l'audit ou son identifiant.
    Le texte des pages (`json_pages`) n'est chargé que si `with_pages` : volumineux, il ne sert ni
    aux indicateurs ni au contexte de l'audit, seulement aux tools d'enquête de l'agent.
    """
    extractions = Extraction.objects.filter(document__audit=audit).order_by('id')
    if not with_pages:
        extractions = extractions.defer('json_pages')
    latest = {}
    for extraction in extractions:
        latest[extraction.document_id] = extraction  # la plus récente écrase les précédentes
    return latest


def compute_indicators(audit, latest: dict | None = None) -> dict:
    """
    Indicateurs de l'audit, calculés à partir de la dernière extraction de chacun de ses documents.
    Seules les extractions au statut « ok » sont prises en compte ; les autres sont comptées dans
    `documents_a_verifier`. Un document jamais extrait n'est pas compté.
    `latest` : résultat de `latest_extractions(audit)` s'il a déjà été lu, pour ne pas le relire.
    """
    if latest is None:
        latest = latest_extractions(audit)
    retained = [e for e in latest.values() if e.status == StatutExtraction.OK]
    indicators = calculer_indicateurs(
        audit.company.industry.name.upper(),
        [(json.loads(e.json_extraction), json.loads(e.json_variables)) for e in sorted(retained, key=lambda e: e.id)],
        {
            'chiffre_affaires': audit.revenue,
            'resultat_net': audit.profit,
            'effectif': audit.head_count,
            'annee': audit.publication_year,
            'siren': audit.company.siren_number,
        },
    )
    return {
        'documents_pris_en_compte': len(retained),
        'documents_a_verifier': len(latest) - len(retained),
        **indicators,
    }
