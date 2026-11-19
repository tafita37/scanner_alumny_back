"""
Mise en page du rapport PDF d'un audit : gabarit Django (HTML/CSS) rendu en PDF par WeasyPrint.

`build_report_context` prépare tout ce que le gabarit affiche : nombres au format français, libellés
destinés au client (aucune mention interne : une méthode non fixée est « en cours de finalisation »),
limites méthodologiques déduites du cockpit. Le gabarit ne fait que de la présentation.
Les chiffres viennent du cockpit, jamais du LLM : le LLM ne rédige que les textes (`content`).

Plan (une section par page, 12 pages) : couverture ; synthèse exécutive ; contexte de l'entreprise ;
méthodologie et limites ; perte annuelle estimée ; indicateurs clés ; données retenues et contrôles ;
réponses du dirigeant ; 3 leviers à 30 jours (une page chacun) ; prochaine étape (appel à l'action Calendly).

WeasyPrint s'appuie sur Pango (GTK) : sous Windows, le GTK3 Runtime doit être installé. Il est importé
au moment du rendu seulement, pour ne pas charger GTK au démarrage de Django.
"""
import json
import math
import re
from datetime import date
from pathlib import Path

from django.template.loader import render_to_string

TEMPLATE = 'companies/report/report.html'
STYLESHEET = Path(__file__).resolve().parent.parent / 'templates' / 'companies' / 'report' / 'report.css'

# Réponses du dirigeant affichées (priorité à celles qui alimentent le moteur de calcul)
MAX_QUESTIONS_AFFICHEES = 10

MOIS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
        'novembre', 'décembre')
NBSP = ' '
NNBSP = ' '  # espace fine insécable : séparateur des milliers

SOURCES = {
    'comptes_annuels': 'Comptes annuels',
    'api': 'Données publiées',
    'documents': 'Vos documents',
    'questionnaire': 'Vos réponses',
    'parametre': 'Référence sectorielle',
}
STATUTS = {
    'ok': ('Chiffré', 'ok'),
    'manquant': ('Donnée manquante', 'warn'),
    'non_defini': ('Méthode en cours de finalisation', 'muted'),
}
# Formulations internes du moteur remplacées dans le rapport client
REMPLACEMENTS = (
    (re.compile(r'\s*\((?:à valider|à définir)[^)]*\)', re.IGNORECASE), ''),
    (re.compile(r'\s*:\s*méthode à définir', re.IGNORECASE), ''),
    (re.compile(r'\bà (?:définir|valider)\b', re.IGNORECASE), 'en cours de finalisation'),
    (re.compile(r'à demander au dirigeant', re.IGNORECASE), 'à compléter'),
    (re.compile(r"Secteur (\S+) choisi à l'onboarding"), r"Secteur d'activité retenu : \1"),
    (re.compile(r"\s+de l'agent\b"), ''),
)


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #

def fmt_number(x) -> str:
    """Nombre à la française : 704 000 ; 58 666,67 (espace fine insécable pour les milliers)."""
    if isinstance(x, float) and not x.is_integer():
        texte = f'{x:,.2f}'
    else:
        texte = f'{int(round(x)):,}'
    return texte.replace(',', NNBSP).replace('.', ',')


def fmt_value(valeur, unite: str | None) -> str | None:
    if valeur is None or isinstance(valeur, bool):
        return None
    return f'{fmt_number(valeur)}{NBSP}{unite}' if unite else fmt_number(valeur)


def fmt_date(jour: date | str | None) -> str | None:
    """19 novembre 2026."""
    if isinstance(jour, str):
        try:
            jour = date.fromisoformat(jour[:10])
        except ValueError:
            return jour
    if jour is None:
        return None
    return f'{jour.day}{NBSP}{MOIS[jour.month - 1]} {jour.year}'


def client_text(texte: str | None) -> str | None:
    """Texte du moteur de calcul reformulé pour le client (aucune mention interne)."""
    if not texte:
        return texte
    for motif, remplacement in REMPLACEMENTS:
        texte = motif.sub(remplacement, texte)
    return ' '.join(texte.split())


def fmt_answer(question: dict) -> str:
    """Réponse du dirigeant lisible : nombre avec unité, Oui / Non, date, texte."""
    if question['status'] == 'ignoree':
        return 'Sans réponse'
    valeur = json.loads(question['answer']) if question['answer'] is not None else None
    if valeur is None:
        return '—'
    if isinstance(valeur, bool):
        return 'Oui' if valeur else 'Non'
    if isinstance(valeur, (int, float)):
        unite = question['unit'] or {'montant': '€', 'pourcentage': '%'}.get(question['answer_type'])
        return fmt_value(valeur, unite)
    if question['answer_type'] == 'date':
        return fmt_date(valeur)
    return str(valeur)


