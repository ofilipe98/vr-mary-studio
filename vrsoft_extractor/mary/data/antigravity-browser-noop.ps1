# Relay the URL without opening a browser or waiting for buffered runtime output.
# The Studio validates this URL and opens it from the Qt UI thread.
param([string]$AuthorizationUrl)
[Console]::Out.WriteLine('Open the following link to authenticate the ACP server: ' + $AuthorizationUrl)
[Console]::Error.WriteLine('Open the following link to authenticate the ACP server: ' + $AuthorizationUrl)
[Console]::Error.WriteLine('__T3_ANTIGRAVITY_AUTH_URL__"' + $AuthorizationUrl + '"')
[Console]::Out.Flush()
[Console]::Error.Flush()
exit 0
