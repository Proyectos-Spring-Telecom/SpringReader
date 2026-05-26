"""
Derivador y validador de CURP — algoritmo RENAPO.

Referencia: Instructivo para el llenado de la CURP, SEGOB/RENAPO.
Caso canónico de validación: HEGG560427MVZRRL04
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Tablas de datos
# ---------------------------------------------------------------------------

ESTADO_CURP: dict[str, str] = {
    "AGUASCALIENTES": "AS",
    "BAJA CALIFORNIA": "BC",
    "BAJA CALIFORNIA SUR": "BS",
    "CAMPECHE": "CC",
    "CHIAPAS": "CS",
    "CHIHUAHUA": "CH",
    "CIUDAD DE MEXICO": "DF",
    "COAHUILA": "CL",
    "COLIMA": "CM",
    "DURANGO": "DG",
    "ESTADO DE MEXICO": "MC",
    "GUANAJUATO": "GT",
    "GUERRERO": "GR",
    "HIDALGO": "HG",
    "JALISCO": "JC",
    "MEXICO": "MC",  # alias
    "MICHOACAN": "MN",
    "MORELOS": "MS",
    "NAYARIT": "NT",
    "NUEVO LEON": "NL",
    "OAXACA": "OC",
    "PUEBLA": "PL",
    "QUERETARO": "QT",
    "QUINTANA ROO": "QR",
    "SAN LUIS POTOSI": "SP",
    "SINALOA": "SL",
    "SONORA": "SR",
    "TABASCO": "TC",
    "TAMAULIPAS": "TS",
    "TLAXCALA": "TL",
    "VERACRUZ": "VZ",
    "YUCATAN": "YN",
    "ZACATECAS": "ZS",
    "EXTRANJERO": "NE",
}

# Palabras altisonantes (lista RENAPO oficial, ~71 palabras)
PALABRAS_ALTISONANTES: frozenset[str] = frozenset(
    [
        "BACA", "BAKA", "BUEI", "BUEY", "CACA", "CACO", "CAGA", "CAGO",
        "CAKA", "CAKO", "COGE", "COGI", "COJA", "COJE", "COJI", "COJO",
        "COLA", "CULO", "FALO", "FETO", "GETA", "GUEI", "GUEY", "JETA",
        "JOTO", "KACA", "KACO", "KAGA", "KAGO", "KAKA", "KAKO", "KOGE",
        "KOGI", "KOJA", "KOJE", "KOJI", "KOJO", "KOLA", "KULO", "LELO",
        "LOCA", "LOCO", "LOKA", "LOKO", "MAME", "MAMO", "MEAR", "MEAS",
        "MEON", "MIAR", "MION", "MOCO", "MOKO", "MULA", "MULO", "NACA",
        "NACO", "PEDA", "PEDO", "PENE", "PIPI", "PITO", "POPO", "PUTA",
        "PUTO", "QULO", "RATA", "ROBA", "ROBE", "ROBO", "RUIN", "SENO",
        "TETA", "VACA", "VAGA", "VAGO", "VAKA", "VUEI", "VUEY", "WUEI",
        "WUEY",
    ]
)

# Tabla de caracteres para el dígito verificador
_TABLA_VERIFICADOR = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

MESES_ES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _normalizar(texto: str) -> str:
    """Uppercase, sin acentos (preserva Ñ), solo letras A-Z y Ñ."""
    texto = texto.upper().strip()
    resultado = []
    for c in unicodedata.normalize("NFD", texto):
        cat = unicodedata.category(c)
        if c == "Ñ" or (cat != "Mn" and c.isalpha()):
            resultado.append(c)
        elif c.isspace():
            resultado.append(" ")
    return "".join(resultado)


def _primera_vocal_interna(palabra: str) -> str:
    """Primera vocal interna (excluyendo la primera letra)."""
    for c in palabra[1:]:
        if c in "AEIOU":
            return c
    return "X"


def _consonantes_internas(palabra: str) -> list[str]:
    """Consonantes internas (excluyendo primera y última letra)."""
    consonantes = [
        c for c in palabra[1:-1]
        if c not in "AEIOUÑ" and c.isalpha()
    ]
    return consonantes


def parse_fecha(fecha: str) -> tuple[int, int, int]:
    """
    Parsea una fecha en formato dd/mm/yyyy, dd-mm-yyyy o "dd de MES de yyyy".
    Retorna (dia, mes, anio).
    """
    fecha = fecha.strip().upper()

    # dd/mm/yyyy o dd-mm-yyyy
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", fecha)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    # "dd de MES de yyyy"
    m = re.match(r"(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})", fecha)
    if m:
        mes_nombre = _normalizar(m.group(2))
        mes = MESES_ES.get(mes_nombre)
        if mes is None:
            raise ValueError(f"Mes desconocido: {m.group(2)}")
        return int(m.group(1)), mes, int(m.group(3))

    raise ValueError(f"Formato de fecha no reconocido: {fecha!r}")


# ---------------------------------------------------------------------------
# Cálculo del dígito verificador
# ---------------------------------------------------------------------------


def _calcular_digito_verificador(curp17: str) -> str:
    """
    Calcula el dígito verificador (posición 18) de los 17 primeros caracteres.
    Algoritmo RENAPO: suma(valor * (18 - posicion)) mod 10.
    Caso canónico: HEGG560427MVZRRL0 → 4
    """
    suma = 0
    for i, c in enumerate(curp17):
        valor = _TABLA_VERIFICADOR.index(c)
        suma += valor * (18 - i)
    return str(suma % 10)


# ---------------------------------------------------------------------------
# Derivación de CURP
# ---------------------------------------------------------------------------


def derivar_curp(
    nombre: str,
    apellido_paterno: str,
    apellido_materno: str,
    fecha_nacimiento: str,
    sexo: str,
    estado: str,
) -> str:
    """
    Deriva la CURP a partir de los datos personales.
    Nota: la homoclave (posiciones 16-17) no se puede derivar aritméticamente;
    se usa "A0" como placeholder. Para validación en producción se requiere
    consulta al servicio RENAPO.

    Returns CURP de 18 caracteres con dígito verificador calculado.
    """
    nombre = _normalizar(nombre)
    ap = _normalizar(apellido_paterno)
    am = _normalizar(apellido_materno)

    # --- Parte 1: 4 letras iniciales ---
    # Inicial + primera vocal interna del apellido paterno
    letra1 = ap[0] if ap else "X"
    letra2 = _primera_vocal_interna(ap) if len(ap) > 1 else "X"

    # Inicial del apellido materno
    letra3 = am[0] if am else "X"

    # Inicial del nombre (si empieza con JOSE/MARIA/MA/J, usar segundo nombre)
    tokens_nombre = nombre.split()
    nombre_para_inicial = tokens_nombre[0]
    if nombre_para_inicial in ("JOSE", "MARIA", "MA") or nombre_para_inicial == "J":
        nombre_para_inicial = tokens_nombre[1] if len(tokens_nombre) > 1 else tokens_nombre[0]
    letra4 = nombre_para_inicial[0] if nombre_para_inicial else "X"

    cuatro_letras = letra1 + letra2 + letra3 + letra4

    # Regla de palabras altisonantes
    if cuatro_letras in PALABRAS_ALTISONANTES:
        cuatro_letras = cuatro_letras[0] + "X" + cuatro_letras[2:]

    # --- Parte 2: fecha YYMMDD ---
    dia, mes, anio = parse_fecha(fecha_nacimiento)
    fecha_str = f"{anio % 100:02d}{mes:02d}{dia:02d}"

    # --- Parte 3: sexo ---
    sexo_upper = sexo.upper().strip()
    if sexo_upper in ("H", "M", "HOMBRE", "MUJER", "F", "FEMENINO", "MASCULINO"):
        sexo_letra = "H" if sexo_upper in ("H", "HOMBRE", "MASCULINO") else "M"
    else:
        sexo_letra = "H"

    # --- Parte 4: entidad federativa ---
    estado_norm = _normalizar(estado)
    codigo_estado = ESTADO_CURP.get(estado_norm, "NE")

    # --- Parte 5: 3 consonantes internas ---
    def tres_consonantes(s: str) -> str:
        cs = _consonantes_internas(s)
        resultado = ""
        for c in cs[:3]:
            resultado += c
        return resultado.ljust(3, "X")[:3]

    cons = tres_consonantes(ap) + tres_consonantes(am) + tres_consonantes(nombre_para_inicial)
    cons = cons[:3].ljust(3, "X")

    # --- Parte 6: homoclave (placeholder) ---
    homoclave = "A0"

    curp17 = cuatro_letras + fecha_str + sexo_letra + codigo_estado + cons + homoclave
    digito = _calcular_digito_verificador(curp17)

    return curp17 + digito


# ---------------------------------------------------------------------------
# Validación de CURP
# ---------------------------------------------------------------------------

_REGEX_CURP = re.compile(
    r"^[A-Z]{4}\d{6}[HM][A-Z]{2}[BCDFGHJKLMNÑPQRSTVWXYZ]{3}[0-9A-Z]\d$"
)


def validate_curp(curp: str) -> bool:
    """
    Valida la estructura y el dígito verificador de una CURP.
    Caso canónico RENAPO: validate_curp("HEGG560427MVZRRL04") == True
    """
    curp = curp.strip().upper()
    if not _REGEX_CURP.match(curp):
        return False

    esperado = _calcular_digito_verificador(curp[:17])
    return curp[17] == esperado


# ---------------------------------------------------------------------------
# Bloque de verificación
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    caso_canonico = "HEGG560427MVZRRL04"
    resultado = validate_curp(caso_canonico)
    print(f"validate_curp({caso_canonico!r}) = {resultado}")
    assert resultado is True, f"ERROR: caso canónico RENAPO debería ser True, obtuvo {resultado}"
    print("OK — dígito verificador correcto.")
