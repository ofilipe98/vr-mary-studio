@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\vr-norte-studio.exe" (
  ".venv\Scripts\vr-norte-studio.exe" --project-dir "%CD%"
) else if exist ".venv\Scripts\vr-mary-studio.exe" (
  rem Compatibilidade com ambientes virtuais criados antes da nova identidade.
  ".venv\Scripts\vr-mary-studio.exe" --project-dir "%CD%"
) else (
  py -m vrsoft_extractor.mary.ui --project-dir "%CD%"
)
endlocal
