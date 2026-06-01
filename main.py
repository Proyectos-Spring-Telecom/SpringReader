"""
SpringReader — Microservicio FastAPI de OCR con PaddleOCR.

Endpoints:
  GET  /health
  POST /ocr, /ocr/batch, /ocr/upload, /ocr/upload-ine, /ine/extract
  POST /constancia-fiscal/extract
"""

import base64
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from middleware.auth import require_service_key
from middleware.auth_middleware import AuthMiddleware
from ocr.constancia_parser import parse_constancia_fiscal
from ocr.ine_parser import parse_ine
from ocr.ocr_service import ocr_service
from ocr.pdf_extractor import extract_text_from_pdf
from ocr.schemas import (
    BatchOcrRequest,
    BatchOcrResponse,
    BatchOcrResultItem,
    ConstanciaFiscalData,
    ConstanciaFiscalDataWrapper,
    ConstanciaFiscalResponse,
    HealthResponse,
    IneExtractData,
    IneExtractResponse,
    IneOcrResponse,
    OcrConfidence,
    OcrLine,
    OcrRequest,
    OcrResponse,
    OcrSideResult,
)

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando %s en puerto %d", settings.APP_NAME, settings.APP_PORT)
    ocr_service.start_janitor()
    yield
    logger.info("Apagando %s, descargando modelo si estaba cargado...", settings.APP_NAME)
    ocr_service.descargar_modelo()
    ocr_service.stop_janitor()