# --------------------------------------------------------------------------- #
# Graphiques (SVG)
# --------------------------------------------------------------------------- #

def gauge_svg(score: float) -> str:
    """Jauge en demi-cercle du score de santé (0 à 100)."""
    score = max(0.0, min(100.0, float(score)))
    angle = math.pi * (1 - score / 100)
    x, y = 100 + 80 * math.cos(angle), 100 - 80 * math.sin(angle)
    return (
        '<svg viewBox="0 0 200 115" width="200" height="115" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="#eaf0fd" stroke-width="18"/>'
        f'<path d="M20 100 A80 80 0 0 1 {x:.1f} {y:.1f}" fill="none" stroke="#2550A2" stroke-width="18"/>'
        f'<text x="100" y="95" text-anchor="middle" font-size="34" font-weight="bold" fill="#1b3c7a">{round(score)}</text>'
        '<text x="100" y="112" text-anchor="middle" font-size="11" fill="#6b6b6b">/ 100</text>'
        '</svg>'
    )


# --------------------------------------------------------------------------- #
# Contexte du gabarit
# --------------------------------------------------------------------------- #

def _loss(cockpit: dict) -> dict:
    perte = cockpit['perte_annuelle']
    connues = [c['valeur'] for c in perte['composantes'] if c['statut'] == 'ok' and c['valeur']]
    maximum = max(connues) if connues else 0
    composantes = []
    for c in perte['composantes']:
        libelle, ton = STATUTS[c['statut']]
        chiffree = c['statut'] == 'ok' and c['valeur'] is not None
        composantes.append({
            'label': client_text(c['label']),
            'value': fmt_value(c['valeur'], '€') if chiffree else None,
            'width': round(100 * c['valeur'] / maximum) if chiffree and maximum else 0,
            'status': libelle if not chiffree else None,
            'tone': ton,
        })
    return {
        'value': fmt_value(perte['valeur'], '€'),
        'partial': perte['partielle'],
        'components': composantes,
        'measured': sum(1 for c in composantes if c['value'] is not None),
    }


def _indicators(cockpit: dict, labels: dict, comments: dict) -> list[dict]:
    resultat = []
    for i in cockpit['indicateurs']:
        libelle, ton = STATUTS[i['statut']]
        resultat.append({
            'name': i['nom'],
            'value': fmt_value(i['valeur'], i['unite']) if i['statut'] == 'ok' else None,
            'pivot': i['pivot'],
            'formula': client_text(i['formule']),
            'comparison': client_text(i['comparaison']),
            'status': libelle,
            'tone': ton,
            'missing': [labels.get(cle, cle) for cle in i['manquants']],
            'comment': comments.get(i['cle']),
        })
    return resultat


def _entries(cockpit: dict) -> list[dict]:
    resultat = []
    for e in cockpit['entrees']:
        libelle, ton = STATUTS[e['statut']]
        detail = 'méthode de calcul en cours de finalisation' if e['statut'] == 'non_defini' else client_text(e['detail'])
        resultat.append({
            'label': e['label'],
            'value': fmt_value(e['valeur'], e['unite']),
            'source': SOURCES.get(e['source']) if e['valeur'] is not None else None,
            'detail': detail,
            'status': libelle,
            'tone': ton,
        })
    return resultat


def _steps(cockpit: dict) -> list[dict]:
    return [
        {'label': s['libelle'], 'equation': s['equation'], 'result': fmt_value(s['resultat'], s['unite'])}
        for s in cockpit['etapes_calcul']
    ]


def lower_first(texte: str) -> str:
    """Première lettre en minuscule, sauf pour un sigle (« TJM vendu » reste tel quel)."""
    if len(texte) > 1 and texte[1].isupper():
        return texte
    return texte[:1].lower() + texte[1:]


def _limits(cockpit: dict, labels: dict) -> list[str]:
    """
    Limites de l'analyse : ce qui n'est pas chiffré et pourquoi, puis les réserves générales. Les
    contrôles de l'audit sont affichés à part (page des données retenues).
    """
    limites = []
    for i in cockpit['indicateurs']:
        if i['statut'] == 'manquant':
            manquants = ', '.join(lower_first(labels.get(cle, cle)) for cle in i['manquants'])
            limites.append(f'{i["nom"]} : non chiffré, faute de donnée ({manquants}).')
        elif i['statut'] == 'non_defini':
            limites.append(f'{i["nom"]} : méthode de calcul en cours de finalisation.')
    perte = cockpit['perte_annuelle']
    non_chiffrees = [lower_first(client_text(c['label'])) for c in perte['composantes'] if c['statut'] != 'ok']
    if non_chiffrees:
        limites.append('La perte annuelle est une estimation partielle : ' + ', '.join(non_chiffrees)
                       + ' ne sont pas encore chiffrés.')
    if cockpit.get('score_sante') is None:
        limites.append('Le score de santé global n\'est pas encore calculé.')
    limites += [
        'Les montants sont des estimations établies à partir des documents transmis et de vos réponses : '
        'ils ne constituent pas une certification des comptes.',
        'Un montant annuel calculé à partir d\'une donnée mensuelle suppose une activité régulière sur 12 mois.',
    ]
    return limites


