"""
ine_parser.py — Parser de credencial para votar (INE) mexicana.

VERSIÓN 3 — calibrado con múltiples INE reales de PaddleOCR.

Lección central: el OCR NO siempre devuelve las líneas en orden visual (puede
intercalar etiquetas o invertir el orden). Por eso el parser NO se apoya en
posiciones, sino en lo que es estructuralmente identificable:

    * CURP (con dígito verificador): codifica iniciales de apellidos/nombre,
      fecha, sexo y estado. Es el ancla principal para asignar apellido paterno,
      materno y nombre, sin depender del orden de líneas.
    * Clave de elector: respaldo del sexo y de la estructura.
    * MRZ del reverso: fecha, vigencia, sexo y nombres (APELLIDOS<<NOMBRES).
    * Formato de cada dato (regex) en lugar de "la línea N".

Domicilio (3 líneas tras DOMICILIO, según los casos reales):
    L1: [marcador vialidad: '-', AV, C, CALLE...] calle y número  -> domicilio
    L2: [abrev asentamiento: COL, U/UHAB, FRACC, RDCIAL...] colonia + CP -> colonia, CP
    L3: MUNICIPIO , ESTADO(abrev)  -> municipio, estado
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Correcciones de OCR (token pegado -> separado). Ampliar con casos nuevos.
# --------------------------------------------------------------------------- #
CORRECCIONES_OCR: Dict[str, str] = {
    "NACIONALELECTORAL": "NACIONAL ELECTORAL",
    "CREDENCIALPARAVOTAR": "CREDENCIAL PARA VOTAR",
    "CREDENCIALPARA VOTAR": "CREDENCIAL PARA VOTAR",
    "CLAVEDEELECTOR": "CLAVE DE ELECTOR",
    "CLAVE DEELECTOR": "CLAVE DE ELECTOR",
    "CLAVE DE ELECTOR": "CLAVE DE ELECTOR",
    "ANODEREGISTRO": "ANO DE REGISTRO",
    "ANODE REGISTRO": "ANO DE REGISTRO",
    "FECHADENACIMIENTO": "FECHA DE NACIMIENTO",
    "FECHADENACIMENTO": "FECHA DE NACIMIENTO",
}

PREFIJOS_VIALIDAD = [
    "PROLONGACION", "PRIVADA", "CIRCUITO", "CERRADA", "ANDADOR", "AVENIDA",
    "CALZADA", "BOULEVARD", "CARRETERA", "RETORNO", "CALLE", "PASEO", "EJE",
    "AV", "BLVD", "CALZ",
]
PREFIJOS_ASENTAMIENTO = [
    "FRACCIONAMIENTO", "UNIDAD HABITACIONAL", "RESIDENCIAL", "AMPLIACION",
    "FRACC", "RDCIAL", "RDCIA", "UHAB", "BARRIO", "PUEBLO", "COL", "U",
]
PARTICULAS = ["DEL", "DE", "LA", "LAS", "LOS", "EL", "Y", "SAN", "SANTA"]

TOKENS_DOMICILIO = [
    "PROLONGACION", "REFORMA", "PASEO", "ESTADO", "PUEBLA", "CARDENAS",
    "LAZARO", "CUERNAVACA", "LOMAS", "MISION", "AMARANTTO", "MADERO",
    "GUSTAVO", "EMILIANO", "ZAPATA", "TEMIXCO", "ARAGON", "JUAN", "SAN",
    "MIGUEL", "HIDALGO", "JUAREZ", "MORELOS", "ALLENDE", "INSURGENTES",
    "REVOLUCION", "INDEPENDENCIA", "CASA", "MZ", "LT", "SECC",
]

ABREV_ESTADO = {
    "AGS": "AGUASCALIENTES", "BC": "BAJA CALIFORNIA", "BCS": "BAJA CALIFORNIA SUR",
    "CAMP": "CAMPECHE", "COAH": "COAHUILA", "COL": "COLIMA", "CHIS": "CHIAPAS",
    "CHIH": "CHIHUAHUA", "CDMX": "CIUDAD DE MEXICO", "DF": "CIUDAD DE MEXICO",
    "DGO": "DURANGO", "GTO": "GUANAJUATO", "GRO": "GUERRERO", "HGO": "HIDALGO",
    "JAL": "JALISCO", "MEX": "MEXICO", "EDOMEX": "MEXICO", "MICH": "MICHOACAN",
    "MOR": "MORELOS", "NAY": "NAYARIT", "NL": "NUEVO LEON", "OAX": "OAXACA",
    "PUE": "PUEBLA", "QRO": "QUERETARO", "QROO": "QUINTANA ROO",
    "SLP": "SAN LUIS POTOSI", "SIN": "SINALOA", "SON": "SONORA", "TAB": "TABASCO",
    "TAMS": "TAMAULIPAS", "TAM": "TAMAULIPAS", "TLAX": "TLAXCALA", "VER": "VERACRUZ",
    "YUC": "YUCATAN", "ZAC": "ZACATECAS",
}

CURP_ESTADO = {
    "AS": "AGUASCALIENTES", "BC": "BAJA CALIFORNIA", "BS": "BAJA CALIFORNIA SUR",
    "CC": "CAMPECHE", "CL": "COAHUILA", "CM": "COLIMA", "CS": "CHIAPAS",
    "CH": "CHIHUAHUA", "DF": "CIUDAD DE MEXICO", "DG": "DURANGO",
    "GT": "GUANAJUATO", "GR": "GUERRERO", "HG": "HIDALGO", "JC": "JALISCO",
    "MC": "MEXICO", "MN": "MICHOACAN", "MS": "MORELOS", "NT": "NAYARIT",
    "NL": "NUEVO LEON", "OC": "OAXACA", "PL": "PUEBLA", "QT": "QUERETARO",
    "QR": "QUINTANA ROO", "SP": "SAN LUIS POTOSI", "SL": "SINALOA",
    "SR": "SONORA", "TC": "TABASCO", "TS": "TAMAULIPAS", "TL": "TLAXCALA",
    "VZ": "VERACRUZ", "YN": "YUCATAN", "ZS": "ZACATECAS", "NE": "NACIDO EXTRANJERO",
}

ETIQUETAS = {
    "NOMBRE", "DOMICILIO", "CURP", "SEXO", "SEXOH", "SEXOM", "VIGENCIA",
    "SECCION", "LOCALIDAD", "MUNICIPIO", "ESTADO", "EMISION", "MEXICO",
    "FECHA DE NACIMIENTO", "CLAVE DE ELECTOR", "ANO DE REGISTRO",
    "INSTITUTO NACIONAL ELECTORAL", "CREDENCIAL PARA VOTAR", "INE", "AINE",
}

RE_CURP = re.compile(r"([A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d)")
RE_CLAVE_ELECTOR = re.compile(r"([A-Z]{6}\d{8}[HM]\d{3})")
RE_FECHA = re.compile(r"\b(\d{2}[/.\-]\d{2}[/.\-]\d{4})\b")


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #
def strip_accents(text: str) -> str:
    text = text.replace("Ñ", "\x01")
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return text.replace("\x01", "Ñ")


def normalize_text(raw: str) -> str:
    if not raw:
        return ""
    text = strip_accents(raw.upper())
    for wrong, right in CORRECCIONES_OCR.items():
        text = text.replace(wrong, right)
    return text


def _lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _separar_tokens(s: str, vocab: List[str]) -> str:
    for p in sorted(vocab, key=len, reverse=True):
        if s.startswith(p) and len(s) > len(p):
            return p + " " + s[len(p):]
    return s


def _separar_por_diccionario(s: str) -> str:
    out = s
    out = re.sub(r"([A-ZÑ])(\d)", r"\1 \2", out)
    out = re.sub(r"(\d)([A-ZÑ])(?![A-ZÑ])", r"\1 \2", out)

    for tok in sorted(TOKENS_DOMICILIO, key=len, reverse=True):
        if out.startswith(tok) and len(out) > len(tok) and out[len(tok)] != " ":
            out = tok + " " + out[len(tok):]
        out = re.sub(rf"(?<=[A-ZÑ]){tok}(?=[A-ZÑ0-9])", f" {tok} ", out)
    out = re.sub(r"\s+", " ", out).strip()

    palabras = out.split()
    fixed = []
    for w in palabras:
        sep = w
        for part in ("DEL", "DE", "LA"):
            m = re.match(rf"^([A-ZÑ]{{3,}})({part})([A-ZÑ]{{3,}})$", w)
            if m and (m.group(1) in TOKENS_DOMICILIO or m.group(3) in TOKENS_DOMICILIO):
                sep = f"{m.group(1)} {part} {m.group(3)}"
                break
        fixed.append(sep)
    return re.sub(r"\s+", " ", " ".join(fixed)).strip()


# --------------------------------------------------------------------------- #
# Anclas: CURP, clave de elector
# --------------------------------------------------------------------------- #
def extract_curp(text: str) -> Optional[str]:
    m = RE_CURP.search(text.replace(" ", ""))
    return m.group(1) if m else None


def extract_clave_elector(text: str) -> Optional[str]:
    m = RE_CLAVE_ELECTOR.search(text.replace(" ", ""))
    return m.group(1) if m else None


def _yymmdd_to_date(yymmdd: str) -> Optional[str]:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = yymmdd[:2], yymmdd[2:4], yymmdd[4:6]
    siglo = "20" if int(yy) <= 29 else "19"
    return f"{dd}/{mm}/{siglo}{yy}"


def _datos_desde_curp(curp: str) -> Dict[str, Optional[str]]:
    out = {
        "fechaNacimiento": None,
        "sexo": None,
        "estado": None,
        "ini_paterno": None,
        "ini_materno": None,
        "ini_nombre": None,
    }
    if not curp or len(curp) < 13:
        return out
    out["ini_paterno"] = curp[0]
    out["ini_materno"] = curp[2]
    out["ini_nombre"] = curp[3]
    out["fechaNacimiento"] = _yymmdd_to_date(curp[4:10])
    out["sexo"] = curp[10] if curp[10] in ("H", "M") else None
    out["estado"] = CURP_ESTADO.get(curp[11:13])
    return out


# --------------------------------------------------------------------------- #
# Nombres y apellidos — asignados por las iniciales de la CURP (no por orden)
# --------------------------------------------------------------------------- #
def extract_nombre_apellidos(
    frente_lines: List[str],
    curp: Optional[str],
    mrz_nombres: Optional[Dict[str, str]],
) -> Dict[str, Optional[str]]:
    result = {
        "apellidoPaterno": None,
        "apellidoMaterno": None,
        "nombre": None,
        "_sexo": None,
    }

    candidatos: List[str] = []
    for l in frente_lines:
        ms = re.match(r"^SEXO\s*([HM])$", l)
        if ms:
            result["_sexo"] = ms.group(1)
            continue
        if l in ETIQUETAS:
            continue
        if _es_etiqueta_rota(l):
            continue
        if RE_CURP.search(l.replace(" ", "")) or RE_CLAVE_ELECTOR.search(
            l.replace(" ", "")
        ):
            continue
        if re.fullmatch(r"[A-ZÑ ]{2,}", l) and l not in ETIQUETAS:
            if l in ("MEXICO", "INE", "AINE", "ESTADO"):
                continue
            candidatos.append(l)

    cd = _datos_desde_curp(curp) if curp else {}
    asign = {"apellidoPaterno": None, "apellidoMaterno": None, "nombre": None}
    if cd.get("ini_paterno"):
        usados = set()
        roles = [
            ("apellidoPaterno", cd["ini_paterno"]),
            ("apellidoMaterno", cd["ini_materno"]),
            ("nombre", cd["ini_nombre"]),
        ]
        for rol, ini in roles:
            for i, c in enumerate(candidatos):
                if i in usados:
                    continue
                if c[0] == ini:
                    asign[rol] = c
                    usados.add(i)
                    break
        result.update(asign)

    if not any(asign.values()):
        try:
            idx = next(i for i, l in enumerate(frente_lines) if l == "NOMBRE")
            bloque = [
                c
                for c in frente_lines[idx + 1 : idx + 6]
                if re.fullmatch(r"[A-ZÑ ]{2,}", c) and c not in ETIQUETAS
            ][:3]
            if len(bloque) >= 3:
                result["apellidoPaterno"], result["apellidoMaterno"], result["nombre"] = (
                    bloque[:3]
                )
            elif len(bloque) == 2:
                result["apellidoPaterno"], result["nombre"] = bloque
            elif bloque:
                result["nombre"] = bloque[0]
        except StopIteration:
            pass

    if mrz_nombres and mrz_nombres.get("nombres"):
        nom_mrz = mrz_nombres["nombres"]
        nom_frente = (result["nombre"] or "").replace(" ", "")
        if nom_frente:
            sep = _separar_por_prefijos(nom_frente, nom_mrz.split())
            if sep:
                result["nombre"] = sep
        elif not result["nombre"]:
            result["nombre"] = nom_mrz

    if result["nombre"] and " " not in result["nombre"]:
        result["nombre"] = _split_nombres_compuestos(result["nombre"])

    return result


def _separar_por_prefijos(pegado: str, palabras_guia: List[str]) -> Optional[str]:
    cortes = []
    pos = 0
    for w in palabras_guia:
        pref = w[:3] if len(w) >= 3 else w
        idx = pegado.find(pref, pos)
        if idx != -1:
            cortes.append(idx)
            pos = idx + len(pref)
    cortes = sorted(set(c for c in cortes if c >= 0))
    if not cortes or cortes[0] != 0:
        cortes = [0] + cortes
    cortes.append(len(pegado))
    cortes = sorted(set(cortes))
    partes = [pegado[cortes[i] : cortes[i + 1]] for i in range(len(cortes) - 1)]
    partes = [p for p in partes if p]
    return " ".join(partes) if len(partes) >= 2 else None


def _split_nombres_compuestos(token: str) -> str:
    comunes = [
        "MIGUEL", "ANGEL", "JOSE", "MARIA", "JUAN", "LUIS", "ANA",
        "BRENDA", "ALEJANDRA", "GUADALUPE", "CARLOS", "EDUARDO",
    ]
    out = token
    for c in sorted(comunes, key=len, reverse=True):
        out = re.sub(rf"(?<=[A-ZÑ]){c}", f" {c}", out)
        if out.startswith(c) and len(out) > len(c) and out[len(c)] != " ":
            out = c + " " + out[len(c):]
    return re.sub(r"\s+", " ", out).strip()


# --------------------------------------------------------------------------- #
# Domicilio
# --------------------------------------------------------------------------- #
def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _es_etiqueta_rota(l: str) -> bool:
    candidatos = [
        "NOMBRE", "DOMICILIO", "FECHADENACIMIENTO", "VIGENCIA",
        "SECCION", "LOCALIDAD", "MUNICIPIO", "REGISTRO", "ELECTOR",
        "CREDENCIAL", "INSTITUTO", "NACIONAL", "MEXICO",
    ]
    comp = re.sub(r"[^A-ZÑ]", "", l)
    if len(comp) < 4:
        return False
    for c in candidatos:
        if comp == c:
            return True
        if abs(len(comp) - len(c)) <= 2 and _lev(comp, c) <= 2:
            return True
    return False


def extract_domicilio(frente_lines: List[str]) -> Dict[str, Optional[str]]:
    result = {
        "domicilio": None,
        "colonia": None,
        "codigoPostal": None,
        "municipio": None,
        "estado": None,
    }

    idx = None
    for i, l in enumerate(frente_lines):
        comp = re.sub(r"[^A-ZÑ]", "", l)
        if comp.startswith("DOMICILIO") or comp in ("DOMCLC", "DOMCILIO", "DOMICLIO"):
            idx = i
            break

    bloque: List[str] = []
    if idx is not None:
        for l in frente_lines[idx + 1 : idx + 6]:
            if re.search(
                r"CLAVE|ELECTOR|CURP|REGISTRO|VIGENCIA|^SECCION|"
                r"^ESTADO|^MUNICIPIO|^LOCALIDAD|^EMISION",
                l,
            ):
                if bloque:
                    break
                continue
            if _es_etiqueta_rota(l) and bloque:
                break
            if _es_etiqueta_rota(l):
                continue
            bloque.append(l)
            if len(bloque) == 3:
                break

    if len(bloque) < 3:
        linea_muni = None
        for l in frente_lines:
            segs = [s.strip() for s in re.split(r"[,.]", l) if s.strip()]
            if segs and segs[-1].replace(".", "").strip() in ABREV_ESTADO:
                linea_muni = l
                break
        linea_col = None
        for l in frente_lines:
            if re.search(r"\d{5}\s*$", l) and not RE_CURP.search(l.replace(" ", "")):
                if not re.search(r"\d{6}", l):
                    linea_col = l
                    break
        linea_calle = None
        for l in frente_lines:
            comp = l
            if comp.startswith("-") or any(
                comp.startswith(p) for p in PREFIJOS_VIALIDAD + ["C"]
            ):
                if l not in (linea_col, linea_muni):
                    linea_calle = l
                    break
        bloque = [x for x in (linea_calle, linea_col, linea_muni) if x]

    if not bloque:
        return result

    l1 = bloque[0]
    marcador = l1.startswith("-")
    l1b = l1[1:] if marcador else l1
    l1b = _separar_tokens(l1b, PREFIJOS_VIALIDAD)
    l1b = _separar_por_diccionario(l1b)
    result["domicilio"] = ("-" + l1b if marcador else l1b).strip()

    if len(bloque) >= 2:
        l2 = bloque[1]
        mcp = re.search(r"(\d{5})\s*$", l2)
        if mcp:
            result["codigoPostal"] = mcp.group(1)
            col = l2[: mcp.start()]
        else:
            col = l2
        col = _separar_tokens(col, PREFIJOS_ASENTAMIENTO)
        for pref in sorted(PREFIJOS_ASENTAMIENTO, key=len, reverse=True):
            if col.startswith(pref + " "):
                col = col[len(pref) + 1 :]
                break
            if col.startswith(pref) and len(col) > len(pref):
                col = col[len(pref) :]
                break
        col = _separar_por_diccionario(col)
        col = re.sub(r"^(LA|EL|LOS|LAS)\s+", "", col)
        result["colonia"] = col.strip() or None

    if len(bloque) >= 3:
        l3 = bloque[2]
        segs = [s.strip() for s in re.split(r"[,.]", l3) if s.strip()]
        if segs:
            posible_estado = segs[-1].replace(".", "").strip()
            if posible_estado in ABREV_ESTADO:
                result["estado"] = ABREV_ESTADO[posible_estado]
                muni_segs = segs[:-1]
            else:
                muni_segs = segs
            muni = _separar_por_diccionario(" ".join(muni_segs))
            result["municipio"] = muni.strip() or None

    if not result["codigoPostal"]:
        m = re.search(r"\b(\d{5})\b", " ".join(bloque))
        if m:
            result["codigoPostal"] = m.group(1)

    return result


# --------------------------------------------------------------------------- #
# Campos finales: fecha, sección, vigencia (por tipo de dato, no por posición)
# --------------------------------------------------------------------------- #
def extract_campos_finales(frente_lines: List[str]) -> Dict[str, Optional[str]]:
    result = {"fechaNacimiento": None, "seccion": None, "vigencia": None}
    texto = "\n".join(frente_lines)

    mf = RE_FECHA.search(texto)
    if mf:
        result["fechaNacimiento"] = re.sub(r"[.\-]", "/", mf.group(1))

    mv = re.search(r"\b((?:19|20)\d{2})\s*[-–.]\s*((?:19|20)\d{2})\b", texto)
    if mv:
        result["vigencia"] = mv.group(2)

    for c in re.findall(r"(?<!\d)(\d{4})(?!\d)", texto):
        if not (1900 <= int(c) <= 2100):
            result["seccion"] = c
            break

    return result


# --------------------------------------------------------------------------- #
# MRZ del reverso
# --------------------------------------------------------------------------- #
def parse_mrz(reverso_text: str) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "fechaNacimiento": None,
        "sexo": None,
        "vigencia": None,
        "seccion": None,
        "apellidos": None,
        "nombres": None,
    }
    raw = [ln.strip() for ln in reverso_text.splitlines() if ln.strip()]

    for ln in raw:
        comp = ln.replace(" ", "")
        if "IDMEX" in comp.upper():
            m = re.search(r"<<(\d{4})", comp)
            if m:
                result["seccion"] = m.group(1)
            break

    for ln in raw:
        comp = ln.replace(" ", "")
        m = re.search(r"(\d{6})\d([MFX])(\d{6})", comp)
        if m:
            result["fechaNacimiento"] = _yymmdd_to_date(m.group(1))
            result["sexo"] = {"M": "H", "F": "M"}.get(m.group(2))
            venc = m.group(3)
            result["vigencia"] = ("20" if int(venc[:2]) <= 79 else "19") + venc[:2]
            break

    for ln in raw:
        comp = ln.replace(" ", "")
        if "IDMEX" in comp.upper() or "<<" not in ln:
            continue
        izq, _, der = ln.partition("<<")
        apell = izq.replace("<", " ").strip()
        nom = der.replace("<", " ").strip()
        if re.search(r"[A-Z]{2,}", apell) and not re.search(r"\d", apell):
            result["apellidos"] = re.sub(r"\s+", " ", apell)
            if nom and re.search(r"[A-Z]{2,}", nom):
                result["nombres"] = re.sub(r"\s+", " ", nom)
            break

    return result


# --------------------------------------------------------------------------- #
# Orquestador
# --------------------------------------------------------------------------- #
def parse_ine(frente_text: str, reverso_text: str = "") -> Dict[str, Optional[str]]:
    frente_norm = normalize_text(frente_text)
    frente_lines = _lines(frente_norm)
    reverso_norm = normalize_text(reverso_text)

    data: Dict[str, Optional[str]] = {
        "nombre": None,
        "apellidoPaterno": None,
        "apellidoMaterno": None,
        "curp": None,
        "claveElector": None,
        "fechaNacimiento": None,
        "sexo": None,
        "domicilio": None,
        "colonia": None,
        "codigoPostal": None,
        "municipio": None,
        "estado": None,
        "seccion": None,
        "vigencia": None,
    }

    todo = frente_norm + "\n" + reverso_norm
    data["curp"] = extract_curp(todo)
    data["claveElector"] = extract_clave_elector(frente_norm) or extract_clave_elector(
        todo
    )

    mrz = parse_mrz(reverso_text)

    na = extract_nombre_apellidos(frente_lines, data["curp"], mrz)
    data["apellidoPaterno"] = na["apellidoPaterno"]
    data["apellidoMaterno"] = na["apellidoMaterno"]
    data["nombre"] = na["nombre"]
    if na["_sexo"]:
        data["sexo"] = na["_sexo"]

    for k, v in extract_domicilio(frente_lines).items():
        if v:
            data[k] = v

    for k, v in extract_campos_finales(frente_lines).items():
        if v and not data.get(k):
            data[k] = v

    if not data["fechaNacimiento"] and mrz["fechaNacimiento"]:
        data["fechaNacimiento"] = mrz["fechaNacimiento"]
    if not data["vigencia"] and mrz["vigencia"]:
        data["vigencia"] = mrz["vigencia"]
    if not data["seccion"] and mrz["seccion"]:
        data["seccion"] = mrz["seccion"]
    if mrz["apellidos"] and (
        not data["apellidoPaterno"] or not data["apellidoMaterno"]
    ):
        partes = mrz["apellidos"].split()
        if len(partes) >= 2:
            data["apellidoPaterno"] = data["apellidoPaterno"] or partes[0]
            data["apellidoMaterno"] = data["apellidoMaterno"] or partes[1]

    if data["curp"]:
        cd = _datos_desde_curp(data["curp"])
        data["sexo"] = data["sexo"] or cd["sexo"]
        data["fechaNacimiento"] = data["fechaNacimiento"] or cd["fechaNacimiento"]
        if not data["estado"]:
            data["estado"] = cd["estado"]

    return data


# --------------------------------------------------------------------------- #
# Test (layout OCR con posible desorden)
# --------------------------------------------------------------------------- #
_TEXTO_FRENTE_V3 = """
NOMBRE
LOPEZ
GARCIA
MARIA GUADALUPE
DOMICILIO
AV REFORMA 123
CENTRO 06600
CUAUHTEMOC, CDMX
CURP GALG850101MDFRPD09
CLAVE DE ELECTOR GRCLPR85010109H200
01/01/1985
0901
2022-2032
"""

_TEXTO_REVERSO_V3 = """
IDMEX1234567890<<0901<<<<<<<<
8501014M2901019MEX<<<<<<<<<<<4
GARCIA<<LOPEZ<<MARIA<GUADALUPE
"""


def _test_parser_v3() -> None:
    datos = parse_ine(_TEXTO_FRENTE_V3, _TEXTO_REVERSO_V3)
    campos = [
        "nombre", "apellidoPaterno", "apellidoMaterno", "curp", "claveElector",
        "fechaNacimiento", "sexo", "domicilio", "colonia", "codigoPostal",
        "municipio", "estado", "seccion", "vigencia",
    ]
    print("=== Test INE parser v3 ===")
    fallos = []
    for c in campos:
        v = datos.get(c)
        ok = "OK" if v is not None else "FALTA"
        print(f"  {c:20s}: {str(v)[:40]:40s}  {ok}")
        if v is None:
            fallos.append(c)
    if fallos:
        raise AssertionError(f"Campos sin extraer: {fallos}")
    # v3: apellidos asignados por iniciales CURP (G=Garcia paterno, L=Lopez materno)
    assert datos["apellidoPaterno"] == "GARCIA", datos["apellidoPaterno"]
    assert datos["apellidoMaterno"] == "LOPEZ", datos["apellidoMaterno"]
    print("OK — 14/14 campos (asignacion por CURP verificada).")


if __name__ == "__main__":
    _test_parser_v3()
