import requests
from django.db import transaction
from django.db.models import F
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Audit, CeoInfo, City, CityPostalCode, Company, Individual
from ..serializers import AuditSaveSerializer


def fetchCity(code_insee) :
    url = "https://geo.api.gouv.fr/communes/" + code_insee
    params={"fields": "nom,code,codeDepartement,codesPostaux"}
    try:
        response = requests.get(url, params=params, timeout=10)
    except requests.RequestException:
        # API Géo injoignable : la commune ne peut pas être créée.
        return None
    return response.json() if response.status_code == 200 else None


def save_city(data):
    """Enregistre une commune renvoyée par l'API Géo, avec ses codes postaux."""
    city = City.objects.create(
        name=data['nom'], code_insee=data['code'], department_code=data['codeDepartement'],
    )
    CityPostalCode.objects.bulk_create(
        CityPostalCode(postal_code=postal_code, city=city) for postal_code in data.get('codesPostaux', [])
    )
    return city


def save_ceo(ceo, company=None):
    """
    Enregistre le dirigeant : la personne est retrouvée par son email (créée sinon).
    Si l'entreprise a déjà cette personne pour dirigeant, ses coordonnées sont mises à jour.
    """
    individual = Individual.objects.filter(email=ceo['email']).first()
    if individual is None:
        individual = Individual.objects.create(
            name=ceo['name'], first_name=ceo['first_name'],
            email=ceo['email'], phone_number=ceo['phone_number'],
        )
    if company is not None and company.ceo_info.individual_id == individual.id:
        ceo_info = company.ceo_info
    else:
        ceo_info = CeoInfo(individual=individual)
    ceo_info.email = ceo['email']
    ceo_info.phone_number = ceo['phone_number']
    ceo_info.job_title = ceo['job_title']
    ceo_info.save()
    return ceo_info


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_audit(request):
    """
    Enregistre un audit :
    - le dirigeant (`ceo`) s'il est fourni ; il devient le dirigeant de l'entreprise ;
    - l'entreprise (`company`) si son SIREN n'est pas encore en base, et sa commune
      si elle n'est pas encore en base (informations récupérées sur l'API Géo) ;
    - l'audit (`audit`), mis à jour si ce SIRET a déjà été audité.
    Tout est enregistré d'un bloc : en cas d'erreur, rien n'est enregistré.
    """
    serializer = AuditSaveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    # Commune inconnue d'une nouvelle entreprise : appel à l'API Géo avant la
    # transaction, pour ne pas la garder ouverte pendant la requête HTTP.
    city_data = None
    code_insee = data['company'].get('city')
    if (
        code_insee
        and not Company.objects.filter(siren_number=data['company']['siren_number']).exists()
        and not City.objects.filter(code_insee=code_insee).exists()
    ):
        city_data = fetchCity(code_insee)
        if city_data is None:
            return Response({'company': {'city': ['Commune introuvable.']}}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        company = (
            Company.objects
            .select_related('ceo_info')
            .filter(siren_number=data['company']['siren_number'])
            .first()
        )
        ceo_info = save_ceo(data['ceo'], company) if 'ceo' in data else None
        if company is None:
            city = save_city(city_data) if city_data else City.objects.get(code_insee=code_insee)
            company = Company.objects.create(**{**data['company'], 'city': city}, ceo_info=ceo_info)
        elif ceo_info is not None and company.ceo_info_id != ceo_info.id:
            company.ceo_info = ceo_info
            company.save(update_fields=['ceo_info'])
        audit = Audit.objects.create(**data['audit'], company=company)
    row = (
        Audit.objects
        .filter(pk=audit.pk)
        .values(
            'id', 'siret_number', 'head_count', 'revenue', 'profit', 'publication_year', 'company_id',
            siren_number=F('company__siren_number'),
            company_name=F('company__company_name'),
            ceo_name=F('company__ceo_info__individual__name'),
            ceo_first_name=F('company__ceo_info__individual__first_name'),
            ceo_job_title=F('company__ceo_info__job_title'),
        )
        .get()
    )
    return Response(row, status=status.HTTP_201_CREATED)
