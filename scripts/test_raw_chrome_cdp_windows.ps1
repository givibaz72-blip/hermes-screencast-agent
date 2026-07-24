<#
.SYNOPSIS
    Smoke-test raw Chrome CDP startup on Windows.

.DESCRIPTION
    Uses the production RawChromeCdpProcess to start Chrome with raw CDP,
    validates DevToolsActivePort detection, and verifies Playwright CDP
    connectivity. Never launches HeyGen, FFmpeg, or recording.

    Chrome search order:
    1.  Explicit -ChromePath parameter
    2.  $env:CHROME_PATH
    3.  Program Files\Google\Chrome\Application\chrome.exe
    4.  Program Files (x86)\Google\Chrome\Application\chrome.exe
    5.  %LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

.PARAMETER ChromePath
    Explicit path to chrome.exe.

.PARAMETER ProfileDir
    Chrome persistent profile directory. Defaults to:
    $env:LOCALAPPDATA\Hermes\Profiles\raw-cdp-smoke

.PARAMETER TimeoutSeconds
    Seconds to wait for DevToolsActivePort (default: 30).

.EXAMPLE
    .\scripts\test_raw_chrome_cdp_windows.ps1 -ChromePath "C:\Chrome\chrome.exe"
#>

[CmdletBinding()]
param(
    [string]$ChromePath,
    [string]$ProfileDir,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

# --- Resolve paths ---
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SmokeScript = Join-Path $ProjectRoot "scripts\demo_raw_chrome_cdp.py"

# --- Default profile dir ---
if (-not $ProfileDir) {
    $ProfileDir = Join-Path $env:LOCALAPPDATA "Hermes\Profiles\raw-cdp-smoke"
}

# --- Chrome detection ---
if (-not $ChromePath) {
    $ChromePath = $env:CHROME_PATH
}
if (-not $ChromePath -or -not (Test-Path -LiteralPath $ChromePath)) {
    $candidates = @(
        "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
    )
    if ($env:LOCALAPPDATA) {
        $candidates += "${env:LOCALAPPDATA}\Google\Chrome\Application\chrome.exe"
    }
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            $ChromePath = $c
            break
        }
    }
}

if (-not $ChromePath -or -not (Test-Path -LiteralPath $ChromePath)) {
    Write-Error "Chrome not found. Specify -ChromePath or install Chrome."
    exit 1
}

# --- Build argv array (safe, no string injection) ---
$PythonArgs = @(
    $SmokeScript,
    "--chrome-path", $ChromePath,
    "--profile-dir", $ProfileDir,
    "--timeout", $TimeoutSeconds
)

# --- Run smoke test ---
try {
    & $Python @PythonArgs
    $PythonExitCode = $LASTEXITCODE
} catch {
    Write-Error "Failed to execute smoke test: $_"
    exit 1
}

exit $PythonExitCode