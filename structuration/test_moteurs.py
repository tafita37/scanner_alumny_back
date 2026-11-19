"""
Tests du moteur de calcul du cockpit : ni base de données ni LLM.
Lancement : python manage.py test structuration.test_moteurs
"""
from unittest import TestCase

from .moteurs import (
    MANQUANT,
    NON_DEFINI,
    OK,
    calculer_cockpit,
    calculs_services,
    entrees_a_demander,
)

COMPTES = {
    "date_cloture": "2025-12-31",
    "duree_exercice_mois": 12,
    "masse_salariale_annuelle": 704000.0,
    "masse_salariale_mensuelle": 58666.67,
    "stocks": 120000.0,
    "dotations_amortissements": 35000.0,
    "installations_techniques_brut": 400000.0,
    "installations_techniques_net": 150000.0,
}

QUESTIONNAIRE_NON_COMMENCE = {"tours_ok": 0, "dernier_tour_vide": False}
QUESTIONNAIRE_TERMINE = {"tours_ok": 2, "dernier_tour_vide": True}


def indicateurs(comptes=COMPTES, documents=None, effectif=(12, "comptes_annuels"), pris=4, a_verifier=0) -> dict:
    return {
        "documents_pris_en_compte": pris,
        "documents_a_verifier": a_verifier,
        "chiffre_affaires": {"valeur": 1500000, "source": "api"},
        "resultat_net": {"valeur": 50000, "source": "api"},
        "effectif": {"valeur": effectif[0], "source": effectif[1]},
        "documents_commerciaux": documents,
        "comptes_annuels": comptes,
    }


DOCUMENTS_BTP = {
    "taux_horaire_main_oeuvre": 42.0,
    "heures_main_oeuvre": 120,
    "conditions_de_paiement": {"acompte_pourcentage_moyen": 30.0, "delai_reglement_jours_moyen": 75.0},
    "documents_achat_exclus": 1,
}


def par_cle(liste: list[dict]) -> dict:
    return {e["cle"]: e for e in liste}


class BTPTests(TestCase):

    def test_entrees_depuis_comptes_documents_et_parametres(self):
        cockpit = calculer_cockpit("BTP", indicateurs(documents=DOCUMENTS_BTP), {}, QUESTIONNAIRE_NON_COMMENCE)
        entrees = par_cle(cockpit["entrees"])
        self.assertEqual(cockpit["secteur"], "BTP")
        self.assertEqual((entrees["effectif"]["valeur"], entrees["effectif"]["source"]), (12, "comptes_annuels"))
        self.assertEqual(entrees["masse_salariale_mensuelle"]["valeur"], 58666.67)
        self.assertEqual(entrees["coefficient_improductivite"]["source"], "parametre")
        self.assertEqual(entrees["coefficient_improductivite"]["valeur"], 20)
        self.assertEqual((entrees["taux_horaire_facture"]["valeur"], entrees["taux_horaire_facture"]["source"]),
                         (42.0, "documents"))
        self.assertEqual(entrees["delai_reglement_moyen"]["valeur"], 75.0)
        self.assertEqual(entrees["acompte_moyen"]["valeur"], 30.0)
        self.assertEqual(entrees["charges_fixes_structure"]["statut"], NON_DEFINI)
        self.assertEqual(entrees["volume_heures_mensuel"]["statut"], MANQUANT)
        self.assertEqual(entrees["heures_facturables_mensuelles"]["statut"], MANQUANT)
        self.assertTrue(all("lignes" in e for e in cockpit["entrees"]))
        self.assertEqual([e["libelle"] for e in cockpit["etapes_calcul"]],
                         ["Masse salariale mensuelle", "Taux horaire facturé"])

    def test_indicateurs_et_perte_sans_formule_inventee(self):
        cockpit = calculer_cockpit("BTP", indicateurs(documents=DOCUMENTS_BTP), {}, QUESTIONNAIRE_NON_COMMENCE)
        ind = par_cle(cockpit["indicateurs"])
        self.assertIsNone(ind["chr"]["valeur"])
        self.assertEqual(ind["chr"]["statut"], MANQUANT)
        self.assertEqual(ind["chr"]["manquants"], ["charges_fixes_structure", "heures_facturables_mensuelles"])
        self.assertTrue(ind["chr"]["pivot"])
        self.assertEqual(ind["chr"]["comparaison"], "taux horaire facturé : 42 €/h")
        self.assertEqual(ind["emo"]["manquants"],
                         ["volume_heures_mensuel", "charges_fixes_structure", "heures_facturables_mensuelles"])
        self.assertEqual(ind["indice_bfr"]["statut"], NON_DEFINI)
        perte = cockpit["perte_annuelle"]
        self.assertEqual((perte["valeur"], perte["partielle"]), (None, True))
        self.assertEqual([c["statut"] for c in perte["composantes"]], [MANQUANT, NON_DEFINI, NON_DEFINI])
        self.assertIsNone(cockpit["score_sante"])

    def test_chr_reste_non_defini_meme_avec_toutes_les_entrees(self):
        reponses = {
            "heures_facturables_mensuelles": {"statut": "repondue", "valeur": 1300, "tour": 1},
            "volume_heures_mensuel": {"statut": "repondue", "valeur": 1500, "tour": 1},
        }
        cockpit = calculer_cockpit("BTP", indicateurs(documents=DOCUMENTS_BTP), reponses, QUESTIONNAIRE_TERMINE)
        chr_ = par_cle(cockpit["indicateurs"])["chr"]
        # Seules les charges fixes (non définies) manquent encore
        self.assertEqual(chr_["manquants"], ["charges_fixes_structure"])

    def test_sans_comptes_ni_documents(self):
        cockpit = calculer_cockpit("BTP", indicateurs(comptes=None, documents=None, effectif=(9, "api"), pris=0),
                                   {}, QUESTIONNAIRE_NON_COMMENCE)
        entrees = par_cle(cockpit["entrees"])
        self.assertEqual((entrees["effectif"]["valeur"], entrees["effectif"]["source"]), (9, "api"))
        self.assertEqual(entrees["masse_salariale_mensuelle"]["statut"], MANQUANT)
        self.assertIn("comptes annuels non fournis", entrees["masse_salariale_mensuelle"]["detail"])
        self.assertEqual(entrees["taux_horaire_facture"]["statut"], MANQUANT)
        self.assertIn("aucun document commercial", entrees["taux_horaire_facture"]["detail"])
        self.assertEqual(cockpit["etapes_calcul"], [])

    def test_documents_d_achat_seulement(self):
        cockpit = calculer_cockpit("BTP", indicateurs(documents={"documents_achat_exclus": 2}), {},
                                   QUESTIONNAIRE_NON_COMMENCE)
        self.assertIn("documents d'achat", par_cle(cockpit["entrees"])["taux_horaire_facture"]["detail"])


