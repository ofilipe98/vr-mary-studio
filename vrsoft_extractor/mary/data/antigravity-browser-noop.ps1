# Browser relay helper for VRStudio Antigravity ACP authentication.
# Writes authorization URL to stderr only to protect JSON-RPC stdout.
# Does NOT open secondary browser. Exits with code 0.
param([string]$AuthorizationUrl)
if ($AuthorizationUrl) {
    try {
        $encoded = ConvertTo-Json -InputObject $AuthorizationUrl -Compress
    } catch {
        $escaped = $AuthorizationUrl.Replace('\', '\\').Replace('"', '\"')
        $encoded = '"' + $escaped + '"'
    }
    [Console]::Error.WriteLine('__VRSTUDIO_ANTIGRAVITY_AUTH_URL__' + $encoded)
    [Console]::Error.Flush()
}
exit 0
