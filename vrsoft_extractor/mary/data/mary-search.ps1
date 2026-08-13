# Gerado pelo VR Norte Studio - projeto Codex portatil
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
$SearchStopwords = @{
    a=$true; ao=$true; aos=$true; as=$true; com=$true; como=$true; da=$true
    das=$true; de=$true; do=$true; dos=$true; e=$true; em=$true; eu=$true
    mas=$true; mary=$true; na=$true; nas=$true; no=$true; nos=$true; o=$true
    os=$true; para=$true; por=$true; qual=$true; que=$true; um=$true; uma=$true
}

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
    $plain = $builder.ToString().Normalize([Text.NormalizationForm]::FormC)
    return (($plain -replace '[^\p{L}\p{N}_-]+', ' ').Trim() -replace '\s+', ' ')
}

function Get-SearchTerms([string]$Value) {
    $withoutPrefix = $Value -replace '^\s*(?i:vr|mary)\s*:\s*', ''
    $normalized = Convert-ToSearchText $withoutPrefix
    $unique = New-Object Collections.Generic.List[string]
    foreach ($term in ($normalized -split '\s+')) {
        if ($term.Length -lt 2 -or $SearchStopwords.ContainsKey($term)) { continue }
        if (-not $unique.Contains($term)) { $unique.Add($term) }
        if ($unique.Count -ge 12) { break }
    }
    return @($unique)
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
        if ($rg) {
            $paths = & $rg.Source -l -i --fixed-strings --glob '*.md' -- $term $KnowledgeRoot 2>$null
        } else {
            $paths = Get-ChildItem -LiteralPath $KnowledgeRoot -Recurse -Filter '*.md' -File |
                Select-String -SimpleMatch -Pattern $term -List |
                ForEach-Object { $_.Path }
        }
        foreach ($path in $paths) {
            $relative = Convert-ToRelativePath ([string]$path)
            if (-not $relative) { continue }
            $key = $relative.ToLowerInvariant()
            if (-not $matches.ContainsKey($key)) {
                $matches[$key] = New-Object 'Collections.Generic.HashSet[string]'
            }
            [void]$matches[$key].Add($term)
        }
    }
    return $matches
}

function Get-InferredModule([string[]]$Terms) {
    $hints = @{
        PDV = @('caixa','cupom','ecf','funcao','operador','pdv','pinpad','sitef','tef','venda','vrcaixa')
        Fiscal = @('cfop','fiscal','icms','nfe','nfce','nota','sped','tributacao','xml')
        ADM_FIN_ESTOQUE = @('cadastro','contas','estoque','financeiro','fornecedor','produto','vradm','vrmaster')
    }
    $scores = @{}
    foreach ($name in $hints.Keys) {
        $scores[$name] = @($Terms | Where-Object { $_ -in $hints[$name] }).Count
    }
    $best = @($scores.GetEnumerator() | Sort-Object Value -Descending)
    if (-not $best -or $best[0].Value -le 0) { return '' }
    if ($best.Count -gt 1 -and $best[0].Value -eq $best[1].Value) { return '' }
    return [string]$best[0].Key
}

function Get-Excerpt([string]$Content, [string[]]$Terms, [int]$Length = 360) {
    if ([string]::IsNullOrWhiteSpace($Content)) { return '' }
    $text = $Content -replace '(?s)\A---\s*.*?\s*---\s*', ''
    $text = $text -replace '!\[[^\]]*\]\([^\)]*\)', ' '
    $text = $text -replace '\[([^\]]+)\]\([^\)]*\)', '$1'
    $text = (($text -replace '[`#>*_|]+', ' ') -replace '\s+', ' ').Trim()
    if ($text.Length -le $Length) { return $text }
    $normalized = Convert-ToSearchText $text
    $positions = @($Terms | ForEach-Object { $normalized.IndexOf($_) } | Where-Object { $_ -ge 0 })
    $center = if ($positions) { ($positions | Measure-Object -Minimum).Minimum } else { 0 }
    $start = [Math]::Max(0, [int]$center - 90)
    $take = [Math]::Min($Length, $text.Length - $start)
    return ('{0}{1}{2}' -f $(if ($start) { '… ' } else { '' }), $text.Substring($start, $take).Trim(), $(if ($start + $take -lt $text.Length) { ' …' } else { '' }))
}

$terms = @(Get-SearchTerms $Query)
$minimumMatches = [Math]::Max(1, [Math]::Ceiling($terms.Count * 0.60))
$queryPhrase = $terms -join ' '
$inferredModule = Get-InferredModule $terms
$contentMatches = Get-MatchingFiles $terms
$items = New-Object Collections.Generic.List[object]

