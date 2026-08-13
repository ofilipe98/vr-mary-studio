@echo off
rem Gerado pelo VR Norte Studio - projeto Codex portatil
setlocal
cd /d "%~dp0"
where codex >nul 2>nul
if errorlevel 1 (
  echo Codex nao foi encontrado no PATH.
  echo Instale e autentique o Codex nesta maquina antes de abrir o projeto VR.
  pause
  exit /b 1
)
codex app "%CD%"
endlocal
