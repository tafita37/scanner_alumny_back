"""
Tests de la validation des questions générées et du routage du graphe : ni base de données ni LLM.
Lancement : python manage.py test questionnaire.tests
"""
from unittest import TestCase

from .limites import MAX_ESSAIS_REDACTION, MAX_QUESTIONS
from .noeuds import apres_validation, validation
from .validation import convertir_reponse, valider_questions


def question(**champs) -> dict:
    return {
        "label": "Existe-t-il des avenants au devis ?",
        "rationale": "Travaux supplémentaires peut-être non facturés.",
        "answer_type": "oui_non",
        "choices": None,
        "unit": None,
        "variable": None,
        "document_ids": [12],
        "suggested_answer": None,
        "suggested_answer_source": None,
    } | champs


def valider(*questions, precedentes=(), entrees=()):
    return valider_questions({"analyse": " Analyse. ", "questions": list(questions)}, {12, 70, 73}, list(precedentes),
                             list(entrees))


ENTREES = [
    {"cle": "volume_heures_mensuel", "label": "Volume d'heures mensuel", "unite": "h", "valeur": None,
     "source": None, "obligatoire": True},
    {"cle": "taux_horaire_facture", "label": "Taux horaire facturé", "unite": "€/h", "valeur": 42,
     "source": "documents", "obligatoire": False},
]


class ConversionTests(TestCase):

    def test_nombres(self):
        self.assertEqual(convertir_reponse("montant", "340 000 €", None), 340000)
        self.assertEqual(convertir_reponse("montant", "1250,50", None), 1250.5)
        self.assertEqual(convertir_reponse("pourcentage", "5 %", None), 5)
        self.assertEqual(convertir_reponse("montant", "340000 EUR", None), 340000)
        self.assertEqual(convertir_reponse("nombre", "14", None), 14)
        for valeur in ("environ 14", "14 mois", "1.250.000"):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                convertir_reponse("nombre", valeur, None)

    def test_date(self):
        self.assertEqual(convertir_reponse("date", "2026-03-12", None), "2026-03-12")
        for valeur in ("12/03/2026", "2026-02-30"):
            with self.subTest(valeur=valeur), self.assertRaises(ValueError):
                convertir_reponse("date", valeur, None)

    def test_oui_non(self):
        self.assertIs(convertir_reponse("oui_non", "Oui", None), True)
        self.assertIs(convertir_reponse("oui_non", "non.", None), False)
        with self.assertRaises(ValueError):
            convertir_reponse("oui_non", "peut-être", None)

    def test_choix(self):
        options = ["Moins de 30 jours", "30 à 60 jours", "Plus de 60 jours"]
        self.assertEqual(convertir_reponse("choix", "plus de 60 jours", options), "Plus de 60 jours")
        with self.assertRaises(ValueError):
            convertir_reponse("choix", "90 jours", options)


class ValidationTests(TestCase):

    def test_question_valide_et_corrections_silencieuses(self):
        resultat, erreurs = valider(
            question(answer_type="montant", choices=["inutile"], document_ids=[12, 12],
                     suggested_answer="340 000", suggested_answer_source="Devis 12, page 1 : total HT 340 000 €"),
            question(label="Délai de paiement accordé ?", answer_type="nombre", unit="jours",
                     suggested_answer_source="sans réponse proposée"),
        )
        self.assertEqual(erreurs, [])
        self.assertEqual(resultat["analyse"], "Analyse.")
        premiere, seconde = resultat["questions"]
        self.assertEqual((premiere["choices"], premiere["unit"], premiere["document_ids"]), (None, "€", [12]))
        self.assertEqual(premiere["suggested_answer"], 340000)
        self.assertEqual((seconde["unit"], seconde["suggested_answer_source"]), ("jours", None))

    def test_liste_vide_questionnaire_termine(self):
        self.assertEqual(valider(), ({"analyse": "Analyse.", "questions": []}, []))

    def test_trop_de_questions(self):
        questions = [question(label=f"Question {i} ?") for i in range(MAX_QUESTIONS + 1)]
        self.assertTrue(any("au maximum" in e for e in valider(*questions)[1]))

    def test_doublons(self):
        erreurs = valider(question(), question(label="existe-t-il des AVENANTS au devis"))[1]
        self.assertTrue(any("en double" in e for e in erreurs))
        erreurs = valider(question(), precedentes=["Existe-t-il des avenants au devis ?"])[1]
        self.assertTrue(any("déjà posée" in e for e in erreurs))

    def test_erreurs(self):
        cas = {
            "documents [99] absents": question(document_ids=[12, 99]),
            "au moins deux options": question(answer_type="choix", choices=["Oui", " "]),
            "réponse proposée invalide": question(suggested_answer="peut-être", suggested_answer_source="Devis 12"),
            "sans source": question(suggested_answer="oui"),
            "justification vide": question(rationale="  "),
        }
        for message, q in cas.items():
            with self.subTest(message=message):
                erreurs = valider(q)[1]
                self.assertTrue(any(message in e for e in erreurs), erreurs)


