param(
    [string]$MaryRoot = "",
    [switch]$SkipMaryProject
)

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
    $Archive = Join-Path $ReleaseRoot "VRMaryStudio-0.3.7-app-only.zip"
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
    Compress-Archive -LiteralPath $DistRoot -DestinationPath $Archive
    Write-Output $Archive

    if (-not $SkipMaryProject) {
        $PortableRoot = Join-Path $ProjectRoot "dist\VRMaryPortable"
        $PortableApp = Join-Path $PortableRoot "App"
        $PortableMary = Join-Path $PortableRoot "MaryProject"
        if (Test-Path -LiteralPath $PortableRoot) {
            Remove-Item -LiteralPath $PortableRoot -Recurse -Force
        }
        New-Item -ItemType Directory -Path $PortableApp -Force | Out-Null
        Copy-Item -Path (Join-Path $DistRoot "*") -Destination $PortableApp -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "vrsoft_extractor\mary\data\Abrir-VR-Mary-Studio.cmd") -Destination $PortableRoot -Force

        $ExportArguments = @(
            "-m", "vrsoft_extractor.mary.cli",
            "--app-dir", $ProjectRoot
        )
        if ($MaryRoot) {
            $ExportArguments += @("--root", $MaryRoot)
        }
        $ExportArguments += @("export-portable", $PortableMary)
        & $Python @ExportArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Exportacao do projeto Mary falhou com codigo $LASTEXITCODE"
        }

        $PortableArchive = Join-Path $ReleaseRoot "VRMaryPortable-0.3.7.zip"
        if (Test-Path -LiteralPath $PortableArchive) {
            Remove-Item -LiteralPath $PortableArchive -Force
        }
        Compress-Archive -LiteralPath $PortableRoot -DestinationPath $PortableArchive
        Write-Output $PortableArchive
    }
}
finally {
    Pop-Location
}
