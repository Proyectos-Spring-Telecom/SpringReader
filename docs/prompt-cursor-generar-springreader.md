# Prompt para Cursor — Generar microservicio SpringReader desde cero

Copia todo lo que sigue (desde la línea de abajo) y pégalo en Cursor.

---

Eres un ingeniero de backend senior. Crea desde cero un microservicio Python/FastAPI llamado **SpringReader**, dedicado a OCR con PaddleOCR, con un parser de credencial INE mexicana. Sigue las especificaciones al pie de la letra. No añadas dependencias ni endpoints que no se pidan. Toda la configuración debe venir por variables de entorno; no incluyas rutas, hosts, IPs ni archivos de despliegue en el repositorio.

## Entorno de ejecución (para justificar decisiones de diseño)

El servicio corre en **CPU, sin GPU, con RAM limitada**, y lo consume otro backend por HTTP. Por eso la gestión de memoria del modelo es crítica (ver más abajo). Puerto por defecto: **8001**, configurable por entorno.

## Restricciones técnicas CRÍTICAS (respétalas exactamente)

1. **Versiones fijas y verificadas.** En `requirements.txt` usa exactamente:
   ```
   setuptools>=69.0.0
   paddlepaddle==2.6.2
   paddleocr==2.8.1
   numpy<2
   fastapi>=0.110.0
   uvicorn[standard]>=0.27.0
   python-multipart>=0.0.9
   pydantic-settings>=2.0.0
   pillow>=10.0.0
   ```
   **El pin `numpy<2` es obligatorio:** paddlepaddle 2.6.2 se compiló contra numpy 1.x y numpy 2.x rompe el import. NO lo cambies a `numpy>=1.24` ni a ningún rango que permita 2.x. Objetivo: Python 3.12.

2. **Gestión del modelo PaddleOCR para CPU con poca RAM:**
   - **Lazy loading:** NO cargar el modelo al arrancar el proceso. Cargarlo solo en la primera petición OCR.
   - **Serialización con lock:** toda inferencia debe ocurrir bajo un único `threading.RLock`. PaddleOCR en CPU no es confiablemente thread-safe y la RAM no permite dos inferencias simultáneas. El endpoint batch procesa las imágenes **en secuencia**, no en paralelo.
   - **Auto-descarga por inactividad:** una tarea de fondo (asyncio) debe liberar el modelo de RAM tras N segundos sin uso (default 600 = 10 min) y llamar a `gc.collect()`. La descarga debe tomar el mismo lock para nunca ocurrir en medio de una inferencia.
   - Un fallo al cargar el modelo NO debe dejar el servicio bloqueado: el lock debe liberarse y permitir reintentos.
   - Instanciar PaddleOCR con `use_gpu=False`, `show_log=False`, `lang` configurable (default "es"), `use_angle_cls` configurable (default True).
   - El import de `paddleocr` debe ser **diferido** (dentro de la función de carga), no a nivel de módulo, porque es costoso.

3. **Configuración con pydantic-settings**, leyendo de `.env` con defaults razonables para que arranque sin `.env`. Variables: `APP_NAME`, `APP_PORT`, `APP_ENV`, `LOG_LEVEL`, `AUTH_ENABLED` (bool, default false), `SERVICE_API_KEY`, `CORS_ORIGINS` (string separado por comas que se parsea a lista), `OCR_LAZY_LOAD`, `OCR_MAX_UPLOAD_SIZE` (default 10485760), `OCR_UNLOAD_TIMEOUT` (default 600), `OCR_LANG` (default "es"), `OCR_USE_ANGLE_CLS` (default true). Ningún valor real de configuración debe estar hardcodeado: el `.env.example` solo lleva placeholders genéricos.

## Estructura del proyecto

```
SpringReader/
├── main.py                 # FastAPI con los 6 endpoints + lifespan
├── config.py               # Settings con pydantic-settings
├── preload_models.py       # Script para predescargar modelos (uso opcional)
├── ocr/
│   ├── __init__.py
│   ├── ocr_service.py      # Singleton PaddleOCR: lazy load + lock + auto-descarga
│   ├── ine_parser.py       # Parser de INE
│   ├── curp_deriver.py     # Derivación y validación de CURP (algoritmo RENAPO)
│   └── schemas.py          # Modelos Pydantic
├── middleware/
│   ├── __init__.py
│   └── auth_middleware.py  # X-Service-Key (opcional, controlado por AUTH_ENABLED)
├── requirements.txt
├── start.bat               # Desarrollo en Windows
├── .env.example
├── .gitignore
└── README.md
```

No generes Dockerfile ni archivos de servicio del sistema (systemd u otros): el despliegue se configura directamente en el entorno destino y queda fuera del repositorio.