class ReponsesTests(TestCase):

    def test_reponse_du_dirigeant_prioritaire_sur_les_documents(self):
        reponses = {
            "taux_horaire_facture": {"statut": "repondue", "valeur": 48, "tour": 2},
            "volume_heures_mensuel": {"statut": "repondue", "valeur": 1500, "tour": 1},
        }
        cockpit = calculer_cockpit("BTP", indicateurs(documents=DOCUMENTS_BTP), reponses, QUESTIONNAIRE_TERMINE)
        entrees = par_cle(cockpit["entrees"])
        taux = entrees["taux_horaire_facture"]
        self.assertEqual((taux["valeur"], taux["source"], taux["statut"]), (48, "questionnaire", OK))
        self.assertEqual(taux["detail"], "réponse du dirigeant (tour 2) ; documents : 42 €/h")
        self.assertEqual(entrees["volume_heures_mensuel"]["source"], "questionnaire")
        # L'étape de calcul du taux tiré des documents disparaît
        self.assertNotIn("Taux horaire facturé", [e["libelle"] for e in cockpit["etapes_calcul"]])

    def test_reponses_non_appliquees(self):
        reponses = {
            "volume_heures_mensuel": {"statut": "ignoree", "valeur": None, "tour": 1},
            "coefficient_improductivite": {"statut": "repondue", "valeur": 35, "tour": 1},
            "charges_fixes_structure": {"statut": "repondue", "valeur": 9000, "tour": 1},
            "heures_facturables_mensuelles": {"statut": "repondue", "valeur": "beaucoup", "tour": 1},
        }
        entrees = par_cle(calculer_cockpit("BTP", indicateurs(documents=DOCUMENTS_BTP), reponses,
                                           QUESTIONNAIRE_TERMINE)["entrees"])
        self.assertEqual(entrees["volume_heures_mensuel"]["statut"], MANQUANT)
        self.assertEqual(entrees["coefficient_improductivite"]["valeur"], 20)
        self.assertEqual(entrees["charges_fixes_structure"]["statut"], NON_DEFINI)
        self.assertEqual(entrees["heures_facturables_mensuelles"]["statut"], MANQUANT)

    def test_entrees_a_demander(self):
        cockpit = calculer_cockpit("BTP", indicateurs(documents=DOCUMENTS_BTP), {}, QUESTIONNAIRE_NON_COMMENCE)
        a_demander = par_cle(entrees_a_demander(cockpit["entrees"], {}))
        # Manquantes : obligatoires ; tirées des documents : à confirmer ; comptes, paramètre et
        # non défini : jamais proposés
        self.assertEqual({c for c, e in a_demander.items() if e["obligatoire"]},
                         {"heures_facturables_mensuelles", "volume_heures_mensuel"})
        self.assertEqual({c for c, e in a_demander.items() if not e["obligatoire"]},
                         {"taux_horaire_facture", "delai_reglement_moyen", "acompte_moyen"})
        self.assertEqual(set(a_demander["volume_heures_mensuel"]), {"cle", "label", "unite", "valeur", "source",
                                                                    "obligatoire"})
        # Déjà demandée (même ignorée) : plus proposée
        reponses = {"volume_heures_mensuel": {"statut": "ignoree", "valeur": None, "tour": 1}}
        self.assertNotIn("volume_heures_mensuel", par_cle(entrees_a_demander(cockpit["entrees"], reponses)))


