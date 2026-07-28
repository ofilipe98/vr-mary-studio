@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\vr-mary-studio.exe" (
  ".venv\Scripts\vr-mary-studio.exe" --project-dir "%CD%"
) else (
  py -m vrsoft_extractor.mary.ui --project-dir "%CD%"
)
endlocal