## Los 6 endpoints (formato de respuesta exacto)

Todos los errores deben devolver códigos HTTP correctos (400 base64/archivo inválido, 413 tamaño excedido, 500 error de OCR) con `{"detail": "..."}`.

### `GET /health`
No debe cargar el modelo. Devuelve:
```json
{ "status": "ok", "service": "SpringReader", "model_loaded": false, "seconds_since_last_use": null }
```

### `POST /ocr`
Recibe `{ "image": "base64_string", "language": "es" }` (tolerar prefijo `data:...;base64,`). Devuelve:
```json
{ "text": "...", "confidence": 95.5, "lines": [ { "text": "...", "confidence": 95.5 } ] }
```
`confidence` es 0–100 (promedio de las líneas).

### `POST /ocr/batch`
Recibe `{ "images": [ { "id": "img1", "image": "base64..." } ], "language": "es" }`. Procesa en secuencia. Si una imagen falla, captura el error por ítem y continúa. Devuelve:
```json
{ "results": [ { "id": "img1", "text": "...", "confidence": 95.0, "error": null } ] }
```

### `POST /ocr/upload`
Recibe un archivo multipart (`file`). Misma respuesta que `/ocr`.

### `POST /ocr/upload-ine`
Recibe dos archivos multipart: `frente` y `reverso`. Devuelve:
```json
{ "frente": { "text": "...", "confidence": 92.5 }, "reverso": { "text": "...", "confidence": 88.3 }, "combined_text": "..." }
```

### `POST /ine/extract`
Recibe `frente` y `reverso` multipart. Hace OCR de ambos, pasa el texto al parser y devuelve:
```json
{
  "extraction_id": "uuid-v4",
  "data": {
    "nombre": null, "apellidoPaterno": null, "apellidoMaterno": null,
    "curp": null, "claveElector": null, "fechaNacimiento": null, "sexo": null,
    "domicilio": null, "colonia": null, "codigoPostal": null,
    "municipio": null, "estado": null, "seccion": null, "vigencia": null
  },
  "ocr_confidence": { "frente": 92.5, "reverso": 88.3 },
  "raw_text": "--- FRENTE ---\n...\n--- REVERSO ---\n..."
}
```
Incluir `raw_text` (frente + reverso) es obligatorio: es necesario para calibrar el parser con casos reales.

## Normalización de la salida de PaddleOCR

PaddleOCR 2.x devuelve una lista por imagen; cada elemento es `[box, (texto, confianza)]`. Cuando no detecta nada puede devolver `[None]` o `[]`. La confianza viene 0–1 y debe convertirse a 0–100. Maneja estos casos defensivamente.

## Derivador de CURP (`curp_deriver.py`)

Implementa el algoritmo de RENAPO para CURP de 18 caracteres:
- 4 letras (inicial+1ª vocal interna del apellido paterno, inicial apellido materno, inicial nombre).
- Si el nombre empieza por JOSE/MARIA/MA/J, usar el segundo nombre para la inicial.
- Regla de palabras altisonantes: si las 4 primeras letras forman una palabra inconveniente, sustituir la 2ª por X (incluye una lista de ~70 palabras).
- 6 dígitos de fecha YYMMDD, letra de sexo (H/M), 2 letras de entidad federativa (tabla de códigos RENAPO de los 32 estados + NE extranjero), 3 consonantes internas, homoclave (no derivable: placeholder según año), y dígito verificador calculado.
- Función `validate_curp(curp)` que valida estructura por regex y dígito verificador.
- Función `parse_fecha` que acepta `dd/mm/yyyy`, `dd-mm-yyyy` y `"dd de MES de yyyy"`.

Verifica el dígito verificador con este caso canónico de RENAPO: `HEGG560427MVZRRL04` debe validar como correcto.

## Parser de INE (`ine_parser.py`) — LEER CON ATENCIÓN

**Advertencia importante:** no tienes muestras reales del texto OCR crudo de estas INE. NO inventes que el parser "funcionará perfectamente". Constrúyelo sobre el **formato estándar publicado de la INE mexicana** (modelos C/D/E vigentes) y déjalo **modular y testeable** para que el equipo lo calibre después con datos reales. Prioriza estructura limpia sobre cobertura mágica de casos.

