"""Sélection des pages utiles des comptes annuels avant l'envoi au LLM.

Une liasse fiscale ou une plaquette d'expert-comptable fait souvent 40 pages, dont 4 à 6 seulement
servent à l'extraction : bilan actif et passif, compte de résultat, quelques informations d'annexe.
Les autres (synthèses sur plusieurs exercices, ratios, soldes intermédiaires de gestion, détail des
comptes, tableaux d'immobilisations et d'emprunts) coûtent des tokens et font confondre N et N-1.

La sélection sert deux fois :
- avant la conversion par Docling, sur le texte natif du PDF (companies.services.pdf_extraction) :
  Docling, lent sur les tableaux, ne lit alors que les pages retenues ;
- avant l'extraction par le LLM, sur le texte Docling (pages_comptes_annuels) : le texte reçu est
  celui construit par companies.services.structuring.build_text, chaque page y est précédée d'une
  ligne "--- page N ---".
"""
import re
import unicodedata

DEBUT_PAGE = re.compile(r"^(?=--- page \d+ ---$)", re.MULTILINE)

# Postes des états financiers (bilan, compte de résultat). Une page qui en contient au moins
# MIN_POSTES_ETATS est une page d'états financiers.
POSTES_ETATS = [re.compile(motif) for motif in (
    r"actif immobilise", r"actif circulant", r"immobilisations incorporelles",
    r"immobilisations corporelles", r"immobilisations financieres", r"disponibilites",
    r"charges constatees d'avance", r"capitaux propres", r"capital social", r"report a nouveau",
    r"resultat de l'exercice", r"dettes fournisseurs", r"dettes fiscales et sociales",
    r"emprunts et dettes", r"chiffre d'affaires", r"produits d'exploitation",
    r"charges d'exploitation", r"resultat d'exploitation", r"produits financiers",
    r"charges financieres", r"resultat financier", r"produits exceptionnels",
    r"charges exceptionnelles", r"resultat exceptionnel", r"impots sur les benefices",
    r"benefice ou perte", r"achats de marchandises", r"salaires et traitements",
    r"dotations aux amortissements",
)]
MIN_POSTES_ETATS = 4

# Informations demandées dans "annexe" (schemas.Annexe) : une seule suffit à garder la page.
INFORMATIONS_ANNEXE = [re.compile(motif) for motif in (
    r"effectif moyen", r"credit[- ]bail", r"engagements (?:financiers|hors bilan|donnes|recus)",
)]

# Pages d'analyse qui reprennent les mêmes postes sans être les états financiers : synthèses
# sur plusieurs exercices, ratios, SIG, détail des comptes, tableaux de flux.
PAGES_ANALYSE = [re.compile(motif) for motif in (
    r"soldes intermediaires", r"excedent brut d'exploitation", r"\bratios?\b", r"\bdetail des\b",
    r"capacite d'autofinancement", r"\bflux\b", r"tableau de financement",
)]


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, apostrophes droites, espaces réduits."""
    texte = unicodedata.normalize("NFKD", texte.lower().replace("’", "'"))
    return " ".join("".join(c for c in texte if not unicodedata.combining(c)).split())


def nature_page(page: str) -> str | None:
    """"etats" (bilan, compte de résultat), "annexe" (information de l'annexe) ou None."""
    texte = normaliser(page)
    if any(motif.search(texte) for motif in PAGES_ANALYSE):
        return None
    if sum(1 for motif in POSTES_ETATS if motif.search(texte)) >= MIN_POSTES_ETATS:
        return "etats"
    if any(motif.search(texte) for motif in INFORMATIONS_ANNEXE):
        return "annexe"
    return None


def indices_pages_utiles(pages: list[str]) -> list[int] | None:
    """
    Indices (à partir de 0) des pages à garder parmi les textes `pages` : la première (raison
    sociale, dates de l'exercice), les pages d'états financiers et les pages d'annexe utiles.
    None si aucune page d'états financiers n'est reconnue (OCR illisible, présentation
    inhabituelle) : mieux vaut alors garder tout le document qu'un bilan manquant.
    """
    natures = [nature_page(page) for page in pages[1:]]
    if "etats" not in natures:
        return None
    return [0, *(indice for indice, nature in enumerate(natures, start=1) if nature is not None)]


def pages_comptes_annuels(texte: str) -> str:
    """Texte réduit aux pages utiles (voir indices_pages_utiles), ou entier si rien n'est reconnu."""
    pages = [page for page in DEBUT_PAGE.split(texte) if page.strip()]
    indices = indices_pages_utiles(pages)
    if indices is None:
        return texte
    return "\n\n".join(pages[indice].strip() for indice in indices)
