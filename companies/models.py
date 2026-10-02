"""
Point d'entrée des modèles de l'app : Django découvre les modèles via ce fichier.
Chaque métier est défini dans son propre fichier du dossier `metier/`.
"""
from .metier.ceo_info import CeoInfo
from .metier.city import City
from .metier.city_postal_code import CityPostalCode
from .metier.company import Company
from .metier.company_type import CompanyType
from .metier.individual import Individual

__all__ = ['CeoInfo', 'City', 'CityPostalCode', 'Company', 'CompanyType', 'Individual']
