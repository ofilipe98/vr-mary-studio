$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Ambiente virtual nao encontrado: $Python"
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean VRMaryStudio.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller falhou com codigo $LASTEXITCODE"
    }

    $DistRoot = Join-Path $ProjectRoot "dist\VRMaryStudio"
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $DistRoot ".env.example") -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $DistRoot "README.md") -Force

    $ReleaseRoot = Join-Path $ProjectRoot "releases"
    New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
    $Archive = Join-Path $ReleaseRoot "VRMaryStudio-0.3.6-portable.zip"
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
    Compress-Archive -LiteralPath $DistRoot -DestinationPath $Archive
    Write-Output $Archive
}
finally {
    Pop-Location
}
