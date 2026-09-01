param(
    [Alias("MaryRoot")]
    [string]$VRRoot = "",
    [Alias("SkipMaryProject")]
    [switch]$SkipVRProject,
    [switch]$IncludeKnowledgeBase,
    [ValidateSet("auto", "main", "dev")]
    [string]$BuildChannel = "auto",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ResolvedVRRoot = if ($VRRoot) {
    (Resolve-Path -LiteralPath $VRRoot).Path
}
else {
    Join-Path $ProjectRoot "VRProject"
}
if (-not (Test-Path -LiteralPath $ResolvedVRRoot -PathType Container)) {
    throw "VRProject usado na build não foi encontrado: $ResolvedVRRoot"
}
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
if (-not [Environment]::Is64BitProcess) {
    throw "A distribuicao oficial deve ser gerada com Python 64 bits."
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
    & $Python -m PyInstaller --noconfirm --clean VRNorteStudio.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller falhou com codigo $LASTEXITCODE"
    }

    $DistRoot = Join-Path $ProjectRoot "dist\VRNorteStudio"
    $Executable = Join-Path $DistRoot "VRNorteStudio.exe"
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Executavel nao encontrado apos o build: $Executable"
    }
    $BundledBrowser = Get-ChildItem -LiteralPath $DistRoot -Recurse -Filter "chrome.exe" -File |
        Where-Object { $_.FullName -like "*playwright*\.local-browsers*" } |
        Select-Object -First 1
    $BundledFfmpeg = Get-ChildItem -LiteralPath $DistRoot -Recurse -Filter "ffmpeg-win64.exe" -File |
        Where-Object { $_.FullName -like "*playwright*\.local-browsers*" } |
        Select-Object -First 1
    if (-not $BundledBrowser -or -not $BundledFfmpeg) {
        throw "A build nao incorporou Chromium e FFmpeg do Playwright. Execute 'python -m playwright install chromium' no ambiente de build."
    }
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $DistRoot ".env.example") -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $DistRoot "README.md") -Force
    $BuildInfo = [ordered]@{
        product = "VR Norte Studio"
        version = $AppVersion
        platform = "windows-x64"
        portable = $true
        python_included = $true
        chromium_included = $true
        ffmpeg_included = $true
        excluded_knowledge_sources = if ($IncludeKnowledgeBase) { @() } else { @("kb", "wiki") }
        excluded_local_data = @("ERP", "indice/codigo", "releases", ".state", "TrabalhoVR")
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

    if (-not $SkipVRProject) {
        $PortableRoot = Join-Path $ProjectRoot "dist\VRNortePortable"
        $PortableApp = Join-Path $PortableRoot "App"
        $PortableVR = Join-Path $PortableRoot "VRProject"
        if (Test-Path -LiteralPath $PortableRoot) {
            Remove-Item -LiteralPath $PortableRoot -Recurse -Force
        }
        New-Item -ItemType Directory -Path $PortableApp -Force | Out-Null
        Copy-Item -Path (Join-Path $DistRoot "*") -Destination $PortableApp -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "vrsoft_extractor\mary\data\Abrir-VR-Studio.cmd") -Destination $PortableRoot -Force
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "LEIA-ME-PORTATIL.txt") -Destination $PortableRoot -Force
        $BuildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PortableRoot "build-info.json") -Encoding UTF8

        $ExportArguments = @(
            "-m", "vrsoft_extractor.mary.cli",
            "--app-dir", $ProjectRoot
        )
        # A build nunca deve herdar o workspace persistido de outra instalação.
        $ExportArguments += @("--root", $ResolvedVRRoot)
        $ExportArguments += @("export-portable")
        if (-not $IncludeKnowledgeBase) {
            $ExportArguments += @(
                "--exclude-source", "kb",
                "--exclude-source", "wiki"
            )
        }
        $ExportArguments += @($PortableVR)
        & $Python @ExportArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Exportacao do projeto VR falhou com codigo $LASTEXITCODE"
        }

        $PortableCodeTools = Join-Path $PortableVR "tools\code-analysis"
        $PortableJava = Get-ChildItem -LiteralPath (Join-Path $PortableCodeTools "java17") -Recurse -Filter "java.exe" -File -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $PortableVineflower = Join-Path $PortableCodeTools "decompilers\vineflower-1.12.0.jar"
        $PortableCfr = Join-Path $PortableCodeTools "decompilers\cfr-0.152.jar"
        if (-not $PortableJava -or
            -not (Test-Path -LiteralPath $PortableVineflower -PathType Leaf) -or
            -not (Test-Path -LiteralPath $PortableCfr -PathType Leaf)) {
            throw "A build portátil não incorporou Java 17, Vineflower e CFR do VRProject selecionado: $ResolvedVRRoot"
        }

        $PortableArchive = Join-Path $ReleaseRoot "VRNortePortable-$ArtifactLabel.zip"
        if (Test-Path -LiteralPath $PortableArchive) {
            Remove-Item -LiteralPath $PortableArchive -Force
        }
        # Compress-Archive usa uma implementação .NET que falha perto de 4 GB.
        # zipfile habilita ZIP64 por padrão e preserva a pasta VRNortePortable.
        & $Python -m zipfile -c $PortableArchive $PortableRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Compactacao ZIP64 falhou com codigo $LASTEXITCODE"
        }
        $ArchiveHash = (Get-FileHash -LiteralPath $PortableArchive -Algorithm SHA256).Hash
        $ChecksumPath = Join-Path $ReleaseRoot "SHA256SUMS.txt"
        $ChecksumLine = "$ArchiveHash  $([IO.Path]::GetFileName($PortableArchive))"
        $ExistingChecksums = if (Test-Path -LiteralPath $ChecksumPath) {
            $ChecksumContent = Get-Content -LiteralPath $ChecksumPath -Raw
            @([regex]::Matches(
                $ChecksumContent,
                '(?i)[0-9a-f]{64}\s{2}\S+?\.zip'
            ) | ForEach-Object { $_.Value } | Where-Object {
                $_ -and $_ -notmatch "\s+$([regex]::Escape([IO.Path]::GetFileName($PortableArchive)))$"
            })
        }
        else {
            @()
        }
        @(@($ExistingChecksums) + @($ChecksumLine)) |
            Set-Content -LiteralPath $ChecksumPath -Encoding ASCII
        Write-Output $PortableArchive
        Write-Output "SHA256: $ArchiveHash"
    }
}
finally {
    Pop-Location
}