Requisitos del parser:
- Normalización del texto crudo: uppercase, quitar acentos (preservando Ñ), y una tabla `CORRECCIONES_OCR` (dict de errores conocidos → corrección) **diseñada para crecer**; incluye algunos ejemplos de palabras pegadas como `INSTITUTONACIONALELECTORAL`, `CLAVEDEELECTOR`, etc.
- Cada campo se extrae con una **función independiente y testeable**: `extract_curp`, `extract_clave_elector`, `extract_nombre_apellidos`, `extract_fecha_nacimiento`, `extract_sexo`, `extract_domicilio` (que saca domicilio, colonia, CP, municipio, estado), `extract_seccion`, `extract_vigencia`.
- Regex robustas que toleren texto pegado (sin depender de `\b` al inicio cuando el OCR pega la etiqueta al valor, p. ej. `CURPGALG...`):
  - CURP: `([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)`
  - Clave de elector: `([A-Z]{6}\d{8}[HM]\d{3})`
- Al buscar el estado en el bloque de domicilio, preferir el nombre **más largo** primero (para no quedarse con "MEXICO" cuando dice "CIUDAD DE MEXICO").
- Extraer el municipio de la línea típica `CP MUNICIPIO ESTADO` quitando el CP y el estado.
- Parser de la **zona MRZ del reverso** (formato tipo TD1, 3 líneas): detectar líneas con `IDMEX` o múltiples `<`, extraer fecha de nacimiento (YYMMDD), sexo y vigencia de la 2ª línea. Heurística de siglo: años 00–29 → 2000s, resto → 1900s.
- Función orquestadora `parse_ine(frente_text, reverso_text)` que reconcilia: campos codificados (CURP, clave, fechas, sexo, vigencia) se prefieren del MRZ del reverso cuando el frente no los tiene; el texto legible (nombre, domicilio) del frente. Como último recurso, derivar fecha de nacimiento y sexo desde la CURP.
- Devuelve un dict con las 14 claves del campo `data` de `/ine/extract`.

Añade al final un bloque de prueba (o un test simple) que pase este texto sintético y verifique que extrae los 14 campos:
```
NOMBRE / GARCIA / LOPEZ / MARIA GUADALUPE / DOMICILIO / AV REFORMA 123 / CENTRO /
06600 CUAUHTEMOC CIUDAD DE MEXICO / CLAVE DE ELECTOR GRCLPR85010109H200 /
CURP GALG850101MDFRPD09 / FECHA DE NACIMIENTO 01/01/1985 / SEXO M / SECCION 0901 / VIGENCIA 2019 2029
```

## Middleware de autenticación (`auth_middleware.py`)

`BaseHTTPMiddleware` que, si `AUTH_ENABLED=true`, exige header `X-Service-Key` == `SERVICE_API_KEY` y responde 401 si falta o no coincide. Si `AUTH_ENABLED=false` (default), deja pasar todo. Exime siempre `/health`, `/docs`, `/openapi.json`, `/redoc`.

## main.py

- Usar `lifespan` (no `@app.on_event`) para arrancar el janitor de auto-descarga en startup y descargar el modelo + parar el janitor en shutdown.
- CORS desde settings.
- Registrar el middleware de auth.
- Helpers: decodificar base64 (tolerando data URI, validando tamaño), leer upload (validando tamaño), y un wrapper de OCR que traduce excepciones a HTTPException 500.

## preload_models.py

Script opcional que instancia PaddleOCR una vez (mismos parámetros que el servicio) para forzar la descarga de modelos y evitar el timeout en la primera petición real. Imprime tiempo y maneja error de red con mensaje claro. No asume rutas ni entorno concreto.

## README.md (mínimo y genérico)

Mantenlo breve y sin información de ningún servidor concreto (sin IPs, hosts, rutas ni pasos de systemd/Docker). Cubre solo:
- Qué es el servicio y los 6 endpoints (tabla corta).
- Gestión de RAM: lazy load + lock de serialización + auto-descarga por inactividad.
- Instalación local genérica: crear venv, instalar requirements, copiar `.env.example` a `.env`, opcionalmente correr `preload_models.py`, y arrancar con uvicorn.
- Variables de entorno disponibles.
- Nota de compatibilidad: `numpy<2` es obligatorio con paddlepaddle 2.6.2.
- Aviso claro de que **el parser de INE necesita calibración con muestras reales** usando el `raw_text` que devuelve `/ine/extract`.

## Verificación final que debes hacer

Antes de terminar, comprueba tú mismo:
1. Que todos los `.py` compilan sin errores de sintaxis.
2. Que la app FastAPI importa y registra los 6 endpoints.
3. Que `validate_curp("HEGG560427MVZRRL04")` devuelve True.
4. Que el parser extrae los 14 campos del texto sintético de arriba.

No marques el trabajo como completo hasta que esas 4 verificaciones pasen. Si la instalación de paddlepaddle/paddleocr no es posible en tu entorno, déjalo documentado pero asegura que el resto del código (parser, CURP, schemas, estructura) sí esté verificado.
