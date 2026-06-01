"""
Parser de Constancia de Situación Fiscal del SAT (México).

ADVERTENCIA: validar con PDFs reales. PaddleOCR sustituye acentos (ü→ú, C6digo→Código).
El campo raw_text de /constancia-fiscal/extract existe para depurar y calibrar.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

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

_LABEL_START_PATTERN = re.compile(
    r"^(" + "|".join(re.escape(lbl) for lbl in SAT_LABELS) + r")",
    re.IGNORECASE,
)

_FOOTER_PATTERN = re.compile(
    r"^(Contacto|Av\.\s*Hid|MarcaSAT|MarcasAT|\{?\+52\}?|\(\+52\)|"
    r"Atenci[oó]n\s+telef|Ce\s*$|^a\s*$|^Lo\s*$|^ATI$|^ET$|^EE$|^E$|=)",
    re.IGNORECASE,
)

_NEXT_LABEL_PATTERN = re.compile(
    r"^(Fecha|Régimen|Estatus|Número|Nombre|Código|Tipo|Datos|Entre|Y Calle|"
    r"Actividades|Obligaciones|Sus datos|CURP|Primer|Segundo)",
    re.IGNORECASE,
)

_PAGE_NOISE_PATTERN = re.compile(r"P[aá]gina\s+\[\d+\]\s+de\s+\[\d+\]", re.IGNORECASE)

_VENCIMIENTO_PATTERN = re.compile(
    r"(Conjuntamente|A\s+m[aá]s\s+tardar|Dentro\s+de\s+los|Al\s+momento)",
    re.IGNORECASE,
)

_RE_FECHA = re.compile(r"\d{2}/\d{2}/\d{4}")
_RE_SOLO_PORCENTAJE = re.compile(r"^\d{1,3}$")
_RE_SOLO_FECHA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_SOLO_ORDEN = re.compile(r"^\d{1,2}$")

_HEADER_TABLE_WORDS = re.compile(
    r"^(Orden|Actividad|Econ[oó]mica|Porcentaje|Fecha|Inicio|Fin|R[eé]gimen|"
    r"Obligaci[oó]n|Descripci[oó]n|Vencimiento|Contacto|HACIENDA|SAT|P[aá]gina|"
    r"MarcasAT|Atenci[oó]n|Valida|FISCAL|social|DE\s+2024)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Paso 0: normalización de acentos OCR
# ---------------------------------------------------------------------------


def normalize_ocr_accents(text: str) -> str:
    """Corrige sustituciones típicas de PaddleOCR en constancias SAT."""
    replacements = {
        "ü": "ú",
        "Ü": "Ú",
        "ä": "á",
        "Ä": "Á",
        "ö": "ó",
        "Ö": "Ó",
        "ë": "é",
        "Ë": "É",
        "ï": "í",
        "Ï": "Í",
    }
    for wrong, right in replacements.items():
        text = text.replace(wrong, right)
    text = re.sub(r"C6digo", "Código", text, flags=re.IGNORECASE)
    return text


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def join_continuation_lines(text: str) -> str:
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
            continue

        # SALINAS tras "Número Exterior: 410" → continúa nombre de vialidad (línea -2)
        if (
            re.fullmatch(r"[A-ZÁÉÍÓÚÑ ]{2,}", stripped)
            and len(result) >= 2
            and re.search(r"N[uú]mero\s+Exterior:\s*\d", result[-1], re.IGNORECASE)
            and re.search(r"Nombre\s+de\s+Vialidad:", result[-2], re.IGNORECASE)
        ):
            result[-2] = re.sub(r"\s+", " ", f"{result[-2]} {stripped}").strip()
            continue

        if result:
            prev = result[-1]
            merged = (prev + " " + stripped).strip() if prev else stripped
            result[-1] = re.sub(r"\s+", " ", merged)
        else:
            result.append(stripped)

    return "\n".join(result)


def fix_porcentaje_pegado(text: str) -> str:
    return re.sub(
        r"([a-zA-ZáéíóúÁÉÍÓÚñÑ])(\d{1,3})\s+(\d{2}/\d{2}/\d{4})",
        r"\1 \2 \3",
        text,
    )


def insert_separators(text: str) -> str:
    for label in sorted(SAT_LABELS, key=len, reverse=True):
        escaped = re.escape(label)
        text = re.sub(escaped, "\n" + label, text, flags=re.IGNORECASE)
    return text


def between(text: str, start_re: str, end_re: str) -> str | None:
    pattern = start_re + r"(.*?)(?=" + end_re + r"|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    value = re.sub(r"\s+", " ", m.group(1).strip())
    if not value:
        return None
    end_found = re.search(end_re, text[m.end() : m.end() + 200], re.IGNORECASE)
    if not end_found:
        first_line = value.split("\n")[0].strip()
        return first_line if first_line else None
    return value


def between_non_empty(text: str, start_re: str, end_re: str) -> str | None:
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


def extract_rfc(text: str) -> str | None:
    m = re.search(r"RFC:\s*([A-Z&]{2,4}\d{6}[A-Z0-9]{2,4})", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(
        r"(?:^|\n)([A-Z&]{3,4}\d{6}[A-Z0-9]{2,4})(?:\s*$|\s+Datos de Identificaci)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([A-Z]{3,4}\d{6}[A-Z0-9]{3,4})\b", text)
    if m:
        return m.group(1).upper()
    return None


def _is_noise_line(line: str) -> bool:
    if not line or _HEADER_TABLE_WORDS.match(line):
        return True
    if _FOOTER_PATTERN.match(line):
        return True
    if _PAGE_NOISE_PATTERN.search(line):
        return True
    return False


def _extract_actividades_block(text: str) -> str:
    reg_m = re.search(r"\nReg[ií]menes:|Regimenes:", text, re.IGNORECASE)
    if not reg_m:
        return ""
    act_matches = list(re.finditer(r"Actividades\s+Econ[oó]micas:?", text, re.IGNORECASE))
    if not act_matches:
        return ""
    start = act_matches[-1].end()
    return text[start : reg_m.start()]


def _clean_actividades_block(block: str) -> str:
    block = _PAGE_NOISE_PATTERN.sub(" ", block)
    block = re.sub(
        r"Orden\s+Actividad\s+Econ[oó]mica\s+Porcentaje\s+Fecha\s+Inicio\s+Fecha\s+Fin",
        " ",
        block,
        flags=re.IGNORECASE,
    )
    block = re.sub(
        r"Contacto.*?\+52\d+",
        " ",
        block,
        flags=re.IGNORECASE | re.DOTALL,
    )
    block = re.sub(r"\s+", " ", block).strip()
    return block


def _parse_actividades_flat(block: str) -> list[dict[str, Any]]:
    """Tabla fusionada en una línea (común tras joinContinuationLines + OCR)."""
    row_re = re.compile(
        r"([A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ0-9 ,.\-]{8,}?)\s+"
        r"(\d{1,3})\s+"
        r"(\d{2}/\d{2}/\d{4})",
        re.IGNORECASE,
    )
    actividades: list[dict[str, Any]] = []
    orden = 0
    for m in row_re.finditer(block):
        desc = re.sub(r"\s+", " ", m.group(1)).strip()
        desc = re.sub(r"^\d{1,2}\s+", "", desc).strip()
        if len(desc) < 8 or _HEADER_TABLE_WORDS.match(desc):
            continue
        orden += 1
        actividades.append({
            "orden": orden,
            "descripcion": desc,
            "porcentaje": int(m.group(2)),
            "fechaInicio": m.group(3),
            "fechaFin": None,
        })
    return actividades


def _parse_actividades_multiline(lines: list[str]) -> list[dict[str, Any]]:
    actividades: list[dict[str, Any]] = []
    desc_parts: list[str] = []
    orden = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        if _RE_SOLO_ORDEN.match(line):
            i += 1
            continue
        if _RE_SOLO_PORCENTAJE.match(line) and desc_parts:
            porcentaje = int(line)
            fecha_inicio: str | None = None
            if i + 1 < len(lines) and _RE_SOLO_FECHA.match(lines[i + 1]):
                fecha_inicio = lines[i + 1]
                i += 1
            descripcion = re.sub(r"\s+", " ", " ".join(desc_parts)).strip()
            descripcion = re.sub(r"\s+\d{1,2}$", "", descripcion).strip()
            if descripcion and len(descripcion) > 3:
                orden += 1
                actividades.append({
                    "orden": orden,
                    "descripcion": descripcion,
                    "porcentaje": porcentaje,
                    "fechaInicio": fecha_inicio,
                    "fechaFin": None,
                })
            desc_parts = []
            i += 1
            continue
        if _RE_SOLO_FECHA.match(line):
            i += 1
            continue
        desc_parts.append(line)
        i += 1
    return actividades


def parse_actividades(text: str) -> list[dict[str, Any]]:
    block = _clean_actividades_block(_extract_actividades_block(text))
    if not block:
        return []

    # Modo plano: una o pocas líneas muy largas
    lines = [ln.strip() for ln in block.split("\n") if ln.strip() and not _is_noise_line(ln.strip())]
    if len(lines) <= 2 or any(len(ln) > 200 for ln in lines):
        flat = _parse_actividades_flat(block if len(block) > 200 else " ".join(lines))
        if flat:
            return flat

    return _parse_actividades_multiline(lines)


def parse_regimenes(text: str) -> list[dict[str, Any]]:
    block_m = re.search(
        r"Reg[ií]menes:?(.*?)(?=Obligaciones:|Sus datos personales|Cadena Original|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not block_m:
        return []

    block = re.sub(
        r"R[eé]gimen\s+Fecha\s+Inicio\s+Fecha\s+Fin",
        " ",
        block_m.group(1),
        flags=re.IGNORECASE,
    )
    block = re.sub(r"\s+", " ", block).strip()

    regimenes: list[dict[str, Any]] = []
    row_re = re.compile(
        r"([A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ0-9 ,.\-]{5,}?)\s+"
        r"(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}/\d{2}/\d{4}))?",
        re.IGNORECASE,
    )
    for m in row_re.finditer(block):
        desc = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(desc) < 5 or _HEADER_TABLE_WORDS.match(desc):
            continue
        regimenes.append({
            "descripcion": desc,
            "fechaInicio": m.group(2),
            "fechaFin": m.group(3) if m.lastindex and m.lastindex >= 3 else None,
        })

    return regimenes


def parse_obligaciones(text: str) -> list[dict[str, Any]]:
    block_m = re.search(
        r"Obligaciones:?(.*?)(?=Sus datos personales|Cadena Original|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not block_m:
        return []

    block = block_m.group(1)
    block = re.sub(
        r"Descripci[oó]n\s+de\s+la\s+Obligaci[oó]n.*?Fecha\s+Fin",
        " ",
        block,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    block = re.sub(
        r"Descripci[oó]n\s+Vencimiento\s+Fecha\s+Inicio\s+Fecha\s+Fin",
        " ",
        block,
        flags=re.IGNORECASE,
    )
    block = re.sub(r"\s+", " ", block).strip()

    obligaciones: list[dict[str, Any]] = []

    # Partir por fechas; cada segmento es una obligación
    partes = re.split(r"(\d{2}/\d{2}/\d{4})", block)
    i = 1
    while i < len(partes):
        cuerpo = partes[i - 1].strip()
        fecha = partes[i]
        i += 2
        # Texto después de la fecha que pertenece al vencimiento (continuación)
        cola = partes[i].strip() if i < len(partes) else ""
        if cola and not _RE_FECHA.search(cola[:20]):
            # Solo tomar fragmento corto de cola (cierre de vencimiento)
            cola_corta = re.split(
                r"(?=[A-ZÁÉÍÓÚ][a-záéíóúñ]{3,}.*?(?:ISR|IVA|retenciones|Declaraci))",
                cola,
                maxsplit=1,
            )[0].strip()
            if cola_corta and len(cola_corta) < 120:
                cuerpo = f"{cuerpo} {cola_corta}"

        vm = _VENCIMIENTO_PATTERN.search(cuerpo)
        vencimiento: str | None = None
        descripcion = cuerpo
        if vm:
            vencimiento = cuerpo[vm.start() :].strip()
            descripcion = cuerpo[: vm.start()].strip()
            vencimiento = re.sub(
                r"\s+posterior al periodo que corresponda\.?\s*$",
                " posterior al periodo que corresponda.",
                vencimiento,
                flags=re.IGNORECASE,
            ).strip()

        descripcion = re.sub(r"\s+", " ", descripcion).strip()
        if descripcion and len(descripcion) > 8 and not _HEADER_TABLE_WORDS.match(descripcion):
            obligaciones.append({
                "descripcion": descripcion,
                "vencimiento": vencimiento,
                "fechaInicio": fecha,
                "fechaFin": None,
            })

    # Fallback multilínea si el split no produjo nada
    if not obligaciones:
        lines = [ln.strip() for ln in block_m.group(1).split("\n") if ln.strip()]
        buffer: list[str] = []

        def _flush(fecha_line: str) -> None:
            nonlocal buffer
            if not buffer:
                return
            joined = re.sub(r"\s+", " ", " ".join(buffer)).strip()
            buffer = []
            vm = _VENCIMIENTO_PATTERN.search(joined)
            if vm:
                obligaciones.append({
                    "descripcion": joined[: vm.start()].strip(),
                    "vencimiento": joined[vm.start() :].strip(),
                    "fechaInicio": fecha_line,
                    "fechaFin": None,
                })
            elif len(joined) > 8:
                obligaciones.append({
                    "descripcion": joined,
                    "vencimiento": None,
                    "fechaInicio": fecha_line,
                    "fechaFin": None,
                })

        for line in lines:
            if _RE_SOLO_FECHA.match(line):
                _flush(line)
            elif not _is_noise_line(line):
                buffer.append(line)

    return obligaciones


def parse_constancia_fiscal(text: str) -> dict[str, Any]:
    text = normalize_ocr_accents(text)
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
            r"\n(Fecha inicio|Datos del domicilio)",
        ),
        "fechaInicioOperaciones": between(
            text, r"Fecha inicio de operaciones:", r"\nEstatus en el padrón:"
        ),
        "estatusContribuyente": between(
            text, r"Estatus en el padrón:", r"\nFecha de último cambio"
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
        "colonia": between(text, r"Nombre de la Colonia:", r"\nNombre de la Localidad:"),
        "localidad": between(
            text, r"Nombre de la Localidad:", r"\nNombre del Municipio"
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
                r"\nEntre Calle:",
            )
        ),
        "entreCalle": clean_page_noise(between(text, r"Entre Calle:", r"\nY Calle:")),
        "yCalle": clean_page_noise(
            between(text, r"Y Calle:", r"\n(Actividades|Regímenes)")
        ),
        "actividadesEconomicas": parse_actividades(text),
        "regimenesFiscales": parse_regimenes(text),
        "obligaciones": parse_obligaciones(text),
    }

    if rfc:
        logger.info(
            "Constancia RFC=%s actividades=%d regimenes=%d obligaciones=%d",
            rfc,
            len(data["actividadesEconomicas"]),
            len(data["regimenesFiscales"]),
            len(data["obligaciones"]),
        )

    return data


# ---------------------------------------------------------------------------
# Test con OCR real (constancia persona moral ICB190202E4A)
# ---------------------------------------------------------------------------

_TEXTO_OCR_REAL = """
CÉDULA DE IDENTIFICACIóN FISCAL
HACIENDA
SAT
CONSTANCIA DE SITUACION FISCAL
ICB190202E4A
Registro Federal de Contribuyentes
INMOBILIARIA Y
CONSTRUCTORA BERLET
Lugar y Fecha de Emisión
SANTA CATARINA , NUEVO LEON A 31 DE OCTUBRE
Nombre, denominación o razón
social
DE 2024
idCIF: 19020096029
VALIDA TU INFORMACIóN
FISCAL
ICB190202E4A
Datos de Identificación del Contribuyente:
RFC:
ICB190202E4A
Denominación/Razón Social:
INMOBILIARIA Y CONSTRUCTORA BERLET
Régimen Capital:
SOCIEDAD ANONIMA DE CAPITAL VARIABLE
Nombre Comercial:
INMOBILIARIA Y CONSTRUCTORA BERLET
Fecha inicio de operaciones:
 02 DE FEBRERO DE 2019
