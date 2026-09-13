@echo off
setlocal
cd /d "%~dp0"
set "VR_STUDIO_PYTHON=%CD%\.venv\Scripts\python.exe"

if exist "%VR_STUDIO_PYTHON%" (
  "%VR_STUDIO_PYTHON%" scripts\batch_decompile.py %*
  pause
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if errorlevel 1 (
  echo Python nao foi encontrado no sistema ou na pasta .venv.
  pause
  exit /b 1
)

py scripts\batch_decompile.py %*
pause
exit /b %ERRORLEVEL%
endlocal
