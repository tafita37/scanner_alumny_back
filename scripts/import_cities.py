"""
Import des communes françaises dans les tables city et city_postal_code
depuis l'API https://geo.api.gouv.fr/communes.

Une ligne city par commune (code INSEE), et une ligne city_postal_code par
code postal de la commune. Le script peut être relancé : les communes sont
mises à jour par code INSEE et leurs codes postaux sont remplacés.

Usage (depuis scanner_alumny_back, avec l'environnement virtuel activé) :
    python scripts/import_cities.py                  # appelle l'API
    python scripts/import_cities.py communes.json    # lit une réponse de l'API déjà enregistrée
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
API_URL = 'https://geo.api.gouv.fr/communes?fields=nom,code,codeDepartement,codesPostaux&format=json'

sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scanner.settings')

import django  # noqa: E402

django.setup()

from django.db import connection, transaction  # noqa: E402

UPSERT_CITY_SQL = """
    INSERT INTO city (name, code_insee, department_code)
    VALUES (%s, %s, %s)
    ON CONFLICT (code_insee) DO UPDATE SET
        name = EXCLUDED.name,
        department_code = EXCLUDED.department_code
    RETURNING id
"""
DELETE_POSTAL_CODES_SQL = 'DELETE FROM city_postal_code WHERE city_id = %s'
INSERT_POSTAL_CODE_SQL = 'INSERT INTO city_postal_code (postal_code, city_id) VALUES (%s, %s)'


def fetch_communes():
    request = urllib.request.Request(API_URL, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def load_communes(file_path):
    with open(file_path, encoding='utf-8-sig') as file:
        return json.load(file)


def main():
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        communes = load_communes(file_path)
        print(f'{len(communes)} communes lues depuis {file_path.name}')
    else:
        communes = fetch_communes()
        print(f'{len(communes)} communes récupérées depuis l\'API')

    # Les collectivités d'outre-mer (ex. Saint-Pierre-et-Miquelon) n'ont pas de département
    skipped = [c['nom'] for c in communes if not c.get('codeDepartement')]
    communes = [c for c in communes if c.get('codeDepartement')]
    if skipped:
        print(f'{len(skipped)} commune(s) sans département ignorée(s) : {", ".join(skipped)}')

    postal_code_count = 0
    with transaction.atomic(), connection.cursor() as cursor:
        for commune in communes:
            cursor.execute(UPSERT_CITY_SQL, (commune['nom'], commune['code'], commune['codeDepartement']))
            city_id = cursor.fetchone()[0]

            postal_codes = sorted(set(commune.get('codesPostaux') or []))
            cursor.execute(DELETE_POSTAL_CODES_SQL, (city_id,))
            cursor.executemany(INSERT_POSTAL_CODE_SQL, [(code, city_id) for code in postal_codes])
            postal_code_count += len(postal_codes)

    print(f'{len(communes)} communes et {postal_code_count} codes postaux importés')


if __name__ == '__main__':
    main()