class VariableTests(TestCase):

    def test_variable_valide_et_unite_imposee(self):
        resultat, erreurs = valider(
            question(label="Heures travaillées par mois ?", answer_type="nombre", unit="heures/mois",
                     variable=" volume_heures_mensuel "),
            question(label="Taux horaire réel ?", answer_type="montant", variable="taux_horaire_facture",
                     suggested_answer="42", suggested_answer_source="Devis 12, page 2"),
            question(),
            entrees=ENTREES,
        )
        self.assertEqual(erreurs, [])
        premiere, seconde, troisieme = resultat["questions"]
        self.assertEqual((premiere["variable"], premiere["unit"]), ("volume_heures_mensuel", "h"))
        self.assertEqual((seconde["variable"], seconde["unit"]), ("taux_horaire_facture", "€/h"))
        self.assertIsNone(troisieme["variable"])

    def test_erreurs_de_variable(self):
        cas = {
            "inconnue ou déjà demandée": [question(answer_type="nombre", variable="charges_fixes_structure")],
            "attend un nombre": [question(variable="volume_heures_mensuel")],
            "déjà rattachée": [question(answer_type="nombre", variable="volume_heures_mensuel"),
                               question(label="Autre ?", answer_type="nombre", variable="volume_heures_mensuel")],
        }
        for message, questions in cas.items():
            with self.subTest(message=message):
                erreurs = valider(*questions, entrees=ENTREES)[1]
                self.assertTrue(any(message in e for e in erreurs), erreurs)

    def test_pas_de_fin_tant_qu_il_reste_des_entrees_obligatoires(self):
        erreurs = valider(entrees=ENTREES)[1]
        self.assertEqual(len(erreurs), 1)
        self.assertIn("volume_heures_mensuel (Volume d'heures mensuel, en h)", erreurs[0])
        self.assertNotIn("taux_horaire_facture", erreurs[0])
        # Seulement des entrées à confirmer : le questionnaire peut s'arrêter
        self.assertEqual(valider(entrees=ENTREES[1:])[1], [])


class NoeudValidationTests(TestCase):

    def etat(self, sortie_brute, essais=1):
        return {
            "contexte": {"documents": [{"document_id": 12}], "documents_sans_extraction": [73]},
            "questions_precedentes": [{"tour": 1, "questions": [{"question": "Quel est le délai de paiement ?"}]}],
            "sortie_brute": sortie_brute, "essais_redaction": essais, "erreurs": [], "statut": "en_cours",
        }

    def test_ok(self):
        etat = self.etat({"analyse": "A", "questions": [question(document_ids=[12, 73])]})
        maj = validation(etat)
        self.assertEqual(maj["statut"], "ok")
        self.assertEqual(apres_validation(etat | maj), "fin")

    def test_erreur_puis_nouvel_essai_puis_echec(self):
        etat = self.etat({"analyse": "A", "questions": [question(label="Quel est le délai de paiement ?")]})
        maj = validation(etat)
        self.assertTrue(maj["erreurs_a_corriger"])
        self.assertEqual(apres_validation(etat | maj), "redaction")
        self.assertEqual(apres_validation(etat | maj | {"essais_redaction": MAX_ESSAIS_REDACTION}), "echec")

    def test_entrees_du_contexte(self):
        etat = self.etat({"analyse": "A", "questions": []})
        etat["contexte"]["entrees_a_demander"] = ENTREES
        self.assertTrue(any("volume_heures_mensuel" in e for e in validation(etat)["erreurs_a_corriger"]))

    def test_schema_invalide(self):
        maj = validation(self.etat({"analyse": "A", "questions": [question(answer_type="inconnu")]}))
        self.assertTrue(any(e.startswith("Schéma") for e in maj["erreurs_a_corriger"]))
