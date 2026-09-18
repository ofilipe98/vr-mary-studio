@echo off
setlocal
cd /d "%~dp0"
echo ===================================================
echo  Iniciando VR Studio em Modo Seguro (Sem GPU / Software)
echo ===================================================
set "VR_STUDIO_SOFTWARE_RENDERING=1"
set "QT_QUICK_BACKEND=software"

call "%~dp0Start-VRStudio.bat" %*
endlocal
