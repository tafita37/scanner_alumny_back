"""Schémas de sortie du LLM, un par secteur.

Compatibles avec le mode strict de Groq (Structured Outputs) :
- extra="forbid"  -> "additionalProperties": false dans le JSON Schema
- aucun champ n'a de valeur par défaut -> tous les champs sont "required"
- une valeur absente est représentée par null (type X | None)
- les sous-objets sont recopiés dans le schéma (pas de $ref) par langchain
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Blocs communs aux documents commerciaux des trois secteurs
# --------------------------------------------------------------------------- #

class Partie(Strict):
    nom: str | None = Field(description="Nom ou raison sociale, recopié tel quel, ou null.")
    adresse: str | None = Field(description="Adresse complète sur une ligne, ou null.")
    siret: str | None = Field(
        description="SIRET (14 chiffres) ou à défaut SIREN (9 chiffres), recopié tel quel, ou null."
    )
    tva_intracom: str | None = Field(description="Numéro de TVA intracommunautaire (FR...), ou null.")


class EnTete(Strict):
    numero: str | None = Field(description="Numéro du document (n° de facture, de devis, de commande), ou null.")
    reference: str | None = Field(
        description="Référence du projet, du chantier, du dossier ou de la commande du client, ou null."
    )
    date_document: str | None = Field(description="Date d'émission au format AAAA-MM-JJ, ou null.")
    date_echeance: str | None = Field(description="Date d'échéance du paiement au format AAAA-MM-JJ, ou null.")
    date_validite: str | None = Field(
        description="Date limite de validité d'un devis ou d'une proposition au format AAAA-MM-JJ, ou null. "
                    "Si seule une durée est indiquée (exemple : 'valable 30 jours'), mets null."
    )
    duree_validite_jours: int | None = Field(
        description="Durée de validité écrite en jours (exemple 30 pour 'valable 30 jours', 90 pour '3 mois'), "
                    "ou null."
    )
    date_debut_execution: str | None = Field(
        description="Début des travaux, de la mission ou de la prestation au format AAAA-MM-JJ, ou null."
    )
    date_fin_execution: str | None = Field(
        description="Fin des travaux, de la mission ou de la prestation au format AAAA-MM-JJ, ou null."
    )
    devise: str | None = Field(description="Code de la devise (EUR, USD, CHF...), ou null si non indiquée.")


class VentilationTVA(Strict):
    taux: float | None = Field(description="Taux de TVA en pourcentage (exemple 20 pour 20 %), ou null.")
    base_ht: float | None = Field(description="Montant HT soumis à ce taux, ou null.")
    montant_tva: float | None = Field(description="Montant de TVA à ce taux, ou null.")


class PiedDocument(Strict):
    total_ht: float | None = Field(description="Total HT du document, ou null.")
    remise_globale_ht: float | None = Field(
        description="Remise globale en montant HT appliquée au document (pas aux lignes), ou null."
    )
    total_tva: float | None = Field(description="Montant total de la TVA, ou null.")
    total_ttc: float | None = Field(description="Total TTC du document, ou null.")
    net_a_payer: float | None = Field(
        description="Net à payer s'il est écrit (après acompte versé, retenue de garantie...), ou null."
    )
    ventilation_tva: list[VentilationTVA] = Field(
        description="Une entrée par taux de TVA du récapitulatif. Liste vide si aucun récapitulatif par taux."
    )


class Conditions(Strict):
    acompte_pourcentage: float | None = Field(
        description="Acompte demandé en pourcentage (exemple 30 pour 30 %), ou null si non mentionné."
    )
    acompte_montant: float | None = Field(description="Acompte demandé en montant, ou null si non mentionné.")
    delai_reglement_jours: int | None = Field(
        description="Délai de règlement écrit en jours (exemple 30 pour '30 jours fin de mois'), ou null. "
                    "Ne le calcule pas à partir des dates : si seule la date d'échéance est indiquée, mets null."
    )
    mode_paiement: Literal["virement", "cheque", "carte", "prelevement", "especes", "autre"] | None = Field(
        description="Mode de paiement demandé, ou null. Si plusieurs modes sont acceptés, prends le premier cité."
    )
    penalites_retard: str | None = Field(
        description="Pénalités de retard recopiées telles quelles (exemple : '3 fois le taux d'intérêt légal'), "
                    "ou null."
    )
    indemnite_forfaitaire_recouvrement: float | None = Field(
        description="Indemnité forfaitaire pour frais de recouvrement (souvent 40), ou null."
    )
    escompte_pourcentage: float | None = Field(
        description="Escompte pour paiement anticipé en pourcentage. 0 si le document indique 'pas d'escompte', "
                    "null si non mentionné."
    )
    conditions_generales_presentes: bool = Field(
        description="true si le document contient ou cite des conditions générales de vente."
    )


class LigneChiffree(Strict):
    libelle: str = Field(description="Libellé de la ligne, recopié tel quel.")
    section: str | None = Field(
        description="Titre de la section, du lot ou du regroupement sous lequel figure la ligne, ou null."
    )
    quantite: float | None = Field(description="Quantité de la ligne, ou null.")
    unite: str | None = Field(description="Unité recopiée telle quelle (h, m2, u, jour, ens...), ou null.")
    prix_unitaire_ht: float | None = Field(description="Prix unitaire HT avant remise, ou null.")
    remise_pourcentage: float | None = Field(
        description="Remise de la ligne en pourcentage (exemple 10 pour 10 %), ou null si aucune."
    )
    total_ht: float | None = Field(description="Montant HT de la ligne (après remise), ou null.")
    taux_tva: float | None = Field(description="Taux de TVA de la ligne en pourcentage, ou null.")


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
            "autre : déplacement, location, évacuation, forfait mixte ou ligne indéterminée."
        )
    )


class Chantier(Strict):
    nom: str | None = Field(description="Nom ou objet du chantier, ou null.")
    adresse: str | None = Field(description="Adresse du chantier si elle diffère de celle du client, ou null.")
    duree_travaux: str | None = Field(
        description="Durée des travaux recopiée telle quelle (exemple : '3 semaines'), ou null."
    )


class AssuranceDecennale(Strict):
    assureur: str | None = Field(description="Nom de l'assureur de la garantie décennale, ou null.")
    numero_police: str | None = Field(description="Numéro de police ou de contrat, ou null.")


class Situation(Strict):
    numero: int | None = Field(description="Numéro de la situation (exemple 3 pour 'situation n°3'), ou null.")
    avancement_pourcentage: float | None = Field(description="Avancement global des travaux en %, ou null.")
    montant_cumule_ht: float | None = Field(
        description="Montant HT cumulé des travaux réalisés à cette situation, ou null."
    )
    montant_deja_facture_ht: float | None = Field(
        description="Montant HT déjà facturé lors des situations précédentes, ou null."
    )


class ExtractionBTP(DocumentCommercial):
    type_document: Literal["devis", "facture", "situation_travaux", "hors_sujet"] = Field(
        description="situation_travaux pour une facture de situation (avancement des travaux). "
                    "hors_sujet si le texte n'est ni un devis, ni une facture, ni une situation de travaux."
    )
    lignes: list[LignePrestationBTP] = Field(
        description="Toutes les lignes de prestation, dans l'ordre du document. Liste vide si hors_sujet."
    )
    chantier: Chantier = Field(description="Chantier concerné.")
    retenue_garantie_pourcentage: float | None = Field(
        description="Retenue de garantie en pourcentage (souvent 5), ou null si non mentionnée."
    )
    retenue_garantie_montant: float | None = Field(description="Retenue de garantie en montant, ou null.")
    autoliquidation_tva: bool = Field(
        description="true si le document indique une autoliquidation de la TVA (sous-traitance, "
                    "'TVA due par le preneur')."
    )
    assurance_decennale: AssuranceDecennale = Field(description="Assurance décennale mentionnée.")
    signature_client: bool = Field(
        description="true si le document porte la mention 'bon pour accord', une signature ou un cachet du client."
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
    profil: str | None = Field(
        description="Profil ou séniorité de l'intervenant (junior, senior, chef de projet...), recopié tel quel, "
                    "ou null."
    )
    jours_estimes: float | None = Field(
        description="Pour un forfait : charge en jours indiquée dans le document, sinon null."
    )
    au_reel: bool | None = Field(
        description="Pour les frais : true si refacturés au réel, false si forfaitaires. null pour les autres lignes."
    )


class Echeance(Strict):
    libelle: str | None = Field(description="Libellé de l'échéance ou du jalon (exemple : 'à la commande'), ou null.")
    pourcentage: float | None = Field(description="Part du total en pourcentage, ou null.")
    montant: float | None = Field(description="Montant de l'échéance, ou null.")
    date: str | None = Field(description="Date de l'échéance au format AAAA-MM-JJ, ou null.")


class ExtractionServices(DocumentCommercial):
    type_document: Literal["proposition_commerciale", "devis", "facture", "hors_sujet"] = Field(
        description="hors_sujet si le texte n'est ni une proposition commerciale, ni un devis, ni une facture."
    )
    lignes: list[LignePrestationServices] = Field(
        description="Toutes les lignes de prestation, dans l'ordre du document. Liste vide si hors_sujet."
    )
    echeancier: list[Echeance] = Field(
        description="Échéancier de paiement ou de facturation par jalon, dans l'ordre. Liste vide si absent."
    )
    nb_participants: int | None = Field(description="Pour une formation : nombre de participants, ou null.")
    lieu: str | None = Field(description="Lieu de la formation ou de l'intervention, ou null.")
    reconduction: str | None = Field(
        description="Conditions de reconduction ou de renouvellement recopiées telles quelles, ou null."
    )


# --------------------------------------------------------------------------- #
# INDUSTRIE : bons de commande, fiches de prix de revient
# --------------------------------------------------------------------------- #

class LigneCommande(LigneChiffree):
    reference: str | None = Field(description="Référence produit, ou null.")
    conditionnement: str | None = Field(
        description="Conditionnement recopié tel quel (exemple : 'carton de 12', 'palette'), ou null."
    )


class Livraison(Strict):
    date_livraison: str | None = Field(description="Date de livraison prévue au format AAAA-MM-JJ, ou null.")
    adresse_livraison: str | None = Field(
        description="Adresse de livraison si elle diffère de celle du destinataire, ou null."
    )
    incoterm: str | None = Field(description="Incoterm ou condition de livraison (EXW, DAP, franco...), ou null.")
    frais_port_ht: float | None = Field(
        description="Frais de port HT s'ils sont indiqués à part (hors lignes produits), ou null."
    )


class Composant(Strict):
    designation: str = Field(description="Désignation du composant ou de la matière, recopiée telle quelle.")
    quantite: float | None = Field(description="Quantité utilisée, ou null.")
    unite: str | None = Field(description="Unité recopiée telle quelle (kg, m, u...), ou null.")
    cout: float | None = Field(description="Coût du composant pour la quantité de référence de la fiche, ou null.")


class FichePrixRevient(Strict):
    produit: str | None = Field(description="Nom ou référence du produit, ou null.")
    date_ou_version: str | None = Field(description="Date ou version de la fiche, recopiée telle quelle, ou null.")
    quantite_reference: float | None = Field(
        description="Nombre d'unités pour lequel les coûts sont donnés (1 si coût unitaire), ou null."
    )
    taille_lot: float | None = Field(description="Taille du lot ou de la série de fabrication, ou null.")
    composants: list[Composant] = Field(
        description="Détail des matières et composants (nomenclature). Liste vide si non détaillé."
    )
    cout_matiere: float | None = Field(description="Coût des matières premières et composants, ou null.")
    heures_main_oeuvre: float | None = Field(description="Temps de main-d'œuvre en heures, ou null.")
    taux_horaire_main_oeuvre: float | None = Field(description="Taux horaire de main-d'œuvre, ou null.")
    cout_main_oeuvre: float | None = Field(description="Coût de main-d'œuvre de production, ou null.")
    heures_machine: float | None = Field(description="Temps machine en heures, ou null.")
    taux_horaire_machine: float | None = Field(description="Taux horaire machine, ou null.")
    cout_machine: float | None = Field(description="Coût machine (heures machine, énergie), ou null.")
    taux_frais_generaux: float | None = Field(
        description="Taux de frais généraux en pourcentage (exemple 15 pour 15 %), ou null."
    )
    autres_couts: float | None = Field(description="Autres coûts (frais généraux, sous-traitance), ou null.")
    taux_rebut: float | None = Field(description="Taux de rebut ou de perte en pourcentage, ou null.")
    cout_revient_total: float | None = Field(description="Coût de revient total indiqué, ou null.")
    coefficient_marge: float | None = Field(
        description="Coefficient multiplicateur appliqué au coût de revient (exemple 1.35), ou null."
    )
    marge_visee_pourcentage: float | None = Field(description="Marge visée en pourcentage, ou null.")
    prix_vente: float | None = Field(description="Prix de vente indiqué pour la même quantité, ou null.")


class ExtractionIndustrie(DocumentCommercial):
    type_document: Literal["bon_de_commande", "fiche_prix_revient", "facture", "hors_sujet"] = Field(
        description="hors_sujet si le texte n'est ni un bon de commande, ni une fiche de prix de revient, ni une facture."
    )
    lignes_commande: list[LigneCommande] = Field(
        description="Lignes d'un bon de commande ou d'une facture. Liste vide pour une fiche de prix de revient."
    )
    livraison: Livraison = Field(description="Conditions de livraison d'un bon de commande ou d'une facture.")
    fiches_prix_revient: list[FichePrixRevient] = Field(
        description="Une entrée par produit d'une fiche de prix de revient. Liste vide sinon."
    )


# --------------------------------------------------------------------------- #
# COMPTES ANNUELS : bilan + compte de résultat (tous secteurs), exercice N seulement
# --------------------------------------------------------------------------- #

class IdentificationComptes(Strict):
    raison_sociale: str | None = Field(description="Dénomination de l'entreprise, ou null.")
    siren: str | None = Field(description="Numéro SIREN (9 chiffres), recopié tel quel, ou null.")
    date_ouverture: str | None = Field(description="Date d'ouverture de l'exercice N au format AAAA-MM-JJ, ou null.")
    date_cloture: str | None = Field(description="Date de clôture de l'exercice N au format AAAA-MM-JJ, ou null.")
    duree_exercice_mois: int | None = Field(description="Durée de l'exercice N en mois (souvent 12), ou null.")


class Actif(Strict):
    immobilisations_incorporelles_net: float | None = Field(
        description="Total des immobilisations incorporelles (fonds commercial, logiciels...), net, ou null."
    )
    terrains_net: float | None = Field(description="Terrains, net, ou null.")
    constructions_net: float | None = Field(description="Constructions, net, ou null.")
    installations_techniques_brut: float | None = Field(
        description="Installations techniques, matériel et outillage : montant brut, ou null."
    )
    installations_techniques_net: float | None = Field(
        description="Installations techniques, matériel et outillage : montant net, ou null."
    )
    autres_immobilisations_corporelles_net: float | None = Field(
        description="Autres immobilisations corporelles (dont en cours et avances), net, ou null."
    )
    immobilisations_financieres_net: float | None = Field(
        description="Total des immobilisations financières, net, ou null."
    )
    total_actif_immobilise_brut: float | None = Field(description="Total de l'actif immobilisé, brut, ou null.")
    total_actif_immobilise_net: float | None = Field(description="Total de l'actif immobilisé, net, ou null.")
    stocks: float | None = Field(description="Total des stocks et en-cours, net, ou null.")
    creances_clients: float | None = Field(description="Clients et comptes rattachés, net, ou null.")
    autres_creances: float | None = Field(description="Autres créances, net, ou null.")
    valeurs_mobilieres_placement: float | None = Field(description="Valeurs mobilières de placement, net, ou null.")
    disponibilites: float | None = Field(description="Disponibilités, ou null.")
    charges_constatees_avance: float | None = Field(description="Charges constatées d'avance, ou null.")
    total_actif: float | None = Field(description="Total général de l'actif (net), ou null.")


class Passif(Strict):
    capital_social: float | None = Field(description="Capital social ou individuel, ou null.")
    reserves: float | None = Field(description="Total des réserves (légale, statutaires, autres), ou null.")
    report_a_nouveau: float | None = Field(description="Report à nouveau (peut être négatif), ou null.")
    resultat_exercice: float | None = Field(
        description="Résultat de l'exercice inscrit au passif (peut être négatif), ou null."
    )
    total_capitaux_propres: float | None = Field(description="Total des capitaux propres, ou null.")
    provisions_risques_charges: float | None = Field(
        description="Total des provisions pour risques et charges, ou null."
    )
    emprunts_dettes_financieres: float | None = Field(
        description="Emprunts et dettes auprès des établissements de crédit et autres dettes financières, ou null."
    )
    dettes_fournisseurs: float | None = Field(description="Dettes fournisseurs et comptes rattachés, ou null.")
    dettes_fiscales_sociales: float | None = Field(description="Dettes fiscales et sociales, ou null.")
    autres_dettes: float | None = Field(
        description="Autres dettes (dont dettes sur immobilisations), ou null."
    )
    produits_constates_avance: float | None = Field(description="Produits constatés d'avance, ou null.")
    total_passif: float | None = Field(description="Total général du passif, ou null.")


class CompteResultat(Strict):
    # Produits d'exploitation
    ventes_marchandises: float | None = Field(description="Ventes de marchandises, ou null.")
    production_vendue_biens: float | None = Field(description="Production vendue de biens, ou null.")
    production_vendue_services: float | None = Field(description="Production vendue de services, ou null.")
    chiffre_affaires: float | None = Field(description="Chiffre d'affaires net, ou null.")
    production_stockee: float | None = Field(description="Production stockée (peut être négative), ou null.")
    production_immobilisee: float | None = Field(description="Production immobilisée, ou null.")
    subventions_exploitation: float | None = Field(description="Subventions d'exploitation, ou null.")
    reprises_provisions_transferts: float | None = Field(
        description="Reprises sur amortissements, dépréciations et provisions, transferts de charges, ou null."
    )
    autres_produits: float | None = Field(description="Autres produits d'exploitation, ou null.")
    total_produits_exploitation: float | None = Field(description="Total des produits d'exploitation, ou null.")
    # Charges d'exploitation
    achats_marchandises: float | None = Field(description="Achats de marchandises, ou null.")
    variation_stock_marchandises: float | None = Field(
        description="Variation de stock de marchandises (peut être négative), ou null."
    )
    achats_matieres_premieres: float | None = Field(
        description="Achats de matières premières et autres approvisionnements, ou null."
    )
    variation_stock_matieres: float | None = Field(
        description="Variation de stock de matières premières et approvisionnements (peut être négative), ou null."
    )
    autres_achats_charges_externes: float | None = Field(description="Autres achats et charges externes, ou null.")
    impots_taxes: float | None = Field(description="Impôts, taxes et versements assimilés, ou null.")
    salaires_traitements: float | None = Field(
        description="Salaires et traitements. Si une seule ligne regroupe salaires et charges sociales "
                    "(charges de personnel), mets-la ici, ou null."
    )
    charges_sociales: float | None = Field(
        description="Charges sociales, ou null si absentes ou regroupées avec les salaires."
    )
    dotations_amortissements: float | None = Field(
        description="Dotations aux amortissements sur immobilisations, ou null."
    )
    dotations_provisions: float | None = Field(
        description="Dotations aux dépréciations et aux provisions d'exploitation (hors amortissements), ou null."
    )
    autres_charges: float | None = Field(description="Autres charges d'exploitation, ou null.")
    total_charges_exploitation: float | None = Field(description="Total des charges d'exploitation, ou null.")
    resultat_exploitation: float | None = Field(
        description="Résultat d'exploitation (peut être négatif), ou null."
    )
    # Financier, exceptionnel, impôt
    produits_financiers: float | None = Field(description="Total des produits financiers, ou null.")
    charges_financieres: float | None = Field(description="Total des charges financières, ou null.")
    interets_charges_assimilees: float | None = Field(
        description="Intérêts et charges assimilées (inclus dans les charges financières), ou null."
    )
    resultat_financier: float | None = Field(description="Résultat financier (peut être négatif), ou null.")
    produits_exceptionnels: float | None = Field(description="Total des produits exceptionnels, ou null.")
    charges_exceptionnelles: float | None = Field(description="Total des charges exceptionnelles, ou null.")
    resultat_exceptionnel: float | None = Field(description="Résultat exceptionnel (peut être négatif), ou null.")
    participation_salaries: float | None = Field(description="Participation des salariés aux résultats, ou null.")
    impots_benefices: float | None = Field(
        description="Impôts sur les bénéfices (peut être négatif en cas de crédit d'impôt), ou null."
    )
    # Totaux
    total_produits: float | None = Field(description="Total des produits, ou null.")
    total_charges: float | None = Field(description="Total des charges, ou null.")
    resultat_net: float | None = Field(
        description="Résultat de l'exercice (bénéfice positif, perte négative), ou null."
    )


class RepartitionEffectif(Strict):
    categorie: str = Field(description="Catégorie de personnel recopiée telle quelle (cadres, employés, ouvriers...).")
    effectif: float | None = Field(description="Effectif de cette catégorie, ou null.")


class EngagementHorsBilan(Strict):
    nature: str = Field(description="Nature de l'engagement (caution, hypothèque, crédit-bail...), recopiée.")
    montant: float | None = Field(description="Montant de l'engagement, ou null.")


class Annexe(Strict):
    effectif_moyen: float | None = Field(description="Effectif moyen du personnel, ou null si non indiqué.")
    repartition_effectif: list[RepartitionEffectif] = Field(
        description="Effectif par catégorie s'il est détaillé. Liste vide sinon."
    )
    credit_bail_redevances_exercice: float | None = Field(
        description="Redevances de crédit-bail payées sur l'exercice N, ou null."
    )
    credit_bail_valeur_origine: float | None = Field(
        description="Valeur d'origine des biens pris en crédit-bail, ou null."
    )
    engagements_hors_bilan: list[EngagementHorsBilan] = Field(
        description="Engagements donnés hors bilan (hors crédit-bail). Liste vide si aucun."
    )


class ExtractionComptesAnnuels(Strict):
    type_document: Literal["comptes_annuels", "liasse_fiscale", "hors_sujet"] = Field(
        description="hors_sujet si le texte ne contient ni bilan ni compte de résultat."
    )
    unite: Literal["euros", "milliers_euros"] = Field(
        description="milliers_euros si le document indique des montants en milliers d'euros (k€, K€), sinon euros."
    )
    compte_resultat_present: bool = Field(
        description="false si le document ne contient que le bilan (compte de résultat absent ou confidentiel)."
    )
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
