from pydantic import BaseModel, Field


class OcrLine(BaseModel):
    text: str
    confidence: float


class OcrRequest(BaseModel):
    image: str
    language: str = "es"


class OcrResponse(BaseModel):
    text: str
    confidence: float
    lines: list[OcrLine]


class BatchImageItem(BaseModel):
    id: str
    image: str


class BatchOcrRequest(BaseModel):
    images: list[BatchImageItem]
    language: str = "es"


class BatchOcrResultItem(BaseModel):
    id: str
    text: str = ""
    confidence: float = 0.0
    error: str | None = None


class BatchOcrResponse(BaseModel):
    results: list[BatchOcrResultItem]


class OcrSideResult(BaseModel):
    text: str
    confidence: float


class IneOcrResponse(BaseModel):
    frente: OcrSideResult
    reverso: OcrSideResult
    combined_text: str


class OcrConfidence(BaseModel):
    frente: float
    reverso: float


class IneExtractData(BaseModel):
    nombre: str | None = None
    apellidoPaterno: str | None = None
    apellidoMaterno: str | None = None
    curp: str | None = None
    claveElector: str | None = None
    fechaNacimiento: str | None = None
    sexo: str | None = None
    domicilio: str | None = None
    colonia: str | None = None
    codigoPostal: str | None = None
    municipio: str | None = None
    estado: str | None = None
    seccion: str | None = None
    vigencia: str | None = None


class IneExtractResponse(BaseModel):
    extraction_id: str
    data: IneExtractData
    ocr_confidence: OcrConfidence
    raw_text: str


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "SpringReader"
    model_loaded: bool = False
    seconds_since_last_use: float | None = None


# --- Constancia Fiscal SAT ---


class ActividadEconomica(BaseModel):
    orden: int
    descripcion: str
    porcentaje: int | None = None
    fechaInicio: str | None = None
    fechaFin: str | None = None


class RegimenFiscal(BaseModel):
    descripcion: str
    fechaInicio: str | None = None
    fechaFin: str | None = None


class ObligacionFiscal(BaseModel):
    descripcion: str
    vencimiento: str | None = None
    fechaInicio: str | None = None
    fechaFin: str | None = None


class ConstanciaFiscalData(BaseModel):
    tipoContribuyente: str | None = None
    rfc: str | None = None
    idCIF: str | None = None
    curp: str | None = None
    nombre: str | None = None
    apellidoPaterno: str | None = None
    apellidoMaterno: str | None = None
    razonSocial: str | None = None
    regimenCapital: str | None = None
    nombreComercial: str | None = None
    fechaInicioOperaciones: str | None = None
    estatusContribuyente: str | None = None
    fechaUltimoCambioEstado: str | None = None
    codigoPostal: str | None = None
    tipoVialidad: str | None = None
    nombreVialidad: str | None = None
    numeroExterior: str | None = None
    numeroInterior: str | None = None
    colonia: str | None = None
    localidad: str | None = None
    municipio: str | None = None
    entidadFederativa: str | None = None
    entreCalle: str | None = None
    yCalle: str | None = None
    actividadesEconomicas: list[ActividadEconomica] = []
    regimenesFiscales: list[RegimenFiscal] = []
    obligaciones: list[ObligacionFiscal] = []


class ConstanciaFiscalDataWrapper(BaseModel):
    constancia: ConstanciaFiscalData


class ConstanciaFiscalResponse(BaseModel):
    status: str = "success"
    message: str = "Constancia fiscal procesada correctamente"
    processingType: str
    pageCount: int
    data: ConstanciaFiscalDataWrapper
