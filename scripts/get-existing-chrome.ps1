<#
.SYNOPSIS
    Find an already-running Chrome instance with remote debugging enabled and return its CDP WebSocket URL.

.DESCRIPTION
    Searches for Chrome processes with --remote-debugging-port, queries /json/version endpoint
    to find the WebSocket debugger URL for the first available tab.

.PARAMETER Port
    Port to check (default: 9222). Can also be a range like "9222-9229".

.PARAMETER Host
    Host to check (default: 127.0.0.1).

.PARAMETER TimeoutSec
    Timeout in seconds for HTTP requests (default: 5).

.OUTPUTS
    [pscustomobject] with properties:
    - WebSocketUrl: The CDP WebSocket URL (ws://127.0.0.1:9222/devtools/page/...)
    - HttpEndpoint: The HTTP CDP endpoint (http://127.0.0.1:9222)
    - Port: The port found
    - BrowserVersion: Chrome version string

.EXAMPLE
    .\scripts\get-existing-chrome.ps1
    # Returns WebSocket URL for Chrome on default port 9222

.EXAMPLE
    .\scripts\get-existing-chrome.ps1 -Port 9223
    # Check specific port

.EXAMPLE
    .\scripts\get-existing-chrome.ps1 -Port "9222-9229"
    # Scan port range
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string]$Port = "9222",

    [Parameter()]
    [string]$Host = "127.0.0.1",

    [Parameter()]
    [int]$TimeoutSec = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-PortRange {
    param(
        [string]$PortRange
    )
    $ports = @()
    
    if ($PortRange -match '^(\d+)-(\d+)$') {
        $start = [int]$matches[1]
        $end = [int]$matches[2]
        if ($start -gt $end) { throw "Invalid port range: $PortRange" }
        $ports = $start..$end
    } elseif ($PortRange -match '^\d+$') {
        $ports = @([int]$PortRange)
    } else {
        throw "Invalid port format: $PortRange (use N or N-M)"
    }
    return $ports
}

function Get-ChromeCdpInfo {
    param(
        [string]$Host,
        [int]$Port,
        [int]$TimeoutSec
    )
    
    $httpUrl = "http://$Host:$Port/json/version"
    try {
        $response = Invoke-RestMethod -Uri $httpUrl -Method Get -TimeoutSec $TimeoutSec -ErrorAction Stop
        
        # Response contains: { "Browser": "Chrome/120.0.6099.109", "Protocol-Version": "1.3", "User-Agent": "...", "V8-Version": "...", "WebKit-Version": "...", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/..." }
        if ($response -and $response.webSocketDebuggerUrl) {
            return @{
                WebSocketUrl = $response.webSocketDebuggerUrl
                HttpEndpoint = "http://$Host:$Port"
                Port = $Port
                BrowserVersion = $response.Browser
                ProtocolVersion = $response.'Protocol-Version'
                WebKitVersion = $response.'WebKit-Version'
            }
        }
    } catch {
        # Silently ignore - port not responding or not Chrome
    }
    return $null
}

function Get-ChromeTabs {
    param(
        [string]$Host,
        [int]$Port,
        [int]$TimeoutSec
    )
    
    $httpUrl = "http://$Host:$Port/json/list"
    try {
        $tabs = Invoke-RestMethod -Uri $httpUrl -Method Get -TimeoutSec $TimeoutSec -ErrorAction Stop
        # Filter for page-type targets (not iframes, workers, etc.)
        $pages = $tabs | Where-Object { $_.type -eq 'page' -and $_.webSocketDebuggerUrl }
        return $pages
    } catch {
        return @()
    }
}

# Main logic
$ports = Test-PortRange -PortRange $Port
$found = $false
$result = $null

Write-Host "Scanning for Chrome with remote debugging on $Host ports: $($ports -join ', ')" -ForegroundColor Cyan

foreach ($p in $ports) {
    Write-Host "  Checking port $p..." -NoNewline
    $info = Get-ChromeCdpInfo -Host $Host -Port $p -TimeoutSec $TimeoutSec
    if ($info) {
        Write-Host " FOUND" -ForegroundColor Green
        $found = $true
        
        # Get available tabs
        $tabs = Get-ChromeTabs -Host $Host -Port $p -TimeoutSec $TimeoutSec
        if ($tabs.Count -gt 0) {
            # Use first available tab's WebSocket URL
            $tabWsUrl = $tabs[0].webSocketDebuggerUrl
            $info.WebSocketUrl = $tabWsUrl
            Write-Host "  Using tab: $($tabs[0].title) ($($tabs[0].url))" -ForegroundColor Gray
        } else {
            Write-Host "  No page tabs found, using browser-level WebSocket" -ForegroundColor Yellow
        }
        
        $result = [pscustomobject]$info
        break
    } else {
        Write-Host " -" -ForegroundColor DarkGray
    }
}

if (-not $found) {
    Write-Error "No Chrome instance with remote debugging found on $Host:$Port"
    Write-Host ""
    Write-Host "To start Chrome with remote debugging:" -ForegroundColor Yellow
    Write-Host '  & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebugProfile"'
    Write-Host ""
    Write-Host "Or add to Chrome shortcut Target:" -ForegroundColor Yellow
    Write-Host '  --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebugProfile"'
    exit 1
}

# Output as JSON for easy parsing
$json = $result | ConvertTo-Json -Compress -Depth 5
Write-Host $json

# Also write to stdout for pipeline use
$json | Out-Default

exit 0