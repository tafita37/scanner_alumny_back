"""
Tests de la validation des textes du rapport et de la boucle de rédaction (LLM simulé) : ni base de
données ni appel au LLM.
Lancement : python manage.py test rapport.tests
"""
from unittest import TestCase
from unittest.mock import patch

from langchain_core.messages import AIMessage

from . import redaction
from .schemas import RapportRedige
from .validation import montant_connu, montants_autorises, montants_cites, valider_rapport

INDICATEURS = ["chr", "emo", "indice_bfr"]
DONNEES = {
    "donnees_publiees": {"chiffre_affaires": 1500000, "resultat_net": 50000, "effectif": 12},
    "cockpit": {
        "secteur": "BTP",
        "indicateurs": [{"cle": cle} for cle in INDICATEURS],
        "perte_annuelle": {"valeur": 47800.0, "partielle": True},
        "entrees": [{"cle": "masse_salariale_mensuelle", "valeur": 58666.67, "statut": "ok"}],
    },
}


def levier(**champs) -> dict:
    return {
        "titre": "Facturer les travaux supplémentaires",
        "constat": "Des travaux hors devis ne sont pas facturés.",
        "actions": ["Faire signer un avenant avant tout travail supplémentaire.", "Relire les situations chaque mois."],
        "gain_attendu": "Une partie des 47 800 € de perte annuelle.",
        "indicateur_suivi": "Nombre d'avenants signés.",
    } | champs


def rapport(**champs) -> dict:
    return {
        "synthese_executive": ["Premier paragraphe.", "  Second paragraphe.  "],
        "points_cles": ["Point 1.", "Point 2.", "Point 3."],
        "commentaire_perte": "La perte est partielle.",
        "commentaires_indicateurs": [{"cle": cle, "commentaire": "Commentaire."} for cle in reversed(INDICATEURS)],
        "leviers": [levier(), levier(), levier()],
        "message_conclusion": "Réservez votre bilan.",
    } | champs


def valider(sortie: dict):
    return valider_rapport(sortie, INDICATEURS, DONNEES)


class MontantsTests(TestCase):

    def test_formats_reconnus(self):
        cas = {
            "perte de 47 800 € par an": 47800,
            "perte de 47 800 € par an": 47800,
            "perte de 47 800 € par an": 47800,
            "soit 47800 euros": 47800,
            "masse de 58 666,67 € par mois": 58666.67,
            "environ 48 k€": 48000,
            "un CA de 1,5 M€": 1500000,
            "1,5 million d'euros": 1500000,
            "12.000 €": 12000,
            "12.5 €": 12.5,
            "40 EUR": 40,
        }
        for texte, attendu in cas.items():
            with self.subTest(texte=texte):
                montants = montants_cites(texte)
                self.assertEqual(len(montants), 1, montants)
                self.assertAlmostEqual(montants[0][1], attendu)

    def test_nombres_sans_euros_ignores(self):
        self.assertEqual(montants_cites("30 % d'acompte, 75 jours de délai, 120 heures, année 2025"), [])

    def test_montants_autorises(self):
        autorises = montants_autorises(DONNEES)
        self.assertTrue(montant_connu(47800, autorises))
        self.assertTrue(montant_connu(48000, autorises))          # arrondi
        self.assertTrue(montant_connu(58666.67 * 12, autorises))  # mensuel -> annuel
        self.assertTrue(montant_connu(47800 / 12, autorises))     # annuel -> mensuel
        self.assertTrue(montant_connu(40, autorises))             # indemnité forfaitaire légale
        self.assertFalse(montant_connu(25000, autorises))
        self.assertFalse(montant_connu(3000, autorises))


