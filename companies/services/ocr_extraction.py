"""
Extraction du texte d'une image par OCR (PaddleOCR).

Le modèle est lourd à charger : il est instancié une seule fois, au premier appel, puis réutilisé.

PaddleOCR tourne dans un processus séparé du serveur Django, OCR_EXECUTOR : sa forte consommation
mémoire ne s'ajoute pas à celle du serveur (spaCy pour l'anonymisation), et s'il plante, seul ce
processus meurt et il est remplacé au prochain appel, sans faire tomber le serveur.
"""
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import lru_cache

import numpy as np
from paddleocr import PaddleOCR

# Taille maximale (en pixels, plus grand côté) de l'image analysée par la détection de texte.
# Sans limite, une page A4 rendue à 300 dpi (3508 × 2481) est analysée en pleine résolution et
# consomme jusqu'à 13 Go de mémoire : l'OCR échoue ou plante dès que la machine en manque.
# À 1600 : ~5 Go et ~6 s par page, pour un texte reconnu équivalent.
OCR_DET_MAX_SIDE = 1600

# Processus dédié à l'OCR, démarré au premier appel. Les OCR demandés en même temps par
# plusieurs requêtes passent l'un après l'autre.
OCR_EXECUTOR = ProcessPoolExecutor(max_workers=1)


class OcrExtractionError(Exception):
    """L'OCR n'a pas pu traiter l'image."""


@lru_cache(maxsize=1)
def get_ocr_engine() -> PaddleOCR:
    """
    Charge le modèle PaddleOCR (français) au premier appel.
    À n'appeler que dans le processus OCR_EXECUTOR (voir run_ocr).
    """
    return PaddleOCR(
        lang='fr',
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_type='max',
        text_det_limit_side_len=OCR_DET_MAX_SIDE,
    )


def run_ocr(image: np.ndarray) -> str:
    """Exécuté dans OCR_EXECUTOR : reconnaît le texte de l'image, une ligne détectée par ligne."""
    results = get_ocr_engine().predict(image)
    return '\n'.join(text for result in results for text in result['rec_texts'])


def ocr_image(image: np.ndarray) -> str:
    """
    Retourne le texte reconnu sur une image BGR, une ligne détectée par ligne de texte.
    Le travail est fait dans OCR_EXECUTOR ; l'appelant attend le résultat.
    """
    global OCR_EXECUTOR
    try:
        return OCR_EXECUTOR.submit(run_ocr, image).result()
    except BrokenProcessPool as exc:
        # Le processus OCR est mort (plantage de Paddle) : on en prépare un neuf pour les
        # appels suivants, sinon tous échoueraient jusqu'au redémarrage du serveur.
        OCR_EXECUTOR = ProcessPoolExecutor(max_workers=1)
        raise OcrExtractionError('OCR impossible : le processus OCR s\'est arrêté.') from exc
    except Exception as exc:
        raise OcrExtractionError(f'OCR impossible : {exc}') from exc
