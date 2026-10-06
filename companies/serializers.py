from rest_framework import serializers

from .models import Audit, Company, CompanyType, Individual, Industry

SIREN_LENGTH = 9
SIRET_LENGTH = 14


def validate_digits(value, length, label):
    value = ''.join(value.split())
    if not value.isdigit() or len(value) != length:
        raise serializers.ValidationError(f'Le {label} doit contenir exactement {length} chiffres.')
    return value


class IndustrySerializer(serializers.ModelSerializer):
    """Champs modifiables d'un secteur (l'unicité du nom est vérifiée automatiquement)."""

    class Meta:
        model = Industry
        fields = ['name', 'description']


class SiretSearchSerializer(serializers.Serializer):
    """
    Début de SIRET saisi par l'utilisateur (les espaces sont ignorés : « 812 456 » = « 812456 »).
    Seuls les 9 premiers chiffres (le SIREN) servent à la recherche : la partie NIC
    d'un SIRET complet est ignorée.
    """

    siret = serializers.CharField(max_length=20)

    def validate_siret(self, value):
        value = ''.join(value.split())
        if not value.isdigit():
            raise serializers.ValidationError('Le SIRET ne doit contenir que des chiffres.')
        if not 3 <= len(value) <= 14:
            raise serializers.ValidationError('Saisis entre 3 et 14 chiffres.')
        return value[:SIREN_LENGTH]


class CeoSaveSerializer(serializers.Serializer):
    """Dirigeant : la personne (nom, prénom) et ses coordonnées pour cette fonction."""

    name = serializers.CharField(max_length=100)
    first_name = serializers.CharField(max_length=100)
    email = serializers.EmailField(max_length=50)
    phone_number = serializers.CharField(max_length=50)
    job_title = serializers.CharField(max_length=50)

    def validate_email(self, value):
        return value.lower()

    def validate(self, data):
        # Une personne est retrouvée par son email : son téléphone ne doit pas
        # déjà appartenir à quelqu'un d'autre (unique en base).
        if Individual.objects.filter(phone_number=data['phone_number']).exclude(email=data['email']).exists():
            raise serializers.ValidationError({'phone_number': 'Ce téléphone appartient déjà à une autre personne.'})
        return data


class CompanySaveSerializer(serializers.Serializer):
    """
    Entreprise de l'audit, retrouvée par son SIREN. Les autres champs ne servent
    (et ne sont obligatoires) que si elle n'est pas encore en base.
    `city` = code INSEE de la commune (créée via geo.api.gouv.fr si inconnue), `company_type` = libellé de la catégorie juridique,
    `industry` = id du secteur (mêmes valeurs que celles renvoyées par la recherche).
    """

    siren_number = serializers.CharField()
    company_name = serializers.CharField(max_length=255, required=False)
    naf_code = serializers.CharField(max_length=6, required=False)
    creation_date = serializers.DateField(required=False)
    industry = serializers.PrimaryKeyRelatedField(
        queryset=Industry.objects.all(), required=False,
        error_messages={'does_not_exist': 'Secteur introuvable.'},
    )
    city = serializers.CharField(min_length=5, max_length=5, required=False)
    company_type = serializers.SlugRelatedField(
        slug_field='label', queryset=CompanyType.objects.all(), required=False,
        error_messages={'does_not_exist': 'Catégorie juridique introuvable.'},
    )

    def validate_siren_number(self, value):
        return validate_digits(value, SIREN_LENGTH, 'SIREN')


class AuditFieldsSerializer(serializers.Serializer):
    """Colonnes de l'audit (un SIRET déjà audité est mis à jour, pas dupliqué)."""

    siret_number = serializers.CharField()
    head_count = serializers.IntegerField(min_value=0)
    revenue = serializers.FloatField()
    profit = serializers.FloatField()
    publication_year = serializers.IntegerField(min_value=1900)

    def validate_siret_number(self, value):
        return validate_digits(value, SIRET_LENGTH, 'SIRET')


class AuditSaveSerializer(serializers.Serializer):
    """Body de l'enregistrement d'un audit : entreprise, dirigeant (facultatif) et audit."""

    company = CompanySaveSerializer()
    ceo = CeoSaveSerializer(required=False)
    audit = AuditFieldsSerializer()

    def validate(self, data):
        company = data['company']
        if not data['audit']['siret_number'].startswith(company['siren_number']):
            raise serializers.ValidationError({'audit': {'siret_number': "Ce SIRET n'appartient pas à cette entreprise."}})
        if not Company.objects.filter(siren_number=company['siren_number']).exists():
            # Nouvelle entreprise : toutes ses colonnes sont obligatoires, dirigeant compris.
            required = ['company_name', 'naf_code', 'industry', 'city', 'company_type']
            missing = {field: 'Obligatoire pour une nouvelle entreprise.' for field in required if field not in company}
            if missing:
                raise serializers.ValidationError({'company': missing})
            if 'ceo' not in data:
                raise serializers.ValidationError({'ceo': 'Obligatoire pour une nouvelle entreprise.'})
        return data


class DocumentUploadSerializer(serializers.Serializer):
    """
    Body (multipart/form-data) de l'upload de documents : les fichiers (champ `files`
    répété une fois par fichier) et l'audit auquel ils sont rattachés.
    """

    files = serializers.ListField(
        child=serializers.FileField(max_length=255, allow_empty_file=False),
        allow_empty=False,
    )
    audit_id = serializers.PrimaryKeyRelatedField(
        queryset=Audit.objects.all(),
        error_messages={'does_not_exist': 'Audit introuvable.'},
    )
