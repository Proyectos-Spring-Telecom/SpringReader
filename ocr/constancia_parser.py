"""
Parser de Constancia de Situación Fiscal del SAT (México).

Portado de la versión TypeScript v4 en producción (NestJS).
Soporta persona física y moral sobre texto nativo u OCR.

ADVERTENCIA: las constancias del SAT varían por año y tipo de contribuyente,
y el OCR de escaneos añade ruido. Debe validarse con PDFs reales.
El campo raw_text de la respuesta existe para depurar y ajustar.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Etiquetas SAT reconocidas al inicio de línea
# ---------------------------------------------------------------------------

SAT_LABELS: list[str] = [
    "RFC:",
    "CURP:",
    "Nombre (s):",
    "Primer Apellido:",
    "Segundo Apellido:",
    "Denominación/Razón Social:",
    "Régimen Capital:",
    "Nombre Comercial:",
    "Fecha inicio de operaciones:",
    "Estatus en el padrón:",
    "Fecha de último cambio de estado:",
    "Datos del domicilio registrado",
    "Código Postal:",
    "Tipo de Vialidad:",
    "Nombre de Vialidad:",
    "Número Exterior:",
    "Número Interior:",
    "Nombre de la Colonia:",
    "Nombre de la Localidad:",
    "Nombre del Municipio o Demarcación Territorial:",
    "Nombre de la Entidad Federativa:",
    "Entre Calle:",
    "Y Calle:",
    "Actividades Económicas",
    "Regímenes:",
    "Obligaciones:",
    "Sus datos personales",
]

# Regex para detectar inicio de etiqueta SAT (escapado)
_LABEL_START_PATTERN = re.compile(
    r"^(" + "|".join(re.escape(lbl) for lbl in SAT_LABELS) + r")",
    re.IGNORECASE,
)

# Pie de página SAT (líneas de ruido)
_FOOTER_PATTERN = re.compile(
    r"^(Contacto|Av\.\s+Hid|MarcaSAT|\{?\+52\}?|\(\+52\)|Atenci[oó]n\s+telef|"
    r"Ce\s*$|^a\s*$|^Lo\s*$|^ATI$|^ET$|^EE$|^E$|=)",
    re.IGNORECASE,
)

# Si el valor empieza por otra etiqueta conocida → campo vacío
_NEXT_LABEL_PATTERN = re.compile(
    r"^(Fecha|Régimen|Estatus|Número|Nombre|Código|Tipo|Datos|Entre|Y Calle|"
    r"Actividades|Obligaciones|Sus datos|CURP|Primer|Segundo)",
    re.IGNORECASE,
)

_PAGE_NOISE_PATTERN = re.compile(r"Página\s+\d+\s+de\s+\d+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def join_continuation_lines(text: str) -> str:
    """Fusiona líneas de continuación; conserva líneas que empiezan por etiqueta SAT."""
    text = _normalize_newlines(text)
    lines = text.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        if _FOOTER_PATTERN.match(stripped):
            result.append("")
            continue

        if _LABEL_START_PATTERN.match(stripped):
            result.append(stripped)
        elif result:
            prev = result[-1]
            merged = (prev + " " + stripped).strip() if prev else stripped
            result[-1] = re.sub(r"\s+", " ", merged)
        else:
            result.append(stripped)

    return "\n".join(result)


def fix_porcentaje_pegado(text: str) -> str:
    """Inserta espacio entre letra y porcentaje pegados antes de fecha."""
    return re.sub(
        r"([a-zA-ZáéíóúÁÉÍÓÚñÑ])(\d{1,3})\s+(\d{2}/\d{2}/\d{4})",
        r"\1 \2 \3",
        text,
    )


def insert_separators(text: str) -> str:
    """Antepone salto de línea antes de cada etiqueta SAT."""
    for label in SAT_LABELS:
        escaped = re.escape(label)
        text = re.sub(escaped, "\n" + label, text, flags=re.IGNORECASE)
    return text


def between(text: str, start_re: str, end_re: str) -> str | None:
    """Valor entre etiqueta de inicio y siguiente etiqueta."""
    pattern = start_re + r"(.*?)(?=" + end_re + r"|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip()
    value = re.sub(r"\s+", " ", value)
    if not value:
        return None
    # Si no hay etiqueta de fin, tomar solo la primera línea no vacía
    if end_re not in text[m.start() : m.end() + len(end_re) + 50]:
        first_line = value.split("\n")[0].strip()
        return first_line if first_line else None
    return value


def between_non_empty(text: str, start_re: str, end_re: str) -> str | None:
    """Como between, pero null si el valor empieza por otra etiqueta conocida."""
    value = between(text, start_re, end_re)
    if value is None:
        return None
    if _NEXT_LABEL_PATTERN.match(value):
        return None
    return value


def match_field(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def clean_page_noise(value: str | None) -> str | None:
    if value is None:
        return None
    return _PAGE_NOISE_PATTERN.sub("", value).strip() or None


# ---------------------------------------------------------------------------
# Extracción de campos individuales
# ---------------------------------------------------------------------------


def extract_rfc(text: str) -> str | None:
    """Tres estrategias en orden."""
    # (1) Etiqueta RFC:
    m = re.search(r"RFC:\s*([A-Z&]{2,4}\d{6}[A-Z0-9]{2,4})", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # (2) Standalone al inicio de línea
    m = re.search(
        r"(?:^|\n)([A-Z&]{3,4}\d{6}[A-Z0-9]{2,4})(?:\s*$|\s+Datos de Identificaci)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        return m.group(1).upper()

    # (3) Patrón global
    m = re.search(r"\b([A-Z]{3,4}\d{6}[A-Z0-9]{3,4})\b", text)
    if m:
        return m.group(1).upper()

    return None


def parse_actividades(text: str) -> list[dict[str, Any]]:
    """Extrae tabla de actividades económicas."""
    block_m = re.search(
        r"Actividades Económicas(.*?)(?=\nReg[ií]menes:|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not block_m:
        return []

    block = block_m.group(1)
    block = re.sub(
        r"Orden\s+Actividad\s+Econ[oó]mica\s+Porcentaje\s+Fecha\s+Inicio\s+Fecha\s+Fin",
        "",
        block,
        flags=re.IGNORECASE,
    ).strip()

    row_pattern = re.compile(
        r"(\d+)\s+(.+?)\s+(\d{1,3})\s+(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}/\d{2}/\d{4}))?",
        re.IGNORECASE,
    )

    actividades: list[dict[str, Any]] = []

    if "\n" not in block.strip() or len(block.split("\n")) <= 2:
        # PDF nativo plano: regex global con finditer
        for m in row_pattern.finditer(block):
            actividades.append(_actividad_from_match(m))
    else:
        # OCR multilínea: acumular líneas
        accumulated = ""
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            accumulated = (accumulated + " " + line).strip()
            m = row_pattern.search(accumulated)
            if m:
                actividades.append(_actividad_from_match(m))
                accumulated = ""

    return actividades


def _actividad_from_match(m: re.Match) -> dict[str, Any]:
    return {
        "orden": int(m.group(1)),
        "descripcion": m.group(2).strip(),
        "porcentaje": int(m.group(3)),
        "fechaInicio": m.group(4),
        "fechaFin": m.group(5) if m.lastindex and m.lastindex >= 5 and m.group(5) else None,
    }


def parse_regimenes(text: str) -> list[dict[str, Any]]:
    """Extrae tabla de regímenes fiscales."""
    block_m = re.search(
        r"\nReg[ií]menes:(.*?)(?=\nObligaciones:|\nSus datos personales|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not block_m:
        return []

    block = block_m.group(1)
    block = re.sub(
        r"R[eé]gimen\s+Fecha\s+Inicio\s+Fecha\s+Fin",
        "",
        block,
        flags=re.IGNORECASE,
    ).strip()

    row_pattern = re.compile(
        r"(.+?)\s+(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}/\d{2}/\d{4}))?",
        re.IGNORECASE,
    )

    regimenes: list[dict[str, Any]] = []
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = row_pattern.search(line)
        if m:
            regimenes.append({
                "descripcion": m.group(1).strip(),
                "fechaInicio": m.group(2),
                "fechaFin": m.group(3) if m.lastindex and m.lastindex >= 3 and m.group(3) else None,
            })

    return regimenes


def parse_obligaciones(text: str) -> list[dict[str, Any]]:
    """Extrae tabla de obligaciones fiscales."""
    block_m = re.search(
        r"Obligaciones:(.*?)(?=Sus datos personales|Cadena Original|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not block_m:
        return []

    block = block_m.group(1)
    block = re.sub(
        r"Descripci[oó]n\s+Vencimiento\s+Fecha\s+Inicio\s+Fecha\s+Fin",
        "",
        block,
        flags=re.IGNORECASE,
    ).strip()

    # Insertar salto antes de fechas pegadas
    block = re.sub(r"(\d{2}/\d{2}/\d{4})", r"\n\1", block)

    vencimiento_pattern = re.compile(
        r"(Conjuntamente|A más tardar|Dentro de los|Al momento)",
        re.IGNORECASE,
    )
    fecha_pattern = re.compile(r"^\d{2}/\d{2}/\d{4}")

    obligaciones: list[dict[str, Any]] = []
    pending_desc: str | None = None

    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue

        if fecha_pattern.match(line):
            # Cierra obligación pendiente
            parts = line.split()
            fecha_inicio = parts[0] if parts else None
            fecha_fin = parts[1] if len(parts) > 1 else None

            if pending_desc:
                vm = vencimiento_pattern.search(pending_desc)
                vencimiento = vm.group(1) if vm else None
                descripcion = vencimiento_pattern.sub("", pending_desc).strip()
                obligaciones.append({
                    "descripcion": descripcion,
                    "vencimiento": vencimiento,
                    "fechaInicio": fecha_inicio,
                    "fechaFin": fecha_fin,
                })
                pending_desc = None
        else:
            if pending_desc:
                pending_desc = pending_desc + " " + line
            else:
                pending_desc = line

    return obligaciones


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------


def parse_constancia_fiscal(text: str) -> dict[str, Any]:
    """
    Pipeline completo: normalización → extracción de campos y tablas.
    Devuelve dict con claves camelCase esperadas por el consumidor.
    """
    text = join_continuation_lines(text)
    text = fix_porcentaje_pegado(text)
    text = insert_separators(text)

    tipo = (
        "PERSONA_FISICA"
        if re.search(r"Nombre \(s\):", text, re.IGNORECASE)
        else "PERSONA_MORAL"
    )

    rfc = extract_rfc(text)

    data: dict[str, Any] = {
        "tipoContribuyente": tipo,
        "rfc": rfc,
        "idCIF": match_field(text, r"idCIF:\s*(\d+)"),
        "curp": match_field(text, r"CURP:\s*([A-Z0-9]{18})"),
        "nombre": between(text, r"Nombre \(s\):", r"\nPrimer Apellido:"),
        "apellidoPaterno": between(text, r"Primer Apellido:", r"\nSegundo Apellido:"),
        "apellidoMaterno": between(
            text, r"Segundo Apellido:", r"\nFecha inicio de operaciones:"
        ),
        "razonSocial": between(
            text, r"Denominación/Razón Social:", r"\nRégimen Capital:"
        ),
        "regimenCapital": between(text, r"Régimen Capital:", r"\nNombre Comercial:"),
        "nombreComercial": between_non_empty(
            text,
            r"Nombre Comercial:",
            r"\n(Fecha inicio de operaciones:|Datos del domicilio)",
        ),
        "fechaInicioOperaciones": between(
            text, r"Fecha inicio de operaciones:", r"\nEstatus en el padrón:"
        ),
        "estatusContribuyente": between(
            text, r"Estatus en el padrón:", r"\nFecha de último cambio de estado:"
        ),
        "fechaUltimoCambioEstado": between(
            text,
            r"Fecha de último cambio de estado:",
            r"\n(Nombre Comercial:|Datos del domicilio)",
        ),
        "codigoPostal": match_field(text, r"Código Postal:\s*(\d{4,5})"),
        "tipoVialidad": between(text, r"Tipo de Vialidad:", r"\nNombre de Vialidad:"),
        "nombreVialidad": between(
            text, r"Nombre de Vialidad:", r"\nNúmero Exterior:"
        ),
        "numeroExterior": between(text, r"Número Exterior:", r"\nNúmero Interior:"),
        "numeroInterior": between_non_empty(
            text, r"Número Interior:", r"\nNombre de la Colonia:"
        ),
        "colonia": between(
            text, r"Nombre de la Colonia:", r"\nNombre de la Localidad:"
        ),
        "localidad": between(
            text, r"Nombre de la Localidad:",
            r"\nNombre del Municipio o Demarcación Territorial:",
        ),
        "municipio": between(
            text,
            r"Nombre del Municipio o Demarcación Territorial:",
            r"\nNombre de la Entidad Federativa:",
        ),
        "entidadFederativa": clean_page_noise(
            between(
                text,
                r"Nombre de la Entidad Federativa:",
                r"\n(Entre Calle:|Actividades)",
            )
        ),
        "entreCalle": clean_page_noise(
            between(text, r"Entre Calle:", r"\nY Calle:")
        ),
        "yCalle": clean_page_noise(
            between(text, r"Y Calle:", r"\n(Actividades|Regímenes)")
        ),
        "actividadesEconomicas": parse_actividades(text),
        "regimenesFiscales": parse_regimenes(text),
        "obligaciones": parse_obligaciones(text),
    }

    if rfc:
        logger.debug("Constancia parseada RFC=%s actividades=%d", rfc, len(data["actividadesEconomicas"]))

    return data


# ---------------------------------------------------------------------------
# Test sintético
# ---------------------------------------------------------------------------

_TEXTO_SINTETICO = """
RFC: XAXX010101000
CURP: XAXX010101HDFXXX00
Nombre (s): JUAN
Primer Apellido: PEREZ
Segundo Apellido: LOPEZ
Fecha inicio de operaciones: 01/01/2020
Estatus en el padrón: ACTIVO
Fecha de último cambio de estado: 15/06/2021
Datos del domicilio registrado
Código Postal: 06600
Tipo de Vialidad: CALLE
Nombre de Vialidad: REFORMA
Número Exterior: 123
Número Interior:
Nombre de la Colonia: CENTRO
Nombre de la Localidad: CIUDAD DE MEXICO
Nombre del Municipio o Demarcación Territorial: CUAUHTEMOC
Nombre de la Entidad Federativa: CIUDAD DE MEXICO
Actividades Económicas
Orden Actividad Económica Porcentaje Fecha Inicio Fecha Fin
1 Comercio al por menor 100 01/01/2020
Regímenes:
Régimen Fecha Inicio Fecha Fin
Régimen de Incorporación Fiscal 01/01/2020
Obligaciones:
Descripción Vencimiento Fecha Inicio Fecha Fin
Declaración anual A más tardar el 30 de abril 01/01/2020
"""


def _test_parser_sintetico() -> None:
    datos = parse_constancia_fiscal(_TEXTO_SINTETICO)

    assert datos["tipoContribuyente"] == "PERSONA_FISICA"
    assert datos["rfc"] == "XAXX010101000"
    assert datos["curp"] is not None
    assert datos["codigoPostal"] == "06600"
    assert len(datos["actividadesEconomicas"]) >= 1
    assert len(datos["regimenesFiscales"]) >= 1
    assert len(datos["obligaciones"]) >= 1

    print("=== Test sintético Constancia Fiscal ===")
    print(f"  RFC: {datos['rfc']}")
    print(f"  tipo: {datos['tipoContribuyente']}")
    print(f"  actividades: {len(datos['actividadesEconomicas'])}")
    print(f"  regimenes: {len(datos['regimenesFiscales'])}")
    print(f"  obligaciones: {len(datos['obligaciones'])}")
    print("OK — campos y tablas poblados.")


if __name__ == "__main__":
    _test_parser_sintetico()
