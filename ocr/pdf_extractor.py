"""
Extracción de texto de PDF: nativo (PyMuPDF) u OCR (PaddleOCR vía ocr_service).

Flujo híbrido: detecta si el PDF tiene texto nativo suficiente; si no,
rasteriza páginas y pasa cada una al servicio OCR existente (secuencial).
"""

import io
import logging

import fitz

from ocr.ocr_service import ocr_service

logger = logging.getLogger(__name__)

_NATIVE_CHAR_THRESHOLD = 50
_OCR_DPI = 200


def detect_native_text(pdf_bytes: bytes) -> tuple[bool, int]:
    """
    Detecta si el PDF tiene texto nativo extraíble.
    Escanea hasta las primeras 3 páginas; is_native si chars sin espacio > 50.
  """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("PDF inválido o corrupto") from exc

    try:
        page_count = len(doc)
        total_chars = 0
        for i in range(min(3, page_count)):
            text = doc[i].get_text()
            total_chars += len(text.replace(" ", "").replace("\n", ""))
        is_native = total_chars > _NATIVE_CHAR_THRESHOLD
        return is_native, page_count
    finally:
        doc.close()


def extract_native(pdf_bytes: bytes) -> tuple[str, int]:
    """Extrae texto nativo concatenando todas las páginas."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("PDF inválido o corrupto") from exc

    try:
        page_count = len(doc)
        partes = []
        for page in doc:
            partes.append(page.get_text())
        text = "\n\n".join(partes)
        return text, page_count
    finally:
        doc.close()


def extract_ocr(pdf_bytes: bytes) -> tuple[str, int]:
    """
    Rasteriza cada página a PNG (~200 DPI) y ejecuta OCR secuencialmente.
    Reutiliza ocr_service (lazy load + lock + auto-descarga).
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("PDF inválido o corrupto") from exc

    try:
        page_count = len(doc)
        partes = []
        for page in doc:
            pix = page.get_pixmap(dpi=_OCR_DPI)
            img_bytes = pix.tobytes("png")
            resultado = ocr_service.extract_text(img_bytes)
            partes.append(resultado["text"])
        text = "\n\n".join(partes)
        return text, page_count
    finally:
        doc.close()


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str, int]:
    """
    Orquestador: detecta nativo vs OCR y devuelve (texto, processing_type, page_count).
    processing_type es "NATIVE" o "OCR".
    """
    is_native, page_count = detect_native_text(pdf_bytes)

    if is_native:
        text, page_count = extract_native(pdf_bytes)
        processing_type = "NATIVE"
    else:
        logger.info(
            "PDF sin texto nativo suficiente (%d páginas), usando OCR",
            page_count,
        )
        text, page_count = extract_ocr(pdf_bytes)
        processing_type = "OCR"

    return text, processing_type, page_count
