"""
Extraction du texte d'une image par OCR (PaddleOCR).

Le modèle est lourd à charger : il est instancié une seule fois, au premier appel, puis réutilisé.
"""
from functools import lru_cache

import numpy as np
from paddleocr import PaddleOCR


class OcrExtractionError(Exception):
    """L'OCR n'a pas pu traiter l'image."""


@lru_cache(maxsize=1)
def get_ocr_engine() -> PaddleOCR:
    """Charge le modèle PaddleOCR (français) au premier appel."""
    return PaddleOCR(
        lang='fr',
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def ocr_image(image: np.ndarray) -> str:
    """Retourne le texte reconnu sur une image BGR, une ligne détectée par ligne de texte."""
    try:
        results = get_ocr_engine().predict(image)
    except Exception as exc:
        raise OcrExtractionError(f'OCR impossible : {exc}') from exc
    return '\n'.join(text for result in results for text in result['rec_texts'])