class ControlesTests(TestCase):

    def textes(self, ind, reponses, questionnaire):
        return {c["texte"]: c["ok"] for c in calculer_cockpit("BTP", ind, reponses, questionnaire)["controles"]}

    def test_controles(self):
        textes = self.textes(indicateurs(documents=DOCUMENTS_BTP, a_verifier=1), {}, QUESTIONNAIRE_NON_COMMENCE)
        self.assertEqual(textes, {
            "Secteur BTP choisi à l'onboarding": True,
            "Comptes annuels présents (exercice clos le 31/12/2025)": True,
            "4 document(s) pris en compte": True,
            "1 document(s) à vérifier": False,
            "1 document(s) d'achat (fournisseurs) exclus des prix de vente": True,
            "Questionnaire de l'agent pas encore commencé": False,
        })

    def test_questionnaire_termine_avec_entrees_a_demander(self):
        textes = self.textes(indicateurs(documents=DOCUMENTS_BTP), {}, QUESTIONNAIRE_TERMINE)
        self.assertIn("Questionnaire terminé, mais il reste à demander : heures facturables réelles par mois, "
                      "volume d'heures mensuel (tour supplémentaire possible)", textes)

    def test_questionnaire_termine_et_question_ignoree(self):
        reponses = {
            "heures_facturables_mensuelles": {"statut": "repondue", "valeur": 1300, "tour": 1},
            "volume_heures_mensuel": {"statut": "ignoree", "valeur": None, "tour": 1},
        }
        textes = self.textes(indicateurs(documents=DOCUMENTS_BTP), reponses, QUESTIONNAIRE_TERMINE)
        self.assertTrue(textes["Questionnaire de l'agent terminé"])
        self.assertFalse(textes["Question ignorée par le dirigeant : volume d'heures mensuel"])

    def test_questionnaire_en_cours(self):
        textes = self.textes(indicateurs(), {}, {"tours_ok": 1, "dernier_tour_vide": False})
        self.assertFalse(textes["Questionnaire de l'agent non terminé"])


class ServicesTests(TestCase):

    def test_entrees(self):
        documents = {"tjm_vendu_regie": 650.0, "tjm_implicite_forfaits": None,
                     "conditions_de_paiement": {"acompte_pourcentage_moyen": None, "delai_reglement_jours_moyen": 45}}
        cockpit = calculer_cockpit("SERVICES", indicateurs(documents=documents), {}, QUESTIONNAIRE_NON_COMMENCE)
        entrees = par_cle(cockpit["entrees"])
        self.assertEqual(entrees["tjm_vendu_regie"]["valeur"], 650.0)
        self.assertEqual(entrees["tjm_implicite_forfaits"]["statut"], MANQUANT)
        for cle in ("heures_vendues_mensuelles", "taux_occupation", "heures_hors_forfait_mensuelles",
                    "heures_execution_dirigeant_mensuelles"):
            self.assertEqual(entrees[cle]["statut"], MANQUANT, cle)
        cout = par_cle(cockpit["indicateurs"])["cout_du_temps"]
        self.assertEqual(cout["manquants"], ["charges_fixes_structure", "heures_vendues_mensuelles"])
        self.assertEqual(cockpit["perte_annuelle"]["valeur"], None)

    def test_cout_du_temps_calcule_quand_toutes_les_entrees_sont_connues(self):
        # Formule du cahier des charges ; les charges fixes sont forcées ici (non définies en vrai).
        def entree(valeur):
            return {"valeur": valeur, "statut": OK, "unite": "€"}
        valeurs = {
            "masse_salariale_mensuelle": entree(50000), "charges_fixes_structure": entree(10000),
            "heures_vendues_mensuelles": entree(800), "tjm_vendu_regie": entree(650),
            "delai_reglement_moyen": entree(45), "taux_occupation": entree(70),
            "heures_hors_forfait_mensuelles": entree(20), "heures_execution_dirigeant_mensuelles": entree(60),
        }
        indicateurs_services, _ = calculs_services(valeurs)
        cout = par_cle(indicateurs_services)["cout_du_temps"]
        self.assertEqual((cout["valeur"], cout["statut"]), (75.0, OK))
        # Conversion heure → jour non définie : l'écart de TJM ne se calcule pas
        self.assertEqual(par_cle(indicateurs_services)["ecart_tjm"]["statut"], NON_DEFINI)


