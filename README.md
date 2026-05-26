# SpringReader

Microservicio Python/FastAPI de OCR con PaddleOCR y extracción de datos de credencial INE mexicana. Pensado para ejecutarse en CPU con RAM limitada; lo consume otro backend por HTTP.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio y del modelo |
| POST | `/ocr` | OCR de imagen en base64 |
| POST | `/ocr/batch` | OCR de múltiples imágenes en base64 (secuencial) |
| POST | `/ocr/upload` | OCR de archivo multipart |
| POST | `/ocr/upload-ine` | OCR de INE (frente + reverso) |
| POST | `/ine/extract` | Extracción de INE (`frente` obligatorio, `reverso` opcional) |
| POST | `/constancia-fiscal/extract` | Extracción de Constancia de Situación Fiscal (SAT) desde PDF |

Documentación interactiva: `/docs` y `/redoc`.

### Autenticación en Swagger

Con `AUTH_ENABLED=true`, los endpoints protegidos exigen el header `X-Service-Key`. En `/docs` aparece el botón **Authorize** para pegar la clave una vez; `/health` y la documentación (`/docs`, `/redoc`, `/openapi.json`) no requieren clave.

## Gestión de RAM

| Mecanismo | Descripción |
|-----------|-------------|
| **Lazy loading** | PaddleOCR no se carga al arrancar; se instancia en la primera petición OCR. |
| **Lock de serialización** | Toda inferencia ocurre bajo un `threading.RLock`. El batch procesa imágenes en secuencia. |
| **Auto-descarga** | Tras `OCR_UNLOAD_TIMEOUT` segundos sin uso (default 600), el modelo se libera de RAM y se llama a `gc.collect()`. |

## Instalación local

Requisitos: Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt

cp .env.example .env
# Editar .env según tu entorno

python preload_models.py             # opcional: pre-descarga modelos PaddleOCR

uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

En Windows puedes usar `start.bat` para el flujo de desarrollo.

## Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `APP_NAME` | `SpringReader` | Nombre del servicio |
| `APP_PORT` | `8001` | Puerto de escucha |
| `APP_ENV` | `development` | Entorno de ejecución |
| `LOG_LEVEL` | `INFO` | Nivel de logging |
| `AUTH_ENABLED` | `false` | Activar autenticación por `X-Service-Key` |
| `SERVICE_API_KEY` | *(vacío)* | Clave requerida si `AUTH_ENABLED=true` |
| `CORS_ORIGINS` | *(vacío)* | Orígenes CORS separados por coma |
| `OCR_LAZY_LOAD` | `true` | No cargar modelo al arrancar |
| `OCR_MAX_UPLOAD_SIZE` | `10485760` | Tamaño máximo de imagen (bytes) |
| `OCR_UNLOAD_TIMEOUT` | `600` | Segundos de inactividad antes de descargar el modelo |
| `OCR_LANG` | `es` | Idioma de PaddleOCR |
| `OCR_USE_ANGLE_CLS` | `true` | Clasificador de ángulo de texto |

## Compatibilidad: `numpy<2`

`paddlepaddle==2.6.2` fue compilado contra numpy 1.x. numpy 2.x rompe el import de PaddlePaddle. El pin `numpy<2` en `requirements.txt` es obligatorio.

## Parser de INE: calibración con muestras reales

El parser (`ocr/ine_parser.py`) se basa en el formato estándar de la INE mexicana (modelos C/D/E). Sin muestras reales del texto OCR de tu emisión, no se garantiza cobertura perfecta.

Para calibrar:

1. Envía credenciales reales a `POST /ine/extract`.
2. Usa el campo `raw_text` de la respuesta (texto OCR sin procesar).
3. Ajusta las funciones `extract_*` en `ocr/ine_parser.py` y añade entradas a `CORRECCIONES_OCR` según sea necesario.

Test sintético incluido:

```bash
python -m ocr.ine_parser
```

## Constancia Fiscal SAT: calibración con PDFs reales

El parser (`ocr/constancia_parser.py`) está portado de una versión en producción, pero las constancias del SAT varían por año y tipo de contribuyente; el OCR de escaneos añade ruido. Valídalo con PDFs reales.

1. Envía el PDF a `POST /constancia-fiscal/extract`.
2. Usa `raw_text` y `processing_type` (`NATIVE` o `OCR`) para depurar.
3. Ajusta `ocr/constancia_parser.py` según sea necesario.

Test sintético:

```bash
python -m ocr.constancia_parser
```