class ValidationTests(TestCase):

    def test_rapport_valide_nettoye_et_reordonne(self):
        resultat, erreurs = valider(rapport())
        self.assertEqual(erreurs, [])
        self.assertEqual(resultat["synthese_executive"][1], "Second paragraphe.")
        self.assertEqual([c["cle"] for c in resultat["commentaires_indicateurs"]], INDICATEURS)

    def test_nombre_de_leviers_et_d_actions(self):
        _, erreurs = valider(rapport(leviers=[levier(), levier()]))
        self.assertTrue(any("exactement 3" in e for e in erreurs))
        _, erreurs = valider(rapport(leviers=[levier(actions=["Une seule."]), levier(), levier()]))
        self.assertTrue(any("leviers[1].actions" in e for e in erreurs))

    def test_commentaires_des_indicateurs(self):
        commentaires = [{"cle": "chr", "commentaire": "A."}, {"cle": "chr", "commentaire": "B."},
                        {"cle": "inconnu", "commentaire": "C."}]
        _, erreurs = valider(rapport(commentaires_indicateurs=commentaires))
        texte = " ".join(erreurs)
        self.assertIn("deux fois", texte)
        self.assertIn("« inconnu » n'est pas un indicateur", texte)
        self.assertIn("sans commentaire : emo, indice_bfr", texte)

    def test_montant_invente(self):
        _, erreurs = valider(rapport(leviers=[levier(gain_attendu="Jusqu'à 25 000 € récupérés."), levier(), levier()]))
        self.assertEqual(len(erreurs), 1)
        self.assertIn("leviers[1].gain_attendu", erreurs[0])
        self.assertIn("25 000 €", erreurs[0])

    def test_texte_vide_et_mentions_internes(self):
        _, erreurs = valider(rapport(
            commentaire_perte="  ",
            message_conclusion="Méthode à valider avec Ny Aina.",
            points_cles=["L'indicateur reste non défini.", "Point 2.", "Il manque masse_salariale_mensuelle."],
        ))
        texte = " ".join(erreurs)
        self.assertIn("commentaire_perte : texte vide", texte)
        self.assertIn("message_conclusion : « Ny Aina »", texte)
        self.assertIn("points_cles[1] : « non défini »", texte)
        self.assertIn("points_cles[3] : clé technique « masse_salariale_mensuelle »", texte)

    def test_texte_trop_long(self):
        _, erreurs = valider(rapport(points_cles=["mot " * 21, "Point 2.", "Point 3."]))
        self.assertEqual(len(erreurs), 1)
        self.assertIn("points_cles[1] : 21 mots, 20 au plus", erreurs[0])


class FakeLLM:
    """Renvoie les sorties prévues, une par appel, au format de `with_structured_output(include_raw=True)`."""

    def __init__(self, *sorties):
        self.sorties = list(sorties)
        self.appels = []

    def invoke(self, messages):
        self.appels.append(list(messages))
        brut = AIMessage("", usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
        return {"raw": brut, "parsed": RapportRedige.model_validate(self.sorties.pop(0)), "parsing_error": None}


class RedactionTests(TestCase):

    def rediger(self, *sorties):
        llm = FakeLLM(*sorties)
        with patch.object(redaction, "_llm", return_value=llm):
            return redaction.rediger_rapport(DONNEES), llm

    def test_premier_essai_valide(self):
        etat, llm = self.rediger(rapport())
        self.assertEqual(etat["statut"], "ok")
        self.assertEqual((etat["tokens_entree"], etat["tokens_sortie"]), (100, 10))
        self.assertEqual(len(llm.appels), 1)

    def test_nouvel_essai_avec_les_erreurs(self):
        invente = rapport(commentaire_perte="Perte de 99 999 €.")
        etat, llm = self.rediger(invente, rapport())
        self.assertEqual(etat["statut"], "ok")
        self.assertEqual(etat["tokens_entree"], 200)
        dernier = llm.appels[1][-1].content
        self.assertIn("99 999 €", dernier)  # l'erreur est renvoyée au LLM, avec sa réponse précédente
        self.assertIsInstance(llm.appels[1][-2], AIMessage)

    def test_echec_apres_le_dernier_essai(self):
        invente = rapport(commentaire_perte="Perte de 99 999 €.")
        etat, _ = self.rediger(invente, invente)
        self.assertEqual(etat["statut"], "erreur")
        self.assertIsNone(etat["resultat"])
        self.assertEqual(len(etat["erreurs"]), 2)