class IndustrieTests(TestCase):

    MARGES = [
        {"produit": "Panneau A", "reference": "PA", "prix_unitaire_ht": 100.0, "couts_variables_unitaires": 60.0,
         "marge_unitaire": 40.0, "taux_marge": 40.0, "quantite": 10, "marge_totale": 400.0},
        {"produit": "Panneau B", "reference": "PB", "prix_unitaire_ht": 50.0, "couts_variables_unitaires": 45.0,
         "marge_unitaire": 5.0, "taux_marge": 10.0, "quantite": 20, "marge_totale": 100.0},
        {"produit": "Panneau C", "reference": "PC", "prix_unitaire_ht": 80.0, "couts_variables_unitaires": 70.0,
         "marge_unitaire": 10.0, "taux_marge": 12.5, "quantite": None, "marge_totale": None},
    ]

    def test_marges_et_comptes(self):
        cockpit = calculer_cockpit("INDUSTRIE", indicateurs(documents={"marges_sur_couts_variables": self.MARGES}),
                                   {}, QUESTIONNAIRE_NON_COMMENCE)
        entrees = par_cle(cockpit["entrees"])
        marge = entrees["marge_sur_couts_variables"]
        self.assertEqual((marge["valeur"], marge["source"]), (500.0, "documents"))
        self.assertEqual(len(marge["lignes"]), 3)
        self.assertIn("1 sans quantité", marge["detail"])
        self.assertEqual(entrees["stocks"]["valeur"], 120000.0)
        self.assertEqual(entrees["installations_techniques_net"]["source"], "comptes_annuels")
        taux = par_cle(cockpit["indicateurs"])["taux_marge_sur_couts_variables"]
        # (400 + 100) ÷ (100 × 10 + 50 × 20) = 25 %
        self.assertEqual((taux["valeur"], taux["statut"]), (25.0, OK))
        self.assertEqual(par_cle(cockpit["indicateurs"])["trs"]["statut"], NON_DEFINI)
        # Marge, dotations et installations : jamais demandées au dirigeant
        a_demander = {e["cle"] for e in entrees_a_demander(cockpit["entrees"], {})}
        self.assertEqual(a_demander, {"cout_non_qualite_annuel", "heures_arret_machine_mensuelles",
                                      "delai_reglement_moyen", "acompte_moyen"})

    def test_cout_non_qualite_dans_la_perte(self):
        reponses = {"cout_non_qualite_annuel": {"statut": "repondue", "valeur": 18000, "tour": 1}}
        cockpit = calculer_cockpit("INDUSTRIE", indicateurs(), reponses, QUESTIONNAIRE_NON_COMMENCE)
        perte = cockpit["perte_annuelle"]
        self.assertEqual((perte["valeur"], perte["partielle"]), (18000, True))

    def test_sans_document(self):
        entrees = par_cle(calculer_cockpit("INDUSTRIE", indicateurs(comptes=None), {},
                                           QUESTIONNAIRE_NON_COMMENCE)["entrees"])
        self.assertEqual(entrees["marge_sur_couts_variables"]["statut"], MANQUANT)
        self.assertEqual(entrees["stocks"]["detail"], "comptes annuels non fournis : à demander au dirigeant")
        self.assertEqual(entrees["dotations_amortissements"]["detail"], "comptes annuels non fournis")


class SecteurTests(TestCase):

    def test_secteur_inconnu(self):
        with self.assertRaises(ValueError):
            calculer_cockpit("AGRICULTURE", indicateurs(), {}, QUESTIONNAIRE_NON_COMMENCE)
