"""
CRUD générique pour les tables simples (référentiels...).
Pour exposer une nouvelle table : l'ajouter dans CRUD_RESOURCES, les routes
sont générées automatiquement dans urls/crud_urls.py.
"""
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from ..models import Industry
from ..serializers import IndustrySerializer

# Nom de la ressource dans l'URL -> modèle, colonnes renvoyées, serializer de validation.
CRUD_RESOURCES = {
    'industries': {
        'model': Industry,
        'fields': ('id', 'name', 'description'),
        'serializer': IndustrySerializer,
    },
}


def _fetch_one(config, pk):
    """Une ligne au format de la ressource (les colonnes peuvent traverser des FK : 'city__name')."""
    return config['model'].objects.values(*config['fields']).get(pk=pk)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_objects(request, resource):
    config = CRUD_RESOURCES[resource]
    rows = config['model'].objects.values(*config['fields'])
    return Response(list(rows), status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_object(request, resource, pk):
    config = CRUD_RESOURCES[resource]
    row = config['model'].objects.values(*config['fields']).filter(pk=pk).first()
    if row is None:
        return Response({'detail': 'Élément introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(row, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def create_object(request, resource):
    config = CRUD_RESOURCES[resource]
    serializer = config['serializer'](data=request.data)
    serializer.is_valid(raise_exception=True)
    obj = serializer.save()
    return Response(_fetch_one(config, obj.pk), status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_object(request, resource, pk):
    """Modification partielle : seuls les champs envoyés sont modifiés."""
    config = CRUD_RESOURCES[resource]
    obj = get_object_or_404(config['model'], pk=pk)
    serializer = config['serializer'](obj, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(_fetch_one(config, pk), status=status.HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_object(request, resource, pk):
    config = CRUD_RESOURCES[resource]
    obj = get_object_or_404(config['model'], pk=pk)
    try:
        obj.delete()
    except ProtectedError:
        return Response(
            {'detail': 'Suppression impossible : cet élément est encore utilisé.'},
            status=status.HTTP_409_CONFLICT,
        )
    return Response(status=status.HTTP_204_NO_CONTENT)
