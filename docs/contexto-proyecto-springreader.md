# Contexto para nuevo chat — Proyecto SpringReader

## OBJETIVO

Crear un microservicio Python/FastAPI independiente llamado **SpringReader** dedicado exclusivamente a OCR con PaddleOCR. Este proyecto se separa de SpringAgent (que ahora solo maneja chat + Ollama).

Repositorio: https://github.com/Proyectos-Spring-Telecom/SpringReader.git

---

## SERVIDOR DESTINO

**Servidor:** spPenta0m  
**IP:** 216.238.70.193  
**Dominio:** spcode.ddns.net  
**OS:** Ubuntu 24.04  
**CPU:** 4 vCPU Intel Xeon Cascadelake (AVX512)  
**RAM:** 7.7 GB total (~4.9 GB disponibles ahora que Ollama fue removido)  
**Python:** 3.12.3  
**Nginx:** ya instalado y configurado en `/etc/nginx/sites-enabled/spcode`

### Servicios que ya corren en este servidor:

- Puerto 8000 → behaviorIQService (Python/FastAPI)
- Puerto 3000 → behaviorIQAPI (Node/NestJS) — requiere reinstalar Node
- Puerto 3001 → riskComplianceAPI (Node)
- Puerto 3003 → cleanCoreAPI (Node)
- Puerto 6379 → Redis
- Puerto 3306 → MySQL
- Puerto 80/443 → Nginx

### Puertos disponibles sugeridos:

- 8001 (hay un proceso huérfano, matar con `kill 931` antes de usar)
- 8010 (libre, era de SpringAgent que ya se removió)

### Nota importante:

- Ollama y SpringAgent fueron desinstalados de este servidor
- La carpeta `/home/ubuntu/development/llm` fue eliminada
- Node.js necesita reinstalarse (se borró durante la instalación de Ollama):

  ```bash
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
  ```

---

## CÓDIGO ORIGINAL DE OCR

El código OCR original existía en el proyecto `paddleocr-service` y después fue absorbido por SpringAgent en la carpeta `ocr/`. Los archivos originales son:

### Archivos a recrear:

**main.py** — FastAPI con 6 endpoints:

- `GET /health` — Health check
- `POST /ocr` — OCR general (imagen en base64 → texto)
- `POST /ocr/batch` — OCR de múltiples imágenes en una llamada
- `POST /ocr/upload` — OCR subiendo archivo multipart
- `POST /ocr/upload-ine` — OCR especializado de INE (frente + reverso)
- `POST /ine/extract` — Extracción completa de datos INE con parser inteligente

**ocr_service.py** — Singleton PaddleOCR thread-safe:

- Carga PaddleOCR una sola vez (lazy loading)
- Thread lock para peticiones concurrentes
- Auto-descarga después de inactividad (configurable)
- `extract_text(image_bytes)` retorna `{ text, confidence, lines }`

**ine_parser.py** (536 líneas) — Parser de INE mexicana:

- Regex para extraer: nombre, apellidos, CURP, clave de elector, fecha nacimiento, sexo, domicilio, colonia, CP, municipio, estado, sección, vigencia
- Manejo de palabras pegadas del OCR (ej: "LAZAROCARDENAS")
- Parse de zona MRZ del reverso
- Lista de reemplazos conocidos para errores de OCR

**curp_deriver.py** (150 líneas) — Derivador de CURP:

- Genera CURP a partir de nombre, apellidos, fecha nacimiento, sexo, estado
- Tabla de códigos de estado
- Algoritmo de dígito verificador

**schemas.py** (74 líneas) — Schemas Pydantic:

- OcrRequest, OcrResponse
- BatchOcrRequest, BatchOcrResponse
- IneOcrResponse, IneExtractResponse, IneExtractData
- OcrConfidence

### requirements.txt original:

```
setuptools>=69.0.0
paddlepaddle==2.6.2
paddleocr==2.8.1
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.9
pillow>=10.0.0
numpy>=1.24.0
```

---

## FUNCIONALIDAD DE CADA ENDPOINT

### POST /ocr

- Recibe: `{ "image": "base64_string", "language": "es|en" }`
- Retorna: `{ "text": "...", "confidence": 95.5, "lines": [...] }`

### POST /ocr/batch

- Recibe: `{ "images": [{ "id": "img1", "image": "base64..." }, ...] }`
- Retorna: `{ "results": [{ "id": "img1", "text": "...", "confidence": 95 }, ...] }`

### POST /ocr/upload

- Recibe: multipart file upload
- Retorna: `{ "text": "...", "confidence": 95.5, "lines": [...] }`

### POST /ocr/upload-ine

- Recibe: multipart (frente: file, reverso: file)
- Retorna: `{ "frente": { "text": "..." }, "reverso": { "text": "..." }, "combined_text": "..." }`

### POST /ine/extract

- Recibe: multipart (frente: file, reverso: file)
- Retorna: datos estructurados de la INE:

