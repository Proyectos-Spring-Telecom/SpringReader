"""
Script para predescargar los modelos de PaddleOCR durante el deploy.

Uso:
    python preload_models.py

Ejecutar UNA VEZ antes de arrancar el servicio en producción para evitar
que la primera petición real sufra un timeout mientras se descargan los
modelos (~200 MB).
"""

import time
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from config import get_settings
    settings = get_settings()

    logger.info("=== SpringReader — Pre-descarga de modelos PaddleOCR ===")
    logger.info("Lang: %s  |  use_angle_cls: %s", settings.OCR_LANG, settings.OCR_USE_ANGLE_CLS)

    t0 = time.monotonic()

    try:
        from paddleocr import PaddleOCR

        logger.info("Iniciando PaddleOCR (descargará modelos si no están en caché)...")
        _ = PaddleOCR(
            use_gpu=False,
            show_log=False,
            lang=settings.OCR_LANG,
            use_angle_cls=settings.OCR_USE_ANGLE_CLS,
        )
        elapsed = time.monotonic() - t0
        logger.info("Modelos listos en %.2f s. Pre-carga completada.", elapsed)

    except ImportError:
        logger.error(
            "ERROR: paddleocr no está instalado. "
            "Ejecuta: pip install -r requirements.txt"
        )
        sys.exit(1)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "ERROR al descargar modelos después de %.2f s: %s", elapsed, exc
        )
        logger.error(
            "Posible causa: sin conexión a internet o repositorio de modelos no disponible. "
            "El servicio funcionará pero descargará los modelos en la primera petición."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
