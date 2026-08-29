@echo off
setlocal
cd /d "%~dp0"
set "VR_STUDIO_PYTHON=%CD%\.venv\Scripts\python.exe"

rem Os executaveis de entry point da virtualenv guardam o caminho absoluto
rem usado na criacao do ambiente e quebram quando a pasta do projeto e movida.
rem Chamar o modulo pelo Python atual mantem este inicializador relocavel.
if exist "%VR_STUDIO_PYTHON%" (
  "%VR_STUDIO_PYTHON%" -m vrsoft_extractor.mary.frontend.app --project-dir "%CD%"
  exit /b
)

where py >nul 2>nul
if errorlevel 1 (
  echo Python nao foi encontrado. Crie a virtualenv em .venv antes de iniciar.
  pause
  exit /b 1
)

py -m vrsoft_extractor.mary.frontend.app --project-dir "%CD%"
exit /b %ERRORLEVEL%
endlocal
