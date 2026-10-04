import os

import requests
from django.db.models import F
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Company, CompanyType
from ..serializers import SiretSearchSerializer

# Nombre maximum de propositions renvoyées à l'autocomplétion.
SEARCH_LIMIT = 5

def fetchSiretSociety(siret, nombre=5) :
    url = "https://api.insee.fr/api-sirene/3.11/siret"
    params={
        "q": "siren:" + siret + "* AND etablissementSiege:true",
        "nombre": nombre,
    }
    headers={"X-INSEE-Api-Key-Integration": os.environ.get("INSEE_API_KEY")}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
    except requests.RequestException:
        # INSEE injoignable : on se contente des résultats de la base.
        return None
    return response.json() if response.status_code == 200 else None


def fetchCompanyAudits(siren, nombre=5) :
    url = "https://recherche-entreprises.api.gouv.fr/search"
    params={
        "q": siren,
        "per_page": nombre,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.RequestException:
        # API Recherche d'entreprises injoignable : pas d'audit.
        return None
    return response.json() if response.status_code == 200 else None


# Tranches d'effectif salarié INSEE -> borne basse de la tranche
# (l'API ne fournit pas l'effectif exact). "NN" = non renseigné.
HEAD_COUNT_BY_TRANCHE = {
    '00': 0, '01': 1, '02': 3, '03': 6, '11': 10, '12': 20, '21': 50, '22': 100,
    '31': 200, '32': 250, '41': 500, '42': 1000, '51': 2000, '52': 5000, '53': 10000,
}


def format_audits(data, siren):
    """
    Met les résultats de l'API Recherche d'entreprises au format du modèle Audit.
    Seuls les résultats dont le SIREN commence par la saisie et qui publient
    un chiffre d'affaires sont gardés ; on prend l'année publiée la plus récente.
    `company_id` vaut None si la société n'est pas encore enregistrée chez nous.
    """
    audits = []
    for result in data.get('results', []):
        if not result.get('siren', '').startswith(siren):
            print('not found')
            continue
        finances = result.get('finances') or {}
        years = [year for year, values in finances.items() if values.get('ca') is not None]
        if not years:
            continue
        year = max(years)
        audits.append({
            'id': None,
            'siret_number': (result.get('siege') or {}).get('siret'),
            'head_count': HEAD_COUNT_BY_TRANCHE.get(result.get('tranche_effectif_salarie')),
            'profit': finances[year]['resultat_net'],
            'revenue': finances[year]['ca'],
            'publication_year': int(year),
        })
    return audits


def department_code_from_insee(code_commune):
    """Département d'une commune à partir de son code INSEE (3 chiffres en outre-mer : 971..976)."""
    if not code_commune:
        return None
    return code_commune[:3] if code_commune.startswith('97') else code_commune[:2]


def format_insee_companies(data, company_type_labels):
    """
    Met les établissements renvoyés par l'INSEE au même format que la recherche en base.
    `id` vaut None : la société n'est pas encore enregistrée chez nous.
    Pour une personne physique (entreprise individuelle), il n'y a pas de dénomination :
    la raison sociale est « Prénom Nom » et cette personne est le dirigeant.
    """
    companies = []
    for etablissement in data.get('etablissements', []):
        unite = etablissement['uniteLegale']
        adresse = etablissement['adresseEtablissement']
        is_individual = not unite.get('denominationUniteLegale')
        first_name = unite.get('prenomUsuelUniteLegale') or unite.get('prenom1UniteLegale')
        last_name = unite.get('nomUsageUniteLegale') or unite.get('nomUniteLegale')
        companies.append({
            'id': None,
            'siren_number': etablissement['siren'],
            'company_name': (
                ' '.join(filter(None, [first_name, last_name])) if is_individual
                else unite['denominationUniteLegale']
            ),
            'naf_code': unite.get('activitePrincipaleUniteLegale'),
            'creation_date': unite.get('dateCreationUniteLegale'),
            'industry_name': None,
            'city_name': adresse.get('libelleCommuneEtablissement'),
            'city_code_insee': adresse.get('codeCommuneEtablissement'),
            'department_code': department_code_from_insee(adresse.get('codeCommuneEtablissement')),
            'company_type_label': company_type_labels.get(unite.get('categorieJuridiqueUniteLegale')),
            'ceo_name': last_name if is_individual else None,
            'ceo_first_name': first_name if is_individual else None,
            'ceo_job_title': None,
        })
    return companies


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_by_siret(request):
    """
    Entreprises dont le SIREN commence par la saisie (?siret=812456).
    Le SIREN étant les 9 premiers chiffres du SIRET, un SIRET complet
    retrouve aussi son entreprise.
    D'abord les sociétés déjà en base, puis on complète jusqu'à SEARCH_LIMIT
    avec celles de l'INSEE (sans les enregistrer).
    """
    serializer = SiretSearchSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    siren = serializer.validated_data['siret']
    companies = list(
        Company.objects
        .filter(siren_number__startswith=siren)
        .order_by('siren_number')
        .values(
            'id', 'siren_number', 'company_name', 'naf_code', 'creation_date',
            industry_name=F('industry__name'),
            city_name=F('city__name'),
            city_code_insee=F('city__code_insee'),
            department_code=F('city__department_code'),
            company_type_label=F('company_type__label'),
            ceo_name=F('ceo_info__individual__name'),
            ceo_first_name=F('ceo_info__individual__first_name'),
            ceo_job_title=F('ceo_info__job_title'),
        )[:SEARCH_LIMIT]
    )
    if len(companies) < SEARCH_LIMIT:
        # L'INSEE renvoie aussi les sociétés déjà en base : on en demande
        # SEARCH_LIMIT et on écarte les doublons.
        data = fetchSiretSociety(siren, SEARCH_LIMIT)
        if data:
            codes = {e['uniteLegale'].get('categorieJuridiqueUniteLegale') for e in data.get('etablissements', [])}
            company_type_labels = dict(CompanyType.objects.filter(code__in=codes).values_list('code', 'label'))
            known_sirens = {company['siren_number'] for company in companies}
            for company in format_insee_companies(data, company_type_labels):
                if len(companies) >= SEARCH_LIMIT:
                    break
                if company['siren_number'] not in known_sirens:
                    companies.append(company)
    return Response(companies, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_audit_informations_by_siren(request, siret) :
    audits = []
    siren= siret[:9]
    data = fetchCompanyAudits(siren, SEARCH_LIMIT)
    audits = format_audits(data, siren)
    return Response(audits[0] if audits else None, status=status.HTTP_200_OK)