Estatus en el padrón:
ACTIVO
Fecha de último cambio de estado:
02 DE FEBRERO DE 2019
Datos del domicilio registrado
C6digo Postal:66129
Tipo de Vialidad: CALLE
Nombre de Vialidad: FRACCIONAMIENTO LICENCIADO PORFIRIO
Nümero Exterior: 410
SALINAS
Nümero Interior:
Nombre de la Colonia: PRADOS DE SAN JORGE
Nombre de la Localidad: CIUDAD SANTA CATARINA
Nombre del Municipio o Demarcación Territorial: SANTA CATARINA
Nombre de la Entidad Federativa: NUEVO LEON
Entre Calle: TOPILTZIN
Y Calle: SIERRA MADRE
Actividades Económicas:
Página [1] de [3]
Contacto
HACIENDA
Av.Hidalgo 77.col.Cuerrero,C.p.06300,Ciudad de Mexico.
SAT
Atencion telefónica desce cualquier parte del pais.
MarcasAT 5562722728ypara el exterior del pais
+525562722728

Orden
Actividad Económica
Porcentaje
Fecha Inicio
Fecha Fin
Otras construcciones de ingenieria civil u obra pesada
40
02/02/2019
Construcción de obras de urbanización
20
02/02/2019
2
Construcción de inmuebles comerciales, institucionales y de servicios
10
02/02/2019
4
Construcción de vivienda multifamiliar
10
02/02/2019
Comercio al por menor en Tiendas de autoservicio de materiales para la10
13/10/2020
5
autoconstrucción
Ai
Construcción de obras para transporte eléctrico y ferroviario
10
04/07/2022
Regimenes:
Régimen
Fecha Inicio
Fecha Fin
Régimen General de Ley Personas Morales
02/02/2019
Obligaciones:
Descripción de la Obligación
Descripción Vencimiento
Fecha Inicio
Fecha Fin
Entero de retenciones mensuales de ISR por sueldos y salarios
A más tardar el dia 17 del mes inmediato
02/02/2019
posterior al periodo que corresponda.
Declaración anual de ISR del ejercicio Personas morales
Dentro de los tres meses siguientes al cierre del
02/02/2019
ejercicio.
Pago definitivo mensual de IVA.
A más tardar el dia 17 del mes inmediato
02/02/2019
posterior al periodo que corresponda.
Declaración de proveedores de IVA
A más tardar el ültimo dia del mes inmediato
02/02/2019
posterior al periodo que corresponda.
Pago provisional mensual de ISR personas morales régimen
A mäs tardar el dia 17 del mes inmediato
01/04/2020
general
posterior al periodo que corresponda.
Pago provisional trimestral de ISR de personas morales por inicio A mäs tardar el dia 17 del mes inmediato
13/10/2020
de segundo ejercicio. Régimen General.
posterior al periodo que corresponda.
"""


def _test_parser_ocr_real() -> None:
    datos = parse_constancia_fiscal(_TEXTO_OCR_REAL)

    assert datos["tipoContribuyente"] == "PERSONA_MORAL", datos["tipoContribuyente"]
    assert datos["rfc"] == "ICB190202E4A", datos["rfc"]
    assert datos["codigoPostal"] == "66129", datos["codigoPostal"]
    assert datos["idCIF"] == "19020096029", datos["idCIF"]

    assert len(datos["actividadesEconomicas"]) == 6, len(datos["actividadesEconomicas"])
    assert len(datos["regimenesFiscales"]) >= 1, datos["regimenesFiscales"]
    assert "General" in datos["regimenesFiscales"][0]["descripcion"]
    assert len(datos["obligaciones"]) == 6, len(datos["obligaciones"])

    nv = datos.get("nombreVialidad") or ""
    assert "FRACCIONAMIENTO" in nv and "PORFIRIO" in nv, nv
    ne = datos.get("numeroExterior") or ""
    assert "410" in ne, ne

    print("=== Test OCR real Constancia Fiscal ===")
    print(f"  RFC: {datos['rfc']}")
    print(f"  CP: {datos['codigoPostal']}")
    print(f"  actividades: {len(datos['actividadesEconomicas'])}")
    print(f"  regimenes: {len(datos['regimenesFiscales'])}")
    print(f"  obligaciones: {len(datos['obligaciones'])}")
    print(f"  nombreVialidad: {nv[:60]}...")
    print("OK — verificaciones OCR real pasaron.")


if __name__ == "__main__":
    _test_parser_ocr_real()