if ($terms.Count -gt 0 -and (Test-Path -LiteralPath $CatalogPath)) {
    foreach ($line in [IO.File]::ReadLines($CatalogPath)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try { $item = $line | ConvertFrom-Json } catch { continue }
        if ($item.status -and $item.status -ne 'active') { continue }
        if ($Module -and $item.module -ne $Module) { continue }
        if ($Source -and $item.source -ne $Source) { continue }
        if (-not $IncludeUnvalidated) {
            if ($item.module -eq 'Revisar') { continue }
            if ($item.review_status -notin @('approved', 'kept')) { continue }
        }

        $relative = Convert-ToRelativePath ([string]$item.local_path)
        if (-not $relative -and $item.relative_path) {
            $relative = Convert-ToRelativePath ([string]$item.relative_path)
        }
        if (-not $relative) { continue }

        $title = Convert-ToSearchText ([string]$item.title)
        $metadata = Convert-ToSearchText ((@($item.product, $item.category, $item.module, $item.source) -join ' '))
        $titleTerms = @($terms | Where-Object { $title.Contains($_) })
        $matchedSet = New-Object 'Collections.Generic.HashSet[string]'
        foreach ($term in $terms) {
            if ($title.Contains($term) -or $metadata.Contains($term)) { [void]$matchedSet.Add($term) }
        }
        $relativeKey = $relative.ToLowerInvariant()
        if ($contentMatches.ContainsKey($relativeKey)) {
            foreach ($term in $contentMatches[$relativeKey]) { [void]$matchedSet.Add($term) }
        }
        if ($matchedSet.Count -lt $minimumMatches) { continue }

        $path = Join-Path $ProjectRoot ($relative.Replace('/', '\'))
        $content = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) } else { '' }
        $normalizedContent = Convert-ToSearchText $content
        $coverage = $matchedSet.Count / [double]$terms.Count
        $titleCoverage = $titleTerms.Count / [double]$terms.Count
        $score = ($coverage * 400.0) + ($titleCoverage * 220.0)
        if ($queryPhrase -and $title.Contains($queryPhrase)) { $score += 220.0 }
        if ($queryPhrase -and $normalizedContent.Contains($queryPhrase)) { $score += 120.0 }
        if ($inferredModule -and $item.module -eq $inferredModule) { $score += 180.0 }
        $occurrences = 0
        foreach ($term in $terms) {
            $occurrences += [regex]::Matches($normalizedContent, [regex]::Escape($term)).Count
        }
        $score += [Math]::Min(36, $occurrences * 3)
        if ($content.Length -gt 150000 -and $titleTerms.Count -eq 0) { $score -= 30 }

        $items.Add([pscustomobject]@{
            score = [Math]::Round($score, 3)
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
            excerpt = Get-Excerpt $content $terms
            matched_terms = @($matchedSet)
            coverage = [Math]::Round($coverage, 4)
            confidence = [Math]::Round([Math]::Min(0.97, 0.40 + ($coverage * 0.42) + ($titleCoverage * 0.12)), 3)
            resolved_from = ''
            _content = $content
            _normalized_title = $title
        })
    }
}

$orderedForLinks = @($items | Sort-Object @{Expression='score';Descending=$true}, @{Expression='title';Descending=$false} | Select-Object -First 30)
foreach ($referring in $orderedForLinks) {
    foreach ($match in [regex]::Matches($referring._content, '\[([^\]]+)\]\((https?://[^\s\)]+)(?:\s+[^\)]*)?\)', 'IgnoreCase')) {
        $label = Convert-ToSearchText $match.Groups[1].Value
        $labelMatches = @($terms | Where-Object { $label.Contains($_) })
        if ($labelMatches.Count -ne $terms.Count) { continue }
        $url = $match.Groups[2].Value
        $targetTitle = ''
        if ($url -match '[?&]title=([^&#]+)') {
            $targetTitle = [Uri]::UnescapeDataString($Matches[1]).Replace('_', ' ')
        } elseif ($match.Groups[1].Value -match '(?i)(fun[cç][aã]o\s+\d+)') {
            $targetTitle = $Matches[1]
        }
        $targetKey = Convert-ToSearchText $targetTitle
        $target = @($items | Where-Object { $_._normalized_title -eq $targetKey } | Select-Object -First 1)
        if (-not $target -or $target[0] -eq $referring) { continue }
        $target = $target[0]
        $target.score = [Math]::Round([Math]::Max([double]$target.score, [double]$referring.score + 300.0), 3)
        $target.matched_terms = @($terms)
        $target.coverage = 1.0
        $target.confidence = [Math]::Max([double]$target.confidence, 0.98)
        $target.resolved_from = [string]$referring.title
    }
}

$results = @(
    $items |
        Sort-Object @{Expression='score';Descending=$true}, @{Expression='title';Descending=$false} |
        Select-Object -First $Limit |
        Select-Object score,source,source_id,title,module,product,category,review_status,status,updated_at,url,local_path,excerpt,matched_terms,coverage,confidence,resolved_from
)
$ambiguous = $false
if ($results.Count -ge 2 -and [double]$results[0].score -gt 0) {
    $ambiguous = (([double]$results[0].score - [double]$results[1].score) / [double]$results[0].score) -lt 0.10
}
[pscustomobject]@{
    query = $Query
    normalized_query = (Convert-ToSearchText (($terms -join ' ')))
    terms = $terms
    inferred_module = $inferredModule
    module = $Module
    source = $Source
    include_unvalidated = [bool]$IncludeUnvalidated
    ambiguous = $ambiguous
    total = $items.Count
    results = $results
} | ConvertTo-Json -Depth 7