app = FastAPI(
    title=settings.APP_NAME,
    root_path=settings.APP_ROOT_PATH,
    version="1.1.0",
    description=(
        "Microservicio de OCR con PaddleOCR, parser de INE mexicana "
        "y extracción de Constancia de Situación Fiscal (SAT)."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decodificar_base64(data: str, max_bytes: int) -> bytes:
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        imagen_bytes = base64.b64decode(data)
    except Exception:
        raise HTTPException(status_code=400, detail="Imagen base64 inválida.")
    if len(imagen_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Imagen excede el tamaño máximo de {max_bytes} bytes.",
        )
    return imagen_bytes


async def _leer_upload(file: UploadFile, max_bytes: int) -> bytes:
    datos = await file.read()
    if len(datos) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo excede el tamaño máximo de {max_bytes} bytes.",
        )
    if not datos:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    return datos


def _validar_pdf(datos: bytes, content_type: str | None) -> None:
    """Valida que el archivo sea un PDF (%PDF o mimetype application/pdf)."""
    if datos[:4].startswith(b"%PDF"):
        return
    if content_type and "pdf" in content_type.lower():
        return
    raise HTTPException(status_code=400, detail="El archivo no es un PDF válido.")


def _ejecutar_ocr(imagen_bytes: bytes) -> dict:
    try:
        return ocr_service.extract_text(imagen_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("Error inesperado en OCR")
        raise HTTPException(status_code=500, detail=f"Error interno OCR: {exc}")


def _resultado_a_ocr_response(resultado: dict) -> OcrResponse:
    lines = [OcrLine(text=l["text"], confidence=l["confidence"]) for l in resultado["lines"]]
    return OcrResponse(
        text=resultado["text"],
        confidence=resultado["confidence"],
        lines=lines,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    """Health check. No carga el modelo ni requiere autenticación."""
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        model_loaded=ocr_service.model_loaded,
        seconds_since_last_use=ocr_service.seconds_since_last_use,
    )


@app.post("/ocr", response_model=OcrResponse, tags=["ocr"])
async def ocr_base64(
    request: OcrRequest,
    _: str | None = Depends(require_service_key),
):
    imagen_bytes = _decodificar_base64(request.image, settings.OCR_MAX_UPLOAD_SIZE)
    resultado = _ejecutar_ocr(imagen_bytes)
    return _resultado_a_ocr_response(resultado)


@app.post("/ocr/batch", response_model=BatchOcrResponse, tags=["ocr"])
async def ocr_batch(
    request: BatchOcrRequest,
    _: str | None = Depends(require_service_key),
):
    results = []
    for item in request.images:
        try:
            imagen_bytes = _decodificar_base64(item.image, settings.OCR_MAX_UPLOAD_SIZE)
            resultado = _ejecutar_ocr(imagen_bytes)
            results.append(
                BatchOcrResultItem(
                    id=item.id,
                    text=resultado["text"],
                    confidence=resultado["confidence"],
                    error=None,
                )
            )
        except HTTPException as exc:
            results.append(
                BatchOcrResultItem(id=item.id, text="", confidence=0.0, error=exc.detail)
            )
        except Exception as exc:
            results.append(
                BatchOcrResultItem(id=item.id, text="", confidence=0.0, error=str(exc))
            )
    return BatchOcrResponse(results=results)


@app.post("/ocr/upload", response_model=OcrResponse, tags=["ocr"])
async def ocr_upload(
    file: UploadFile = File(...),
    _: str | None = Depends(require_service_key),
):
    imagen_bytes = await _leer_upload(file, settings.OCR_MAX_UPLOAD_SIZE)
    resultado = _ejecutar_ocr(imagen_bytes)
    return _resultado_a_ocr_response(resultado)


@app.post("/ocr/upload-ine", response_model=IneOcrResponse, tags=["ine"])
async def ocr_upload_ine(
    frente: UploadFile = File(...),
    reverso: UploadFile = File(...),
    _: str | None = Depends(require_service_key),
):
    frente_bytes = await _leer_upload(frente, settings.OCR_MAX_UPLOAD_SIZE)
    reverso_bytes = await _leer_upload(reverso, settings.OCR_MAX_UPLOAD_SIZE)

    resultado_frente = _ejecutar_ocr(frente_bytes)
    resultado_reverso = _ejecutar_ocr(reverso_bytes)

    combined = resultado_frente["text"] + "\n" + resultado_reverso["text"]

    return IneOcrResponse(
        frente=OcrSideResult(
            text=resultado_frente["text"],
            confidence=resultado_frente["confidence"],
        ),
        reverso=OcrSideResult(
            text=resultado_reverso["text"],
            confidence=resultado_reverso["confidence"],
        ),
        combined_text=combined,
    )


@app.post("/ine/extract", response_model=IneExtractResponse, tags=["ine"])
async def ine_extract(
    frente: UploadFile = File(...),
    reverso: UploadFile | None = File(default=None),
    _: str | None = Depends(require_service_key),
):
    """
    Extracción de datos de INE. `frente` es obligatorio; `reverso` es opcional
    (si no se envía, solo se usa el texto del frente y la CURP del frente).
    """
    frente_bytes = await _leer_upload(frente, settings.OCR_MAX_UPLOAD_SIZE)

    reverso_bytes: bytes | None = None
    if reverso is not None and reverso.filename:
        datos_reverso = await reverso.read()
        if datos_reverso:
            if len(datos_reverso) > settings.OCR_MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Archivo reverso excede el tamaño máximo de "
                        f"{settings.OCR_MAX_UPLOAD_SIZE} bytes."
                    ),
                )
            reverso_bytes = datos_reverso

    resultado_frente = _ejecutar_ocr(frente_bytes)

    if reverso_bytes:
        resultado_reverso = _ejecutar_ocr(reverso_bytes)
        reverso_text = resultado_reverso["text"]
        reverso_confidence = resultado_reverso["confidence"]
        raw_text = f"--- FRENTE ---\n{resultado_frente['text']}\n--- REVERSO ---\n{reverso_text}"
    else:
        reverso_text = ""
        reverso_confidence = 0.0
        raw_text = f"--- FRENTE ---\n{resultado_frente['text']}"

    frente_text = resultado_frente["text"]
    datos = parse_ine(frente_text, reverso_text)

    return IneExtractResponse(
        extraction_id=str(uuid.uuid4()),
        data=IneExtractData(**datos),
        ocr_confidence=OcrConfidence(
            frente=resultado_frente["confidence"],
            reverso=reverso_confidence,
        ),
        raw_text=raw_text,
    )


@app.post(
    "/constancia-fiscal/extract",
    response_model=ConstanciaFiscalResponse,
    tags=["constancia-fiscal"],
)
async def constancia_fiscal_extract(
    file: UploadFile = File(...),
    _: str | None = Depends(require_service_key),
):
    """
    Extrae datos estructurados de una Constancia de Situación Fiscal del SAT.
    Detecta texto nativo u OCR según el PDF.
    """
    pdf_bytes = await _leer_upload(file, settings.OCR_MAX_UPLOAD_SIZE)
    _validar_pdf(pdf_bytes, file.content_type)

    try:
        raw_text, processing_type, page_count = extract_text_from_pdf(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error al extraer texto del PDF")
        raise HTTPException(status_code=500, detail=f"Error al procesar PDF: {exc}")

    if not raw_text.strip():
        raise HTTPException(
            status_code=500,
            detail="No se pudo extraer texto del PDF.",
        )

    datos = parse_constancia_fiscal(raw_text)

    return ConstanciaFiscalResponse(
        processingType=processing_type.lower(),
        pageCount=page_count,
        data=ConstanciaFiscalDataWrapper(constancia=ConstanciaFiscalData(**datos)),
        raw_text=raw_text,
    )
