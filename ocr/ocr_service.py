"""
Singleton PaddleOCR thread-safe con lazy loading y auto-descarga por inactividad.

Diseño:
- El modelo NO se carga al importar el módulo (lazy load).
- Un RLock serializa cada inferencia: PaddleOCR en CPU no es thread-safe
  y el servidor no dispone de RAM para inferencias concurrentes.
- Una tarea asyncio de fondo descarga el modelo tras OCR_UNLOAD_TIMEOUT
  segundos de inactividad, liberando ~400-500 MB de RAM.
- Un fallo durante la carga libera el lock para permitir reintentos.
- El import de paddleocr es diferido (dentro de _cargar_modelo) porque
  es costoso (~1-2 s solo de import).
"""

import asyncio
import gc
import io
import logging
import threading
import time
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class _OcrService:
    def __init__(self) -> None:
        self._modelo: Any | None = None
        self._lock = threading.RLock()
        self._ultimo_uso: float | None = None
        self._janitor_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Propiedades de estado (sin lock: solo lectura de valores atómicos)
    # ------------------------------------------------------------------

    @property
    def model_loaded(self) -> bool:
        return self._modelo is not None

    @property
    def seconds_since_last_use(self) -> float | None:
        if self._ultimo_uso is None:
            return None
        return time.monotonic() - self._ultimo_uso

    # ------------------------------------------------------------------
    # Carga y descarga del modelo
    # ------------------------------------------------------------------

    def _cargar_modelo(self) -> None:
        """
        Carga PaddleOCR. Debe llamarse ya dentro del lock.
        El import de paddleocr es diferido aquí para no pagar el costo
        al importar el módulo.
        """
        if self._modelo is not None:
            return

        logger.info("Cargando modelo PaddleOCR (primera petición)...")
        t0 = time.monotonic()

        try:
            from paddleocr import PaddleOCR  # import diferido

            self._modelo = PaddleOCR(
                use_gpu=False,
                show_log=False,
                lang=settings.OCR_LANG,
                use_angle_cls=settings.OCR_USE_ANGLE_CLS,
            )
            elapsed = time.monotonic() - t0
            logger.info("Modelo PaddleOCR cargado en %.2f s", elapsed)
        except Exception:
            logger.exception("Error al cargar PaddleOCR")
            self._modelo = None
            raise

    def descargar_modelo(self) -> None:
        """
        Descarga el modelo de memoria. Toma el lock para no interrumpir
        una inferencia en curso.
        """
        with self._lock:
            if self._modelo is not None:
                logger.info("Descargando modelo PaddleOCR por inactividad.")
                self._modelo = None
                gc.collect()

    # ------------------------------------------------------------------
    # Janitor asyncio
    # ------------------------------------------------------------------

    async def _janitor(self) -> None:
        """Tarea de fondo que descarga el modelo tras inactividad."""
        timeout = settings.OCR_UNLOAD_TIMEOUT
        while True:
            await asyncio.sleep(30)  # revisar cada 30 s
            if self._modelo is None:
                continue
            secs = self.seconds_since_last_use
            if secs is not None and secs >= timeout:
                self.descargar_modelo()

    def start_janitor(self) -> None:
        """Inicia la tarea de janitor en el event loop actual."""
        if self._janitor_task is None or self._janitor_task.done():
            self._janitor_task = asyncio.create_task(self._janitor())
            logger.debug("Janitor de auto-descarga iniciado.")

    def stop_janitor(self) -> None:
        """Cancela la tarea de janitor en shutdown."""
        if self._janitor_task and not self._janitor_task.done():
            self._janitor_task.cancel()
            logger.debug("Janitor de auto-descarga detenido.")

    # ------------------------------------------------------------------
    # Extracción de texto
    # ------------------------------------------------------------------

    def extract_text(self, image_bytes: bytes) -> dict[str, Any]:
        """
        Ejecuta OCR sobre los bytes de una imagen.

        Returns:
            {
                "text": str,
                "confidence": float (0-100),
                "lines": [{"text": str, "confidence": float}]
            }

        Raises:
            RuntimeError: si el modelo no se puede cargar o la inferencia falla.
        """
        import numpy as np
        from PIL import Image

        with self._lock:
            # Cargar modelo si no está cargado
            if self._modelo is None:
                self._cargar_modelo()

            modelo = self._modelo
            if modelo is None:
                raise RuntimeError("No se pudo cargar el modelo PaddleOCR.")

            try:
                imagen = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                # PaddleOCR 2.x exige np.ndarray (no acepta PIL Image directamente)
                img_array = np.array(imagen)
                resultado = modelo.ocr(img_array, cls=settings.OCR_USE_ANGLE_CLS)
            except Exception as exc:
                raise RuntimeError(f"Error durante la inferencia OCR: {exc}") from exc
            finally:
                self._ultimo_uso = time.monotonic()

        return _procesar_resultado(resultado)


def _procesar_resultado(resultado: Any) -> dict[str, Any]:
    """
    Normaliza la salida de PaddleOCR 2.x al formato interno.

    PaddleOCR devuelve lista de listas:
        [[box, (texto, confianza)], ...]
    o puede devolver [None] o [] cuando no detecta nada.
    La confianza viene en 0-1 y se convierte a 0-100.
    """
    lineas: list[dict[str, Any]] = []

    if not resultado:
        return {"text": "", "confidence": 0.0, "lines": []}

    # PaddleOCR 2.x envuelve el resultado en una lista extra
    items = resultado[0] if isinstance(resultado[0], list) else resultado

    for item in items:
        if item is None:
            continue
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        # item = [box, (texto, confianza)]
        texto_conf = item[1]
        if not isinstance(texto_conf, (list, tuple)) or len(texto_conf) < 2:
            continue

        texto = str(texto_conf[0])
        try:
            confianza = float(texto_conf[1]) * 100  # 0-1 → 0-100
        except (TypeError, ValueError):
            confianza = 0.0

        lineas.append({"text": texto, "confidence": round(confianza, 2)})

    if not lineas:
        return {"text": "", "confidence": 0.0, "lines": []}

    texto_completo = "\n".join(l["text"] for l in lineas)
    confianza_promedio = round(sum(l["confidence"] for l in lineas) / len(lineas), 2)

    return {
        "text": texto_completo,
        "confidence": confianza_promedio,
        "lines": lineas,
    }


# Instancia singleton del servicio
ocr_service = _OcrService()
