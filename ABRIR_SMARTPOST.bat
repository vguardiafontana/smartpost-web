@echo off
setlocal
cd /d "%~dp0"

if exist ".build-venv\Scripts\python.exe" (
    ".build-venv\Scripts\python.exe" desktop.py
    if errorlevel 1 (
        echo.
        echo SmartPost termino con un error. Presiona una tecla para cerrar.
        pause >nul
    )
    exit /b
)

where py >nul 2>nul
if %errorlevel%==0 (
    py desktop.py
    if errorlevel 1 pause
    exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
    python desktop.py
    if errorlevel 1 pause
    exit /b
)

echo No encontre Python ni .build-venv.
echo Ejecuta una vez packaging\build_windows.ps1 o crea el entorno virtual.
pause
