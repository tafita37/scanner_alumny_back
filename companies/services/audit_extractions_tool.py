"""
Tool d'agent IA (LangChain) qui lit les extractions des documents d'un audit.

Les extractions sont enregistrées en base avec les données personnelles en clair
(`structure_document` les remet à la place des jetons). Le résultat du tool part chez le
fournisseur du LLM : les coordonnées des parties (adresse, téléphone, e-mail) et les adresses
de chantier, de livraison et d'intervention sont donc retirées, et les noms des parties
remplacés par des alias stables pour tout l'audit (ENTREPRISE_AUDITEE, PARTIE_1, PARTIE_2...).
Les montants, lignes, dates, SIRET et variables calculées sont renvoyés tels quels.
Le texte libre (libellés de lignes, nom de chantier...) n'est pas analysé.
"""
import copy
import json
import re

from langchain_core.tools import BaseTool, tool

from ..models import Audit, Extraction
from .anonymization import normalize_text

AUDITED_COMPANY_ALIAS = 'ENTREPRISE_AUDITEE'
PARTY_ALIAS_FORMAT = 'PARTIE_{number}'
MASKED_VALUE = '[masqué]'
# Coordonnées d'une partie (émetteur, destinataire) retirées de l'extraction
PARTY_CONTACT_FIELDS = ('adresse', 'telephone', 'email')
# (bloc de l'extraction, champ) : adresses hors des parties, retirées elles aussi
ADDRESS_FIELDS = (('chantier', 'adresse'), ('livraison', 'adresse_livraison'), (None, 'lieu'))

TOOL_NAME = 'lire_extractions_audit'
TOOL_DESCRIPTION = (
    "Lit les données extraites des documents de l'audit en cours (devis, factures, situations de "
    "travaux, propositions commerciales, bons de commande, fiches de prix de revient, comptes "
    "annuels). Pour chaque document : sa dernière extraction, avec son statut ('ok' : fiable ; "
    "'a_verifier' : données incomplètes ou incohérentes, voir 'erreurs'), les données lues dans le "
    "document ('extraction') et les variables calculées ('variables'). Les montants sont en euros. "
    "Les noms des parties sont remplacés par des alias : ENTREPRISE_AUDITEE pour l'entreprise "
    "auditée, PARTIE_1, PARTIE_2... pour ses clients et fournisseurs ; leurs coordonnées sont "
    "masquées. 'documents_sans_extraction' liste les documents jamais extraits."
)


def digits(value) -> str:
    return re.sub(r'\D', '', value) if isinstance(value, str) else ''


class PartyAliases:
    """
    Alias des parties d'un audit : la même partie (même nom, casse et accents ignorés) reçoit le
    même alias dans tous les documents. L'entreprise auditée est reconnue à son SIREN (début du
    SIRET) ou à sa raison sociale.
    """

    def __init__(self, siren: str, company_name: str):
        self.siren = digits(siren)
        self.company_name = normalize_text(company_name or '')
        self.aliases = {}  # nom normalisé -> alias

    def alias_for(self, name: str | None, siret: str | None = None) -> str | None:
        if not name:
            return None
        key = normalize_text(name)
        if (len(self.siren) == 9 and digits(siret).startswith(self.siren)) or key == self.company_name:
            return AUDITED_COMPANY_ALIAS
        if key not in self.aliases:
            self.aliases[key] = PARTY_ALIAS_FORMAT.format(number=len(self.aliases) + 1)
        return self.aliases[key]


