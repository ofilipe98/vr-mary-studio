param(
    [string]$MaryRoot = "",
    [switch]$SkipMaryProject,
    [ValidateSet("auto", "main", "dev")]
    [string]$BuildChannel = "auto",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($PythonPath) {
    $PythonPath
}
else {
    Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
$VersionFile = Join-Path $ProjectRoot "vrsoft_extractor\__init__.py"
$VersionMatch = [regex]::Match(
    (Get-Content -LiteralPath $VersionFile -Raw),
    '__version__\s*=\s*["'']([^"'']+)["'']'
)
if (-not $VersionMatch.Success) {
    throw "Versao do aplicativo nao encontrada em: $VersionFile"
}
$AppVersion = $VersionMatch.Groups[1].Value

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Ambiente virtual nao encontrado: $Python"
}

$CurrentBranch = (& git -C $ProjectRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $CurrentBranch) {
    throw "Nao foi possivel identificar a branch Git atual."
}
$ResolvedChannel = if ($BuildChannel -eq "auto") {
    $CurrentBranch
}
else {
    $BuildChannel
}
if ($ResolvedChannel -notin @("main", "dev")) {
    throw "Build oficial permitido somente nas branches main ou dev. Branch atual: $CurrentBranch"
}
if ($CurrentBranch -ne $ResolvedChannel) {
    throw "O canal $ResolvedChannel deve ser gerado a partir da branch de mesmo nome. Branch atual: $CurrentBranch"
}
$PendingChanges = @(& git -C $ProjectRoot status --porcelain --untracked-files=normal)
if ($LASTEXITCODE -ne 0) {
    throw "Nao foi possivel validar o estado do repositorio."
}
if ($PendingChanges.Count -gt 0) {
    throw "Build oficial exige uma arvore Git limpa. Commit ou descarte as alteracoes antes de empacotar."
}
$Revision = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Nao foi possivel identificar a revisao Git atual."
}
$ShortRevision = $Revision.Substring(0, 8)
$ArtifactLabel = if ($ResolvedChannel -eq "main") {
    "$ResolvedChannel-$AppVersion"
}
else {
    "$ResolvedChannel-$AppVersion-$ShortRevision"
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
    $BuildInfo = [ordered]@{
        product = "VR Mary Studio"
        version = $AppVersion
        channel = $ResolvedChannel
        branch = $CurrentBranch
        revision = $Revision
        built_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $BuildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $DistRoot "build-info.json") -Encoding UTF8

    $ReleaseRoot = Join-Path $ProjectRoot "releases"
    New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
    # A distribuição oficial é única: o portátil completo já contém o app.
    # Remova o artefato legado para não publicar duas variantes da mesma versão.
    foreach ($LegacyAppOnlyArchive in Get-ChildItem -LiteralPath $ReleaseRoot -Filter "VRMaryStudio-*-app-only.zip" -File) {
        Remove-Item -LiteralPath $LegacyAppOnlyArchive.FullName -Force
    }

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
        $BuildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PortableRoot "build-info.json") -Encoding UTF8

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

        $PortableArchive = Join-Path $ReleaseRoot "VRMaryPortable-$ArtifactLabel.zip"
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
