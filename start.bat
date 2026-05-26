@echo off
REM ============================================================
REM  SpringReader — Arranque en desarrollo (Windows)
REM ============================================================

REM Crear entorno virtual si no existe
if not exist ".venv" (
    echo Creando entorno virtual...
    python -m venv .venv
)

REM Activar entorno virtual
call .venv\Scripts\activate.bat

REM Instalar dependencias
echo Instalando dependencias...
pip install -r requirements.txt

REM Copiar .env.example si no existe .env
if not exist ".env" (
    echo Copiando .env.example a .env...
    copy .env.example .env
)

REM Arrancar Uvicorn en modo reload para desarrollo
echo.
echo Iniciando SpringReader en http://localhost:8001
echo Docs: http://localhost:8001/docs
echo.
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