def mask_extraction(extraction: dict | None, variables: dict | None, errors: list,
                    aliases: PartyAliases) -> tuple[dict | None, dict | None, list]:
    """
    Copies masquées de l'extraction, des variables et des erreurs d'un document.
    Chaque valeur retirée de l'extraction est aussi remplacée dans les erreurs (un message de
    contrôle de cohérence peut la citer). L'extraction peut être la dernière réponse brute du
    LLM (échec) : les blocs absents ou mal formés sont ignorés.
    """
    replacements = {}  # valeur d'origine -> remplaçant, appliqué aux erreurs
    extraction = copy.deepcopy(extraction)
    variables = copy.deepcopy(variables)

    if isinstance(extraction, dict):
        for party_key in ('emetteur', 'destinataire'):
            party = extraction.get(party_key)
            if not isinstance(party, dict):
                continue
            if party.get('nom'):
                alias = aliases.alias_for(party['nom'], party.get('siret'))
                replacements[party['nom']] = alias
                party['nom'] = alias
            for field in PARTY_CONTACT_FIELDS:
                if party.get(field):
                    replacements[party[field]] = MASKED_VALUE
                    party[field] = None
        for block_key, field in ADDRESS_FIELDS:
            block = extraction.get(block_key) if block_key else extraction
            if isinstance(block, dict) and block.get(field):
                replacements[block[field]] = MASKED_VALUE
                block[field] = None
        identification = extraction.get('identification')
        if isinstance(identification, dict) and identification.get('raison_sociale'):
            alias = aliases.alias_for(identification['raison_sociale'])
            replacements[identification['raison_sociale']] = alias
            identification['raison_sociale'] = alias

    if isinstance(variables, dict) and variables.get('raison_sociale'):
        alias = aliases.alias_for(variables['raison_sociale'])
        replacements[variables['raison_sociale']] = alias
        variables['raison_sociale'] = alias

    # Valeurs les plus longues d'abord : une adresse contenant un nom est remplacée en entier.
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    masked_errors = []
    for error in errors:
        if isinstance(error, str):
            for value, replacement in ordered:
                error = error.replace(value, replacement)
        masked_errors.append(error)
    return extraction, variables, masked_errors


def read_audit_extractions(audit_id: int) -> dict:
    """
    Dernière extraction de chaque document de l'audit (quel que soit son statut), masquée pour
    être envoyée au LLM, et liste des documents jamais extraits.
    Lève Audit.DoesNotExist si l'audit n'existe pas.
    """
    audit = Audit.objects.select_related('company__industry').get(pk=audit_id)
    latest = {}
    for extraction in Extraction.objects.filter(document__audit=audit).order_by('id'):
        latest[extraction.document_id] = extraction  # la plus récente écrase les précédentes
    document_ids = list(audit.documents.order_by('id').values_list('id', flat=True))
    aliases = PartyAliases(audit.company.siren_number, audit.company.company_name)

    documents = []
    for extraction in sorted(latest.values(), key=lambda e: e.document_id):
        data, variables, errors = mask_extraction(
            json.loads(extraction.json_extraction) if extraction.json_extraction else None,
            json.loads(extraction.json_variables) if extraction.json_variables else None,
            json.loads(extraction.errors) if extraction.errors else [],
            aliases,
        )
        documents.append({
            'document_id': extraction.document_id,
            'statut': extraction.status,
            'date_extraction': extraction.extraction_date.isoformat(),
            'erreurs': errors,
            'extraction': data,
            'variables': variables,
        })
    return {
        'audit_id': audit.pk,
        'secteur': audit.company.industry.name.upper(),
        'documents': documents,
        'documents_sans_extraction': [pk for pk in document_ids if pk not in latest],
    }


def make_audit_extractions_tool(audit_id: int) -> BaseTool:
    """
    Tool `lire_extractions_audit` lié à un audit : l'identifiant est fixé ici, pas choisi par le
    LLM, qui ne peut donc lire que les extractions de cet audit.
    Exemple : `create_agent(model, tools=[make_audit_extractions_tool(audit.pk)])`.
    """

    @tool(TOOL_NAME, description=TOOL_DESCRIPTION)
    def lire_extractions_audit() -> str:
        try:
            result = read_audit_extractions(audit_id)
        except Audit.DoesNotExist:
            result = {'erreur': f'Audit {audit_id} introuvable.'}
        return json.dumps(result, ensure_ascii=False)

    return lire_extractions_audit
