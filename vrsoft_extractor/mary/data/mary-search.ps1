# Gerado pelo VR Mary Studio - projeto Codex portatil
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Query,

    [ValidateSet('', 'Fiscal', 'ADM_FIN_ESTOQUE', 'PDV', 'Multimodulo', 'Revisar')]
    [string]$Module = '',

    [ValidateSet('', 'wiki', 'kb')]
    [string]$Source = '',

    [ValidateRange(1, 20)]
    [int]$Limit = 8,

    [switch]$IncludeUnvalidated
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$CatalogPath = Join-Path $ProjectRoot 'indice\catalogo.jsonl'
$KnowledgeRoot = Join-Path $ProjectRoot 'conhecimento'

function Convert-ToSearchText([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $normalized = $Value.Normalize([Text.NormalizationForm]::FormD)
    $builder = New-Object Text.StringBuilder
    foreach ($character in $normalized.ToCharArray()) {
        $category = [Globalization.CharUnicodeInfo]::GetUnicodeCategory($character)
        if ($category -ne [Globalization.UnicodeCategory]::NonSpacingMark) {
            [void]$builder.Append([char]::ToLowerInvariant($character))
        }
    }
    return $builder.ToString().Normalize([Text.NormalizationForm]::FormC)
}

function Convert-ToRelativePath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $candidate = $Value.Replace('/', '\')
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        return $candidate.TrimStart('.','\').Replace('\', '/')
    }
    $rootPrefix = $ProjectRoot.TrimEnd('\') + '\'
    if ($candidate.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        return $candidate.Substring($rootPrefix.Length).Replace('\', '/')
    }
    foreach ($anchor in ('\conhecimento\', '\assets\', '\agentes\', '\videos\')) {
        $index = $candidate.IndexOf($anchor, [StringComparison]::OrdinalIgnoreCase)
        if ($index -ge 0) {
            return $candidate.Substring($index + 1).Replace('\', '/')
        }
    }
    return ''
}

function Get-MatchingFiles([string[]]$Terms) {
    $matches = @{}
    if (-not (Test-Path -LiteralPath $KnowledgeRoot)) { return $matches }
    $rg = Get-Command rg -ErrorAction SilentlyContinue
    foreach ($term in $Terms) {
        if ([string]::IsNullOrWhiteSpace($term)) { continue }
        if ($rg) {
            $paths = & $rg.Source -l -i --fixed-strings --glob '*.md' -- $term $KnowledgeRoot 2>$null
        } else {
            $paths = Get-ChildItem -LiteralPath $KnowledgeRoot -Recurse -Filter '*.md' -File |
                Select-String -SimpleMatch -Pattern $term -List |
                ForEach-Object { $_.Path }
        }
        foreach ($path in $paths) {
            $relative = Convert-ToRelativePath ([string]$path)
            if ($relative) { $matches[$relative.ToLowerInvariant()] = $true }
        }
    }
    return $matches
}

$queryText = Convert-ToSearchText $Query
$terms = @($queryText -split '[^\p{L}\p{N}_-]+' | Where-Object { $_.Length -ge 2 } | Select-Object -Unique)
$contentMatches = Get-MatchingFiles $terms
$items = New-Object Collections.Generic.List[object]

if (Test-Path -LiteralPath $CatalogPath) {
    foreach ($line in [IO.File]::ReadLines($CatalogPath)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $item = $line | ConvertFrom-Json } catch { continue }
        if ($item.status -and $item.status -ne 'active') { continue }
        if ($Module -and $item.module -ne $Module) { continue }
        if ($Source -and $item.source -ne $Source) { continue }
        if (-not $IncludeUnvalidated) {
            if ($item.module -eq 'Revisar') { continue }
            if ($item.review_status -and $item.review_status -notin @('approved', 'kept')) { continue }
        }

        $relative = Convert-ToRelativePath ([string]$item.local_path)
        if (-not $relative -and $item.relative_path) {
            $relative = Convert-ToRelativePath ([string]$item.relative_path)
        }
        if (-not $relative) { continue }

        $title = Convert-ToSearchText ([string]$item.title)
        $metadata = Convert-ToSearchText ((@($item.product, $item.category, $item.module, $item.source) -join ' '))
        $score = 0
        if ($title.Contains($queryText)) { $score += 120 }
        if ($metadata.Contains($queryText)) { $score += 60 }
        foreach ($term in $terms) {
            if ($title.Contains($term)) { $score += 24 }
            if ($metadata.Contains($term)) { $score += 10 }
        }
        if ($contentMatches.ContainsKey($relative.ToLowerInvariant())) { $score += 35 }
        if ($score -le 0) { continue }

        $items.Add([pscustomobject]@{
            score = $score
            source = [string]$item.source
            source_id = [string]$item.source_id
            title = [string]$item.title
            module = [string]$item.module
            product = [string]$item.product
            category = [string]$item.category
            review_status = [string]$item.review_status
            status = [string]$item.status
            updated_at = [string]$item.updated_at
            url = [string]$item.url
            local_path = $relative
        })
    }
} else {
    foreach ($relativeKey in $contentMatches.Keys) {
        $relative = $relativeKey.Replace('\', '/')
        $items.Add([pscustomobject]@{
            score = 10
            source = ''
            source_id = ''
            title = [IO.Path]::GetFileNameWithoutExtension($relative)
            module = ''
            product = ''
            category = ''
            review_status = 'unknown'
            status = 'active'
            updated_at = ''
            url = ''
            local_path = $relative
        })
    }
}

$results = @($items | Sort-Object @{Expression='score';Descending=$true}, @{Expression='title';Descending=$false} | Select-Object -First $Limit)
[pscustomobject]@{
    query = $Query
    module = $Module
    source = $Source
    include_unvalidated = [bool]$IncludeUnvalidated
    total = $items.Count
    results = $results
} | ConvertTo-Json -Depth 6