def _financials(indicators: dict, published: dict) -> list[dict]:
    """
    Chiffres clés retenus par les indicateurs (comptes annuels en priorité, sinon données publiées),
    avec leur source. Un chiffre d'affaires publié à 0 signifie qu'il n'est pas publié.
    """
    lignes = []
    for label, cle, unite in (("Chiffre d'affaires", 'chiffre_affaires', '€'), ('Résultat net', 'resultat_net', '€'),
                              ('Effectif', 'effectif', 'salariés')):
        retenu = indicators.get(cle) or {}
        valeur, source = retenu.get('valeur'), retenu.get('source')
        if valeur is None:
            valeur, source = published.get(cle), 'api'
        if cle == 'chiffre_affaires' and not valeur:
            lignes.append({'label': label, 'value': 'non publié', 'source': None})
        else:
            lignes.append({'label': label, 'value': fmt_value(valeur, unite) or '—', 'source': SOURCES.get(source)})
    lignes.append({'label': 'Année de publication', 'value': str(published['annee']), 'source': SOURCES['api']})
    return lignes


def _questions(questions: list[dict]) -> dict:
    """Réponses du dirigeant affichées : d'abord celles qui alimentent le moteur, puis les autres."""
    triees = sorted(questions, key=lambda q: q['variable'] is None)  # tri stable : ordre des tours conservé
    affichees = triees[:MAX_QUESTIONS_AFFICHEES]
    return {
        'shown': [{'label': q['label'], 'answer': fmt_answer(q), 'ignored': q['status'] == 'ignoree',
                   'engine': q['variable'] is not None} for q in affichees],
        'others': len(questions) - len(affichees),
        'total': len(questions),
    }


def build_report_context(*, company: dict, published: dict, indicators: dict, cockpit: dict, content: dict,
                         questions: list[dict], calendly_url: str, audit_date: date | str,
                         generated_on: date) -> dict:
    """
    Contexte du gabarit.
    `company` : {name, siren, siret, naf, legal_form, city, creation_date, sector} ; `published` :
    données publiées de l'audit (annee, chiffre_affaires, resultat_net, effectif), à défaut des
    chiffres retenus par les indicateurs ; `indicators` :
    `compute_indicators(audit)` ; `cockpit` : `compute_cockpit(audit)` ; `content` : textes rédigés
    (`rapport.schemas.RapportRedige`, noms remis) ; `questions` : réponses du dirigeant (label,
    answer_type, unit, status, answer en JSON, variable), dans l'ordre des tours.
    """
    labels = {e['cle']: e['label'] for e in cockpit['entrees']}
    comments = {c['cle']: c['commentaire'] for c in content['commentaires_indicateurs']}
    comptes = indicators.get('comptes_annuels') or {}
    score = cockpit.get('score_sante')
    return {
        'company': {**company, 'creation_date': fmt_date(company.get('creation_date'))},
        'audit_date': fmt_date(audit_date),
        'generated_on': fmt_date(generated_on),
        'financials': _financials(indicators, published),
        'annual_accounts_closing': fmt_date(comptes.get('date_cloture')),
        'documents_count': indicators.get('documents_pris_en_compte') or 0,
        'loss': _loss(cockpit),
        'score_svg': gauge_svg(score) if score is not None else None,
        'indicators': _indicators(cockpit, labels, comments),
        'entries': _entries(cockpit),
        'steps': _steps(cockpit),
        'controls': [{'ok': c['ok'], 'text': client_text(c['texte'])} for c in cockpit['controles']],
        'limits': _limits(cockpit, labels),
        'questions': _questions(questions),
        'content': content,
        'calendly_url': calendly_url,
    }


def render_report_pdf(context: dict) -> tuple[bytes, int]:
    """(PDF, nombre de pages)."""
    from weasyprint import CSS, HTML  # charge GTK : seulement au rendu

    html = render_to_string(TEMPLATE, context)
    document = HTML(string=html).render(stylesheets=[CSS(filename=str(STYLESHEET))])
    return document.write_pdf(), len(document.pages)
