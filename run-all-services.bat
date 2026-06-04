@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "FRONTEND_DIR=%PROJECT_ROOT%app-front"
set "PYTHON_EXE=python"

if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
)

echo [BRASA] Iniciando servicos...

if not exist "%FRONTEND_DIR%\package.json" (
  echo [ERRO] Pasta do frontend nao encontrada em: %FRONTEND_DIR%
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERRO] npm nao encontrado no PATH.
  exit /b 1
)

if "%PYTHON_EXE%"=="python" (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    exit /b 1
  )
)

start "BRASA Backend API" /D "%PROJECT_ROOT%" "%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
start "BRASA Frontend Vite" /D "%FRONTEND_DIR%" cmd /k "npm run dev"

echo [OK] Servicos iniciados.
echo [URL] Backend:  http://127.0.0.1:8000/health
echo [URL] Frontend: http://127.0.0.1:5173

exit /b 0
