from rest_framework import serializers

SIREN_LENGTH = 9


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
