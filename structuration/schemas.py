"""Schémas de sortie du LLM, un par secteur.

Compatibles avec le mode strict de Groq (Structured Outputs) :
- extra="forbid"  -> "additionalProperties": false dans le JSON Schema
- aucun champ n'a de valeur par défaut -> tous les champs sont "required"
- une valeur absente est représentée par null (type X | None)
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Champs communs aux trois secteurs (pied du document)
class PiedDocument(Strict):
    total_ht: float | None = Field(description="Total HT du document, ou null.")
    total_ttc: float | None = Field(description="Total TTC du document, ou null.")
    acompte_pourcentage: float | None = Field(
        description="Acompte demandé en pourcentage (exemple 30 pour 30 %), ou null si non mentionné."
    )
    delai_reglement_jours: int | None = Field(
        description="Délai de règlement en jours (exemple 30 pour '30 jours fin de mois'), ou null si non mentionné. Si la date d'écheance est indiquée, le délai est calculé à partir de la date de facture et renvoyé ici."
    )
    
# Champs communs aux lignes des trois secteurs
class LigneChiffree(Strict):
    libelle: str = Field(description="Libellé de la ligne, recopié tel quel.")
    quantite: float | None = Field(description="Quantité de la ligne, ou null.")
    unite: str | None = Field(description="Unité recopiée telle quelle (h, m2, u, jour, ens...), ou null.")
    prix_unitaire_ht: float | None = Field(description="Prix unitaire HT, ou null.")
    total_ht: float | None = Field(description="Montant HT de la ligne, ou null.")


# --------------------------------------------------------------------------- #
# BTP : devis, factures
# --------------------------------------------------------------------------- #

class LignePrestationBTP(LigneChiffree):
    nature: Literal["main_oeuvre", "fourniture", "autre"] = Field(
        description=(
            "main_oeuvre : temps de travail facturé (pose, heures, journée d'ouvrier). "
            "fourniture : matériel, matériaux, équipements. "
            "autre : déplacement, location, évacuation, forfait mixte ou ligne indéterminée."
        )
    )


class ExtractionBTP(PiedDocument):
    type_document: Literal["devis", "facture", "hors_sujet"] = Field(
        description="hors_sujet si le texte n'est ni un devis ni une facture."
    )
    lignes: list[LignePrestationBTP] = Field(
        description="Toutes les lignes de prestation, dans l'ordre du document. Liste vide si hors_sujet."
    )


# --------------------------------------------------------------------------- #
# SERVICES : propositions commerciales, TJM, forfaits
# --------------------------------------------------------------------------- #

class LignePrestationServices(LigneChiffree):
    mode_facturation: Literal["regie_jour", "regie_heure", "forfait", "autre"] = Field(
        description=(
            "regie_jour : facturé au jour (TJM). regie_heure : facturé à l'heure. "
            "forfait : prix global pour un livrable ou une mission. autre : frais, déplacements, licences."
        )
    )
    jours_estimes: float | None = Field(
        description="Pour un forfait : charge en jours indiquée dans le document, sinon null."
    )

class ExtractionServices(PiedDocument):
    type_document: Literal["proposition_commerciale", "devis", "facture", "hors_sujet"] = Field(
        description="hors_sujet si le texte n'est ni une proposition commerciale, ni un devis, ni une facture."
    )
    lignes: list[LignePrestationServices] = Field(
        description="Toutes les lignes de prestation, dans l'ordre du document. Liste vide si hors_sujet."
    )


# --------------------------------------------------------------------------- #
# INDUSTRIE : bons de commande, fiches de prix de revient
# --------------------------------------------------------------------------- #

class LigneCommande(LigneChiffree):
    reference: str | None = Field(description="Référence produit, ou null.")

class FichePrixRevient(Strict):
    produit: str | None = Field(description="Nom ou référence du produit, ou null.")
    quantite_reference: float | None = Field(
        description="Nombre d'unités pour lequel les coûts sont donnés (1 si coût unitaire), ou null."
    )
    cout_matiere: float | None = Field(description="Coût des matières premières et composants, ou null.")
    cout_main_oeuvre: float | None = Field(description="Coût de main-d'œuvre de production, ou null.")
    cout_machine: float | None = Field(description="Coût machine (heures machine, énergie), ou null.")
    autres_couts: float | None = Field(description="Autres coûts (frais généraux, sous-traitance), ou null.")
    cout_revient_total: float | None = Field(description="Coût de revient total indiqué, ou null.")
    prix_vente: float | None = Field(description="Prix de vente indiqué pour la même quantité, ou null.")


class ExtractionIndustrie(PiedDocument):
    type_document: Literal["bon_de_commande", "fiche_prix_revient", "facture", "hors_sujet"] = Field(
        description="hors_sujet si le texte n'est ni un bon de commande, ni une fiche de prix de revient, ni une facture."
    )
    lignes_commande: list[LigneCommande] = Field(
        description="Lignes d'un bon de commande ou d'une facture. Liste vide pour une fiche de prix de revient."
    )
    fiches_prix_revient: list[FichePrixRevient] = Field(
        description="Une entrée par produit d'une fiche de prix de revient. Liste vide sinon."
    )


# --------------------------------------------------------------------------- #
# COMPTES ANNUELS : bilan + compte de résultat (tous secteurs), exercice N seulement
# --------------------------------------------------------------------------- #

class ExtractionComptesAnnuels(Strict):
    type_document: Literal["comptes_annuels", "liasse_fiscale", "hors_sujet"] = Field(
        description="hors_sujet si le texte ne contient ni bilan ni compte de résultat."
    )
    date_cloture: str | None = Field(description="Date de clôture de l'exercice N au format AAAA-MM-JJ, ou null.")
    duree_exercice_mois: int | None = Field(description="Durée de l'exercice N en mois (souvent 12), ou null.")
    unite: Literal["euros", "milliers_euros"] = Field(
        description="milliers_euros si le document indique des montants en milliers d'euros (k€, K€), sinon euros."
    )
    compte_resultat_present: bool = Field(
        description="false si le document ne contient que le bilan (compte de résultat absent ou confidentiel)."
    )

    # Bilan
    installations_techniques_brut: float | None = Field(
        description="Installations techniques, matériel et outillage : montant brut de l'exercice N, ou null."
    )
    installations_techniques_net: float | None = Field(
        description="Installations techniques, matériel et outillage : montant net de l'exercice N, ou null."
    )
    stocks: float | None = Field(description="Total des stocks et en-cours, montant net de l'exercice N, ou null.")
    creances_clients: float | None = Field(
        description="Clients et comptes rattachés, montant net de l'exercice N, ou null."
    )
    dettes_fournisseurs: float | None = Field(
        description="Dettes fournisseurs et comptes rattachés de l'exercice N, ou null."
    )
    total_actif: float | None = Field(description="Total général de l'actif (net) de l'exercice N, ou null.")
    total_passif: float | None = Field(description="Total général du passif de l'exercice N, ou null.")

    # Compte de résultat
    chiffre_affaires: float | None = Field(description="Chiffre d'affaires net de l'exercice N, ou null.")
    achats_matieres_premieres: float | None = Field(
        description="Achats de matières premières et autres approvisionnements de l'exercice N, ou null."
    )
    variation_stock_matieres: float | None = Field(
        description="Variation de stock de matières premières et approvisionnements de l'exercice N "
                    "(peut être négative), ou null."
    )
    autres_achats_charges_externes: float | None = Field(
        description="Autres achats et charges externes de l'exercice N, ou null."
    )
    impots_taxes: float | None = Field(description="Impôts, taxes et versements assimilés de l'exercice N, ou null.")
    salaires_traitements: float | None = Field(
        description="Salaires et traitements de l'exercice N. Si une seule ligne regroupe salaires et charges "
                    "sociales (charges de personnel), mets-la ici, ou null."
    )
    charges_sociales: float | None = Field(
        description="Charges sociales de l'exercice N, ou null si absentes ou regroupées avec les salaires."
    )
    dotations_amortissements: float | None = Field(
        description="Dotations aux amortissements (sur immobilisations) de l'exercice N, ou null."
    )
    total_produits: float | None = Field(description="Total des produits de l'exercice N, ou null.")
    total_charges: float | None = Field(description="Total des charges de l'exercice N, ou null.")
    resultat_net: float | None = Field(
        description="Résultat de l'exercice N (bénéfice positif, perte négative), ou null."
    )
    effectif_moyen: float | None = Field(description="Effectif moyen du personnel, ou null si non indiqué.")


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