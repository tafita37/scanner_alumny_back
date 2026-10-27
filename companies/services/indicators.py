"""
Indicateurs d'un audit : regroupe les extractions de ses documents et les données publiées de
l'audit, puis délègue le calcul à `structuration.indicateurs`. Rien n'est enregistré : les
indicateurs sont recalculés à chaque appel (quelques requêtes SQL, aucun appel au LLM).
"""
import json

from structuration.indicateurs import calculer_indicateurs

from ..models import Extraction
from ..metier.extraction import StatutExtraction


def compute_indicators(audit) -> dict:
    """
    Indicateurs de l'audit, calculés à partir de la dernière extraction de chacun de ses documents.
    Seules les extractions au statut « ok » sont prises en compte ; les autres sont comptées dans
    `documents_a_verifier`. Un document jamais extrait n'est pas compté.
    """
    latest = {}
    for extraction in Extraction.objects.filter(document__audit=audit).order_by('id'):
        latest[extraction.document_id] = extraction  # la plus récente écrase les précédentes
    retained = [e for e in latest.values() if e.status == StatutExtraction.OK]
    indicators = calculer_indicateurs(
        audit.company.industry.name.upper(),
        [(json.loads(e.json_extraction), json.loads(e.json_variables)) for e in sorted(retained, key=lambda e: e.id)],
        {
            'chiffre_affaires': audit.revenue,
            'resultat_net': audit.profit,
            'effectif': audit.head_count,
            'annee': audit.publication_year,
        },
    )
    return {
        'documents_pris_en_compte': len(retained),
        'documents_a_verifier': len(latest) - len(retained),
        **indicators,
    }
