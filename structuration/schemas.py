"""Schémas de sortie du LLM, un par secteur.

Compatibles avec le mode strict de Groq (Structured Outputs) :
- extra="forbid"  -> "additionalProperties": false dans le JSON Schema
- aucun champ n'a de valeur par défaut -> tous les champs sont "required"
- une valeur absente est représentée par null (type X | None)
- les sous-objets sont recopiés dans le schéma (pas de $ref) par langchain

Le schéma est envoyé au LLM à chaque appel : les descriptions sont courtes. Les règles
générales (null si absent, textes recopiés tels quels) sont dans le prompt système (prompts.py)
et ne sont pas répétées champ par champ.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Blocs communs aux documents commerciaux des trois secteurs
# --------------------------------------------------------------------------- #

class Partie(Strict):
    nom: str | None = Field(description="Nom ou raison sociale.")
    adresse: str | None = Field(description="Adresse complète sur une ligne.")
    telephone: str | None = Field(description="Numéro de téléphone.")
    email: str | None = Field(description="Adresse e-mail.")
    siret: str | None = Field(description="SIRET (14 chiffres), à défaut SIREN (9 chiffres).")
    tva_intracom: str | None = Field(description="Numéro de TVA intracommunautaire (FR...).")


class EnTete(Strict):
    numero: str | None = Field(description="Numéro de facture, de devis ou de commande.")
    reference: str | None = Field(description="Référence du projet, du chantier, du dossier ou de la commande du client.")
    date_document: str | None = Field(description="Date d'émission au format AAAA-MM-JJ.")
    date_echeance: str | None = Field(description="Date d'échéance du paiement au format AAAA-MM-JJ.")
    date_validite: str | None = Field(
        description="Date limite de validité d'un devis ou d'une proposition au format AAAA-MM-JJ. "
                    "null si seule une durée est écrite."
    )
    duree_validite_jours: int | None = Field(
        description="Durée de validité écrite, en jours (30 pour 'valable 30 jours', 90 pour '3 mois')."
    )
    date_debut_execution: str | None = Field(
        description="Début des travaux, de la mission ou de la prestation au format AAAA-MM-JJ."
    )
    date_fin_execution: str | None = Field(
        description="Fin des travaux, de la mission ou de la prestation au format AAAA-MM-JJ."
    )
    devise: str | None = Field(description="Code de la devise (EUR, USD, CHF...).")


class VentilationTVA(Strict):
    # Vérifiés par coherence.py (base_ht × taux / 100 = montant_tva) ; taux repris tel quel par calculs.py
    taux: float | None = Field(description="Taux de TVA en pourcentage (exemple 20 pour 20 %).")
    base_ht: float | None = Field(description="Montant HT soumis à ce taux.")
    montant_tva: float | None = Field(description="Montant de TVA à ce taux.")


class PiedDocument(Strict):
    # total_ht + total_tva = total_ttc (coherence.py) : seul le total après remise vérifie l'égalité
    total_ht: float | None = Field(
        description="Total HT après remise globale (souvent écrit 'Net HT' quand une remise est appliquée)."
    )
    remise_globale_ht: float | None = Field(description="Remise globale en montant HT appliquée au document (pas aux lignes).")
    total_tva: float | None = Field(description="Montant total de la TVA.")
    total_ttc: float | None = Field(description="Total TTC du document.")
    net_a_payer: float | None = Field(description="Après acompte versé, retenue de garantie...")
    ventilation_tva: list[VentilationTVA] = Field(
        description="Une entrée par taux de TVA du récapitulatif. Liste vide si aucun récapitulatif par taux."
    )


class Conditions(Strict):
    acompte_pourcentage: float | None = Field(description="En pourcentage (exemple 30 pour 30 %).")
    acompte_montant: float | None = Field(description="Acompte demandé en montant.")
    delai_reglement_jours: int | None = Field(
        description="Délai écrit (30 pour '30 jours fin de mois'). Ne le calcule pas à partir des dates : "
                    "si seule la date d'échéance est écrite, null."
    )
    mode_paiement: Literal["virement", "cheque", "carte", "prelevement", "especes", "autre"] | None = Field(
        description="Si plusieurs modes sont acceptés, le premier cité."
    )
    penalites_retard: str | None = Field(description="Pénalités de retard (exemple : '3 fois le taux d'intérêt légal').")
    indemnite_forfaitaire_recouvrement: float | None = Field(description="Souvent 40.")
    escompte_pourcentage: float | None = Field(
        description="En pourcentage. 0 si le document indique 'pas d'escompte', null si non mentionné."
    )
    conditions_generales_presentes: bool = Field(
        description="true si le document contient ou cite des conditions générales de vente."
    )


class LigneChiffree(Strict):
    libelle: str = Field(description="Libellé de la ligne.")
    section: str | None = Field(
        description="Titre du lot ou du regroupement de la ligne (exemple : 'Lot 2 - Plomberie'). "
                    "null si les lignes ne sont pas regroupées."
    )
    quantite: float | None = Field(description="Quantité de la ligne.")
    unite: str | None = Field(description="h, m2, u, jour, ens...")
    prix_unitaire_ht: float | None = Field(description="Avant remise.")
    remise_pourcentage: float | None = Field(description="En pourcentage (exemple 10 pour 10 %).")
    total_ht: float | None = Field(description="Après remise.")
    taux_tva: float | None = Field(description="En pourcentage (exemple 20 pour 20 %).")


class DocumentCommercial(Strict):
    emetteur: Partie = Field(description="Entreprise qui émet le document (fournisseur, prestataire).")
    destinataire: Partie = Field(description="Client ou destinataire du document.")
    en_tete: EnTete = Field(description="Identification et dates du document.")
    pied: PiedDocument = Field(description="Totaux du document.")
    conditions: Conditions = Field(description="Conditions de paiement.")


# --------------------------------------------------------------------------- #
# BTP : devis, factures, situations de travaux
# --------------------------------------------------------------------------- #

class LignePrestationBTP(LigneChiffree):
    nature: Literal["main_oeuvre", "fourniture", "autre"] = Field(
        description=(
            "main_oeuvre : temps de travail facturé (pose, heures, journée d'ouvrier). "
            "fourniture : matériel, matériaux, équipements. "
            "autre : déplacement, location, évacuation, fourniture et pose sans détail, ligne indéterminée."
        )
    )


class Chantier(Strict):
    nom: str | None = Field(description="Nom ou objet du chantier.")
    adresse: str | None = Field(description="Seulement si elle diffère de celle du client.")
    duree_travaux: str | None = Field(description="Exemple : '3 semaines'.")


class AssuranceDecennale(Strict):
    assureur: str | None = Field(description="Assureur de la garantie décennale.")
    numero_police: str | None = Field(description="Numéro de police ou de contrat.")


class Situation(Strict):
    numero: int | None = Field(description="3 pour 'situation n°3'.")
    avancement_pourcentage: float | None = Field(description="Avancement global des travaux en %.")
    montant_cumule_ht: float | None = Field(description="Cumul HT des travaux réalisés à cette situation.")
    montant_deja_facture_ht: float | None = Field(description="Déjà facturé HT aux situations précédentes.")


class ExtractionBTP(DocumentCommercial):
    type_document: Literal["devis", "facture", "situation_travaux", "hors_sujet"] = Field(
        description="situation_travaux : facture de situation (avancement des travaux). "
                    "hors_sujet : ni devis, ni facture, ni situation de travaux."
    )
    lignes: list[LignePrestationBTP] = Field(description="Lignes de prestation, dans l'ordre du document. Liste vide si hors_sujet.")
    chantier: Chantier = Field(description="Chantier concerné.")
    retenue_garantie_pourcentage: float | None = Field(description="En pourcentage, souvent 5.")
    retenue_garantie_montant: float | None = Field(description="Retenue de garantie en montant.")
    autoliquidation_tva: bool = Field(
        description="true si le document indique une autoliquidation (sous-traitance, 'TVA due par le preneur')."
    )
    assurance_decennale: AssuranceDecennale = Field(description="Assurance décennale mentionnée.")
    signature_client: bool = Field(
        description="true si le document porte 'bon pour accord', une signature ou un cachet du client."
    )
    situation: Situation | None = Field(description="Uniquement pour une situation de travaux, sinon null.")


# --------------------------------------------------------------------------- #
# SERVICES : propositions commerciales, TJM, forfaits
# --------------------------------------------------------------------------- #

class LignePrestationServices(LigneChiffree):
    mode_facturation: Literal["regie_jour", "regie_heure", "forfait", "frais", "autre"] = Field(
        description=(
            "regie_jour : facturé au jour (TJM). regie_heure : facturé à l'heure. "
            "forfait : prix global pour un livrable ou une mission. "
            "frais : déplacements, hébergement, frais refacturés. autre : licences, matériel, ligne indéterminée."
        )
    )
    profil: str | None = Field(description="Profil ou séniorité de l'intervenant (junior, senior, chef de projet...).")
    jours_estimes: float | None = Field(
        description="Forfait seulement : charge en jours écrite dans le document (exemple : '10 jours')."
    )
    au_reel: bool | None = Field(
        description="Frais seulement : true si refacturés au réel, false si forfaitaires. null pour les autres lignes."
    )


class Echeance(Strict):
    libelle: str | None = Field(description="Exemple : 'à la commande'.")
    pourcentage: float | None = Field(description="Part du total en pourcentage.")
    montant: float | None = Field(description="Montant de l'échéance.")
    date: str | None = Field(description="Au format AAAA-MM-JJ.")


class ExtractionServices(DocumentCommercial):
    type_document: Literal["proposition_commerciale", "devis", "facture", "hors_sujet"] = Field(
        description="hors_sujet : ni proposition commerciale, ni devis, ni facture."
    )
    lignes: list[LignePrestationServices] = Field(description="Lignes de prestation, dans l'ordre du document. Liste vide si hors_sujet.")
    echeancier: list[Echeance] = Field(description="Échéancier de paiement ou de facturation par jalon, dans l'ordre. Liste vide si absent.")
    nb_participants: int | None = Field(description="Pour une formation.")
    lieu: str | None = Field(description="Lieu de la formation ou de l'intervention.")
    reconduction: str | None = Field(description="Conditions de reconduction ou de renouvellement.")


# --------------------------------------------------------------------------- #
# INDUSTRIE : bons de commande, fiches de prix de revient
# --------------------------------------------------------------------------- #

class LigneCommande(LigneChiffree):
    reference: str | None = Field(description="Référence produit.")
    conditionnement: str | None = Field(description="Exemple : 'carton de 12', 'palette'.")


class Livraison(Strict):
    date_livraison: str | None = Field(description="Au format AAAA-MM-JJ.")
    adresse_livraison: str | None = Field(description="Seulement si elle diffère de celle du destinataire.")
    incoterm: str | None = Field(description="EXW, DAP, franco...")
    frais_port_ht: float | None = Field(description="S'ils sont indiqués à part des lignes produits.")


class Composant(Strict):
    designation: str = Field(description="Désignation du composant ou de la matière.")
    quantite: float | None = Field(description="Quantité utilisée.")
    unite: str | None = Field(description="kg, m, u...")
    cout: float | None = Field(description="Pour la quantité de référence de la fiche.")


class FichePrixRevient(Strict):
    produit: str | None = Field(description="Nom ou référence du produit.")
    date_ou_version: str | None = Field(description="Date ou version de la fiche.")
    quantite_reference: float | None = Field(
        description="Nombre d'unités pour lequel les coûts sont donnés (1 si coût unitaire)."
    )
    taille_lot: float | None = Field(description="Taille du lot ou de la série de fabrication.")
    composants: list[Composant] = Field(description="Détail des matières et composants (nomenclature). Liste vide si non détaillé.")
    cout_matiere: float | None = Field(description="Matières premières et composants.")
    heures_main_oeuvre: float | None = Field(description="Temps de main-d'œuvre en heures.")
    taux_horaire_main_oeuvre: float | None = Field(description="Taux horaire de main-d'œuvre.")
    cout_main_oeuvre: float | None = Field(description="Main-d'œuvre de production.")
    heures_machine: float | None = Field(description="Temps machine en heures.")
    taux_horaire_machine: float | None = Field(description="Taux horaire machine.")
    cout_machine: float | None = Field(description="Heures machine, énergie.")
    taux_frais_generaux: float | None = Field(description="Taux de frais généraux en pourcentage (exemple 15 pour 15 %).")
    autres_couts: float | None = Field(description="Frais généraux, sous-traitance.")
    taux_rebut: float | None = Field(description="Taux de rebut ou de perte en pourcentage.")
    cout_revient_total: float | None = Field(description="Coût de revient total indiqué.")
    coefficient_marge: float | None = Field(description="Coefficient appliqué au coût de revient (exemple 1.35).")
    marge_visee_pourcentage: float | None = Field(description="Marge visée en pourcentage.")
    prix_vente: float | None = Field(description="Pour la même quantité de référence.")


class ExtractionIndustrie(DocumentCommercial):
    type_document: Literal["bon_de_commande", "fiche_prix_revient", "facture", "hors_sujet"] = Field(
        description="hors_sujet : ni bon de commande, ni fiche de prix de revient, ni facture."
    )
    lignes_commande: list[LigneCommande] = Field(description="Lignes d'un bon de commande ou d'une facture. Liste vide pour une fiche de prix de revient.")
    livraison: Livraison = Field(description="Conditions de livraison d'un bon de commande ou d'une facture.")
    fiches_prix_revient: list[FichePrixRevient] = Field(description="Une entrée par produit d'une fiche de prix de revient. Liste vide sinon.")


# --------------------------------------------------------------------------- #
# COMPTES ANNUELS : bilan + compte de résultat (tous secteurs), exercice N seulement
# --------------------------------------------------------------------------- #

class IdentificationComptes(Strict):
    raison_sociale: str | None = Field(description="Dénomination de l'entreprise.")
    siren: str | None = Field(description="9 chiffres.")
    date_ouverture: str | None = Field(description="Ouverture de l'exercice N au format AAAA-MM-JJ.")
    date_cloture: str | None = Field(description="Clôture de l'exercice N au format AAAA-MM-JJ.")
    duree_exercice_mois: int | None = Field(description="Souvent 12.")


class Actif(Strict):
    immobilisations_incorporelles_net: float | None = Field(description="Total (fonds commercial, logiciels...).")
    terrains_net: float | None = Field(description="Terrains, net.")
    constructions_net: float | None = Field(description="Constructions, net.")
    installations_techniques_brut: float | None = Field(description="Installations techniques, matériel et outillage.")
    installations_techniques_net: float | None = Field(description="Installations techniques, matériel et outillage.")
    autres_immobilisations_corporelles_net: float | None = Field(description="Dont en cours et avances.")
    immobilisations_financieres_net: float | None = Field(description="Total.")
    total_actif_immobilise_brut: float | None = Field(description="Total de l'actif immobilisé, brut.")
    total_actif_immobilise_net: float | None = Field(description="Total de l'actif immobilisé, net.")
    stocks: float | None = Field(description="Total des stocks et en-cours, net.")
    creances_clients: float | None = Field(description="Clients et comptes rattachés, net.")
    autres_creances: float | None = Field(description="Autres créances, net.")
    valeurs_mobilieres_placement: float | None = Field(description="Valeurs mobilières de placement, net.")
    disponibilites: float | None = Field(description="Disponibilités.")
    charges_constatees_avance: float | None = Field(description="Charges constatées d'avance.")
    total_actif: float | None = Field(description="Total général de l'actif (net).")


class Passif(Strict):
    capital_social: float | None = Field(description="Capital social ou individuel.")
    reserves: float | None = Field(description="Total (légale, statutaires, autres).")
    report_a_nouveau: float | None = Field(description="Peut être négatif.")
    resultat_exercice: float | None = Field(description="Inscrit au passif. Peut être négatif.")
    total_capitaux_propres: float | None = Field(description="Total des capitaux propres.")
    provisions_risques_charges: float | None = Field(description="Total.")
    emprunts_dettes_financieres: float | None = Field(
        description="Auprès des établissements de crédit et autres dettes financières."
    )
    dettes_fournisseurs: float | None = Field(description="Fournisseurs et comptes rattachés.")
    dettes_fiscales_sociales: float | None = Field(description="Dettes fiscales et sociales.")
    autres_dettes: float | None = Field(description="Dont dettes sur immobilisations.")
    produits_constates_avance: float | None = Field(description="Produits constatés d'avance.")
    total_passif: float | None = Field(description="Total général du passif.")


class CompteResultat(Strict):
    # Produits d'exploitation
    ventes_marchandises: float | None = Field(description="Ventes de marchandises.")
    production_vendue_biens: float | None = Field(description="Production vendue de biens.")
    production_vendue_services: float | None = Field(description="Production vendue de services.")
    chiffre_affaires: float | None = Field(description="Chiffre d'affaires net.")
    production_stockee: float | None = Field(description="Peut être négative.")
    production_immobilisee: float | None = Field(description="Production immobilisée.")
    subventions_exploitation: float | None = Field(description="Subventions d'exploitation.")
    reprises_provisions_transferts: float | None = Field(
        description="Reprises sur amortissements, dépréciations et provisions, transferts de charges."
    )
    autres_produits: float | None = Field(description="Autres produits d'exploitation.")
    total_produits_exploitation: float | None = Field(description="Total des produits d'exploitation.")
    # Charges d'exploitation
    achats_marchandises: float | None = Field(description="Achats de marchandises.")
    variation_stock_marchandises: float | None = Field(description="Peut être négative.")
    achats_matieres_premieres: float | None = Field(description="Matières premières et autres approvisionnements.")
    variation_stock_matieres: float | None = Field(
        description="Matières premières et approvisionnements. Peut être négative."
    )
    autres_achats_charges_externes: float | None = Field(description="Autres achats et charges externes.")
    impots_taxes: float | None = Field(description="Impôts, taxes et versements assimilés.")
    salaires_traitements: float | None = Field(
        description="Si une seule ligne regroupe salaires et charges sociales (charges de personnel), mets-la ici."
    )
    charges_sociales: float | None = Field(description="null si regroupées avec les salaires.")
    dotations_amortissements: float | None = Field(description="Sur immobilisations.")
    dotations_provisions: float | None = Field(
        description="Dépréciations et provisions d'exploitation (hors amortissements)."
    )
    autres_charges: float | None = Field(description="Autres charges d'exploitation.")
    total_charges_exploitation: float | None = Field(description="Total des charges d'exploitation.")
    resultat_exploitation: float | None = Field(description="Peut être négatif.")
    # Financier, exceptionnel, impôt
    produits_financiers: float | None = Field(description="Total.")
    charges_financieres: float | None = Field(description="Total.")
    interets_charges_assimilees: float | None = Field(description="Inclus dans les charges financières.")
    resultat_financier: float | None = Field(description="Peut être négatif.")
    produits_exceptionnels: float | None = Field(description="Total.")
    charges_exceptionnelles: float | None = Field(description="Total.")
    resultat_exceptionnel: float | None = Field(description="Peut être négatif.")
    participation_salaries: float | None = Field(description="Participation des salariés aux résultats.")
    impots_benefices: float | None = Field(description="Peut être négatif (crédit d'impôt).")
    # Totaux
    total_produits: float | None = Field(description="Total des produits.")
    total_charges: float | None = Field(description="Total des charges.")
    resultat_net: float | None = Field(description="Bénéfice positif, perte négative.")


class RepartitionEffectif(Strict):
    categorie: str = Field(description="Cadres, employés, ouvriers...")
    effectif: float | None = Field(description="Effectif de cette catégorie.")


class EngagementHorsBilan(Strict):
    nature: str = Field(description="Caution, hypothèque, crédit-bail...")
    montant: float | None = Field(description="Montant de l'engagement.")


class Annexe(Strict):
    effectif_moyen: float | None = Field(description="Effectif moyen du personnel.")
    repartition_effectif: list[RepartitionEffectif] = Field(description="Liste vide si non détaillé.")
    credit_bail_redevances_exercice: float | None = Field(description="Redevances payées sur l'exercice N.")
    credit_bail_valeur_origine: float | None = Field(description="Valeur d'origine des biens pris en crédit-bail.")
    engagements_hors_bilan: list[EngagementHorsBilan] = Field(
        description="Engagements donnés hors bilan (hors crédit-bail)."
    )


class ExtractionComptesAnnuels(Strict):
    type_document: Literal["comptes_annuels", "liasse_fiscale", "hors_sujet"] = Field(
        description="hors_sujet : ni bilan ni compte de résultat."
    )
    unite: Literal["euros", "milliers_euros"] = Field(
        description="milliers_euros si le document indique des montants en milliers d'euros (k€, K€), sinon euros."
    )
    compte_resultat_present: bool = Field(description="false si le document ne contient que le bilan (compte de résultat absent ou confidentiel).")
    identification: IdentificationComptes = Field(description="Entreprise et exercice N.")
    actif: Actif = Field(description="Actif du bilan, exercice N.")
    passif: Passif = Field(description="Passif du bilan, exercice N.")
    compte_resultat: CompteResultat = Field(description="Compte de résultat, exercice N.")
    annexe: Annexe = Field(description="Informations tirées de l'annexe, exercice N.")


# --------------------------------------------------------------------------- #
# CLASSIFICATION : quel type de document ?
# --------------------------------------------------------------------------- #

class Classification(Strict):
    categorie: Literal["commercial", "comptes_annuels", "autre"] = Field(
        description=(
            "commercial : devis, facture, proposition commerciale, bon de commande, fiche de prix de revient. "
            "comptes_annuels : bilan, compte de résultat, comptes annuels, liasse fiscale. "
            "autre : tout autre document."
        )
    )


SECTEURS = ("BTP", "SERVICES", "INDUSTRIE")

# Type d'extraction : le secteur pour un document commercial, COMPTES_ANNUELS sinon
SCHEMAS_PAR_TYPE: dict[str, type[Strict]] = {
    "BTP": ExtractionBTP,
    "SERVICES": ExtractionServices,
    "INDUSTRIE": ExtractionIndustrie,
    "COMPTES_ANNUELS": ExtractionComptesAnnuels,
}
