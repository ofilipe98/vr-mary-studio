# Relay the URL without waiting for buffered runtime output and launch browser.
# The Studio also validates this URL and manages the lifecycle from the Qt UI thread.
param([string]$AuthorizationUrl)
[Console]::Out.WriteLine('Open the following link to authenticate the ACP server: ' + $AuthorizationUrl)
[Console]::Error.WriteLine('Open the following link to authenticate the ACP server: ' + $AuthorizationUrl)
[Console]::Error.WriteLine('__T3_ANTIGRAVITY_AUTH_URL__"' + $AuthorizationUrl + '"')
[Console]::Out.Flush()
[Console]::Error.Flush()
if ($AuthorizationUrl -and ($AuthorizationUrl.StartsWith('https://accounts.google.com/') -or $AuthorizationUrl.StartsWith('http://') -or $AuthorizationUrl.StartsWith('https://'))) {
    try {
        Start-Process $AuthorizationUrl
    } catch {}
}
exit 0