```json
{
  "extraction_id": "uuid",
  "data": {
    "nombre": "MARIA GUADALUPE",
    "apellidoPaterno": "GARCIA",
    "apellidoMaterno": "LOPEZ",
    "curp": "GALM850101MDFRPRA09",
    "claveElector": "GRCLPR85010109H200",
    "fechaNacimiento": "01/01/1985",
    "sexo": "M",
    "domicilio": "AV REFORMA 123",
    "colonia": "CENTRO",
    "codigoPostal": "06600",
    "municipio": "CUAUHTEMOC",
    "estado": "CDMX",
    "seccion": "0901",
    "vigencia": "2029"
  },
  "ocr_confidence": { "frente": 92.5, "reverso": 88.3 }
}
```

---

## INTEGRACIÓN CON NESTJS (InmueblesAPI)

NestJS (InmueblesAPI) ya tiene un módulo `pdf-ocr` que se conecta al servicio de OCR via HTTP. Las variables en el `.env` de NestJS:

```env
OCR_ENGINE=tesseract
PADDLEOCR_SERVICE_URL=http://localhost:8001
PADDLEOCR_TIMEOUT_MS=60000
```

El servicio `PaddleOcrClientService` en NestJS (`src/pdf-ocr/services/paddleocr-client.service.ts`) hace llamadas HTTP a estos endpoints. Cuando SpringReader esté corriendo, solo hay que actualizar `PADDLEOCR_SERVICE_URL` para que apunte al nuevo servicio.

---

## ESTRUCTURA SUGERIDA PARA SPRINGREADER

```
SpringReader/
├── main.py                 # FastAPI con 6 endpoints
├── config.py               # Settings con pydantic-settings
├── .env                    # Variables de entorno
├── ocr/
│   ├── __init__.py
│   ├── ocr_service.py      # Singleton PaddleOCR con lazy load + auto-descarga
│   ├── ine_parser.py       # Parser INE (536 líneas)
│   ├── curp_deriver.py     # Derivador CURP
│   └── schemas.py          # Schemas Pydantic
├── middleware/
│   └── auth_middleware.py   # X-Service-Key (opcional, para seguridad)
├── requirements.txt
├── Dockerfile
├── start.bat               # Para desarrollo Windows
└── README.md
```

---

## VARIABLES DE ENTORNO (.env)

```env
APP_NAME=SpringReader
APP_PORT=8001
APP_ENV=production
LOG_LEVEL=INFO

# Security (opcional)
SERVICE_API_KEY=springreader-secure-key-change-in-production

# CORS
CORS_ORIGINS=http://localhost:3005,https://springtelecom.mx

# OCR
OCR_LAZY_LOAD=true
OCR_MAX_UPLOAD_SIZE=10485760
OCR_UNLOAD_TIMEOUT=600
```

---

## DEMONIO SYSTEMD (referencia)

```ini
[Unit]
Description=Uvicorn FastAPI - springReader
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/development/workspace/springReader/SpringReader
Environment="PYTHONUNBUFFERED=1"
Environment="PATH=/home/ubuntu/development/workspace/springReader/SpringReader/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/home/ubuntu/development/workspace/springReader/SpringReader/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## MEJORAS QUE SE HABÍAN IMPLEMENTADO (opcionales para SpringReader)

1. **Lazy loading de PaddleOCR** — No cargar al inicio, solo cuando llega la primera petición OCR
2. **Auto-descarga** — Si nadie usa OCR en 10 minutos, liberar PaddleOCR de RAM (~400-500 MB)
3. **INE Enhanced con Ollama** — Endpoint `/ine/extract-enhanced` que combina regex + Ollama para mejorar extracción (requiere Ollama, que NO está en spPenta0m)

Para SpringReader en spPenta0m, las mejoras 1 y 2 son útiles. La mejora 3 (Ollama) no aplica porque Ollama no está en ese servidor.

---

## CONTEXTO DE LOS OTROS PROYECTOS

- **SpringAgent** (Python) — Chat + Ollama + tool calling → servidor textAgent (216.238.82.163:8010)
- **InmueblesAPI** (NestJS) — Backend empresarial → servidor springfieldDev (springtelecom.mx)
- **SpringReader** (Python) — OCR → servidor spPenta0m (spcode.ddns.net) ← ESTE PROYECTO

---

## PROMPT CORTO PARA PEGAR EN EL NUEVO CHAT

```
Necesito crear un microservicio Python/FastAPI llamado SpringReader dedicado a OCR con PaddleOCR. 

Repositorio: https://github.com/Proyectos-Spring-Telecom/SpringReader.git
Servidor: spPenta0m (Ubuntu 24.04, Python 3.12.3, 7.7 GB RAM, sin GPU)
Puerto: 8001

Tiene 6 endpoints:
- GET /health
- POST /ocr (base64 → texto)
- POST /ocr/batch (múltiples imágenes)
- POST /ocr/upload (multipart → texto)
- POST /ocr/upload-ine (INE frente + reverso)
- POST /ine/extract (extracción completa de datos INE mexicana)

Usa PaddleOCR con lazy loading (no cargar al inicio) y auto-descarga después de 10 minutos de inactividad. 

El parser de INE tiene 536 líneas con regex para: nombre, apellidos, CURP, clave de elector, fecha nacimiento, sexo, domicilio, colonia, CP, municipio, estado, sección, vigencia. Maneja palabras pegadas del OCR y zona MRZ del reverso.

Python 3.12.3, paddlepaddle==2.6.2, paddleocr==2.8.1.

[Adjunta el documento de contexto completo]

Ayúdame a: [describe tu tarea]
```
