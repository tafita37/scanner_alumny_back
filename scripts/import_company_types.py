"""
Import des catégories juridiques INSEE dans la table company_type.

Le fichier Excel contient 3 feuilles (Niveau I, II, III) avec les colonnes
Code / Libellé en ligne 4 et les données à partir de la ligne 5.
Une ligne est insérée par code de niveau III, avec les libellés de ses
parents de niveau I (1er chiffre) et de niveau II (2 premiers chiffres).

Usage (depuis scanner_alumny_back, avec l'environnement virtuel activé) :
    python scripts/import_company_types.py [chemin_du_fichier.xls]
"""
import os
import sys
from pathlib import Path

import xlrd

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FILE = BASE_DIR / 'cj_septembre_2022.xls'
FIRST_DATA_ROW = 4  # ligne 5 dans Excel (index 0)

sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scanner.settings')

import django  # noqa: E402

django.setup()

from django.db import connection, transaction  # noqa: E402

UPSERT_SQL = """
    INSERT INTO company_type (code, label, label_level_1, label_level_2)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (code) DO UPDATE SET
        label = EXCLUDED.label,
        label_level_1 = EXCLUDED.label_level_1,
        label_level_2 = EXCLUDED.label_level_2
"""


def read_sheet(sheet):
    """Retourne un dict {code: libellé} pour une feuille."""
    rows = {}
    for r in range(FIRST_DATA_ROW, sheet.nrows):
        code = str(sheet.cell_value(r, 0)).strip()
        label = str(sheet.cell_value(r, 1)).strip()
        if code:
            rows[code] = label
    return rows


def build_rows(file_path):
    workbook = xlrd.open_workbook(file_path)
    if workbook.nsheets < 3:
        raise ValueError(f'3 feuilles attendues, {workbook.nsheets} trouvée(s)')
    level_1, level_2, level_3 = (read_sheet(workbook.sheet_by_index(i)) for i in range(3))

    rows = []
    for code, label in level_3.items():
        parent_1 = level_1.get(code[:1])
        parent_2 = level_2.get(code[:2])
        if parent_1 is None or parent_2 is None:
            raise ValueError(f'Parent introuvable pour le code {code} ({label})')
        rows.append((code, label, parent_1, parent_2))
    return rows


def main():
    file_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE
    rows = build_rows(file_path)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.executemany(UPSERT_SQL, rows)
    print(f'{len(rows)} formes juridiques importées depuis {file_path.name}')


if __name__ == '__main__':
    main()
