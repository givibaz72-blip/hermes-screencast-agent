<#
.SYNOPSIS
    Run Hermes Windows E2E HeyGen Review - same-machine Windows workflow without relay/domain/TLS

.DESCRIPTION
    This script launches the Hermes screencast agent in Windows E2E mode for recording
    HeyGen reviews on a single Windows machine. No public WSS, no relay, no domain, no DNS,
    no reverse proxy required. The user manually performs login/CAPTCHA/2FA in a local
    Chrome window, and recording starts only after confirmed dashboard authentication.

.PARAMETER InspectOnly
    Run in inspect-only mode (default). Opens Chrome, allows manual login, shows page state.
    Does not record video.

.PARAMETER Record
    Enable recording mode. Requires - will start recording after confirmed authentication.

.PARAMETER SuccessSelector
    CSS selector for authenticated dashboard element (required for --Record).

.PARAMETER RecordSeconds
    Recording duration in seconds (default: 10).

.PARAMETER OutputName
    Output filename for recording (default: heygen-review-demo.mp4).

.PARAMETER ProfileDir
    Chrome persistent profile directory (default: $env:LOCALAPPDATA\Hermes\Profiles\heygen-review).

.PARAMETER RecordingDir
    Recording output directory (default: $env:USERPROFILE\Videos\Hermes).

.PARAMETER TargetUrl
    Target URL to open (default: https://app.heygen.com/).

.PARAMETER Profile
    Profile name for session (default: heygen-review).

.PARAMETER ChromePath
    Explicit path to Chrome executable (auto-detected if not provided).

.PARAMETER ConnectTimeout
    Connection timeout in seconds (default: 30).

.PARAMETER HermesDebug
    Enable debug output (maps to Python --debug).

.PARAMETER DryRun
    Show what would be done without starting Chrome, companion, or FFmpeg.

.EXAMPLE
    # Inspect-only mode - manual login, view page state
    .\scripts\run_heygen_windows_e2e.ps1 -InspectOnly

.EXAMPLE
    # Record mode - requires confirmed selector
    .\scripts\run_heygen_windows_e2e.ps1 `
      -Record `
      -SuccessSelector "[data-testid='dashboard']" `
      -RecordSeconds 10 `
      -OutputName "heygen-review-demo.mp4"

.EXAMPLE
    # Custom profile and recording directories
    .\scripts\run_heygen_windows_e2e.ps1 -InspectOnly `
      -ProfileDir "C:\Hermes\Profiles\heygen-review" `
      -RecordingDir "C:\Videos\Hermes"

.EXAMPLE
    # Dry run to verify setup
    .\scripts\run_heygen_windows_e2e.ps1 -InspectOnly -DryRun

.EXAMPLE
    # Debug mode
    .\scripts\run_heygen_windows_e2e.ps1 -InspectOnly -HermesDebug
#>

[CmdletBinding(DefaultParameterSetName="InspectOnly")]
param(
    [Parameter(ParameterSetName="InspectOnly", Mandatory=$true)]
    [Parameter(ParameterSetName="Record", Mandatory=$true)]
    [switch]$InspectOnly,

    [Parameter(ParameterSetName="Record", Mandatory=$true)]
    [switch]$Record,

    [Parameter(ParameterSetName="Record", Mandatory=$true)]
    [string]$SuccessSelector,

    [Parameter(ParameterSetName="Record")]
    [int]$RecordSeconds = 10,

    [Parameter(ParameterSetName="Record")]
    [string]$OutputName = "heygen-review-demo.mp4",

    [string]$ProfileDir = "$env:LOCALAPPDATA\Hermes\Profiles\heygen-review",

    [string]$RecordingDir = "$env:USERPROFILE\Videos\Hermes",

    [string]$TargetUrl = "https://app.heygen.com/",

    [string]$Profile = "heygen-review",

    [string]$ChromePath,

    [int]$ConnectTimeout = 30,

    [switch]$HermesDebug,

    [switch]$DryRun,

    [ValidateSet("playwright","raw-cdp")]
    [string]$BrowserStartup = "playwright",

    [int]$AuthWaitSeconds = 300
)

# Set strict mode
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Find project root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = Split-Path -Parent $scriptDir

# Find Python in .venv
$Python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python"
    Write-Error "Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# Check Chrome
if ($ChromePath) {
    if (-not (Test-Path $ChromePath)) {
        Write-Error "Chrome not found at specified path: $ChromePath"
        exit 1
    }
} else {
    # Auto-detect Chrome
    $chromePaths = @(
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "$env:PROGRAMFILES\Google\Chrome\Application\chrome.exe",
        "${env:PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe"
    )
    $found = $false
    foreach ($path in $chromePaths) {
        if (Test-Path $path) {
            $ChromePath = $path
            $found = $true
            break
        }
    }
    if (-not $found) {
        Write-Error "chrome_not_found: Chrome not found in standard locations"
        Write-Error "  Checked: $env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
        Write-Error "  Checked: $env:PROGRAMFILES\Google\Chrome\Application\chrome.exe"
        Write-Error "  Checked: ${env:PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe"
        Write-Error "  Use -ChromePath to specify explicitly"
        exit 1
    }
}

Write-Host "Using Chrome: $ChromePath"

# Check FFmpeg and ffprobe
foreach ($tool in @("ffmpeg", "ffprobe")) {
    try {
        $result = & $tool -version 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "$tool not working (exit code $LASTEXITCODE)"
            exit 1
        }
    } catch {
        Write-Error "$tool not found in PATH"
        exit 1
    }
}
Write-Host "FFmpeg and ffprobe: OK"

# Create directories
try {
    New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null
    New-Item -ItemType Directory -Path $RecordingDir -Force | Out-Null
} catch {
    Write-Error "Failed to create directories: $_"
    exit 1
}
Write-Host "Profile dir: $ProfileDir"
Write-Host "Recording dir: $RecordingDir"

# Build demo script path
$DemoScript = Join-Path $projectRoot "scripts\demo_local_transport.py"
if (-not (Test-Path $DemoScript)) {
    Write-Error "Demo script not found: $DemoScript"
    exit 1
}

# Build Python arguments array (DO NOT include executable in args)
$PythonArgs = @(
    $DemoScript
    "windows-e2e"
    "--profile-dir"
    $ProfileDir
    "--recording-dir"
    $RecordingDir
    "--target-url"
    $TargetUrl
    "--profile"
    $Profile
    "--chrome-path"
    $ChromePath
    "--connect-timeout"
    "$ConnectTimeout"
)

if ($InspectOnly) {
    $PythonArgs += "--inspect-only"
}

if ($Record) {
    $PythonArgs += @(
        "--record"
        "--record-seconds"
        "$RecordSeconds"
        "--output-name"
        $OutputName
        "--success-selector"
        $SuccessSelector
    )
}

if ($HermesDebug) {
    $PythonArgs += "--debug"
}

if ($DryRun) {
    $PythonArgs += "--dry-run"
}

if ($BrowserStartup -ne "playwright") {
    $PythonArgs += @(
        "--browser-startup"
        $BrowserStartup
    )
}

if ($AuthWaitSeconds -ne 300) {
    $PythonArgs += @(
        "--auth-wait-seconds"
        "$AuthWaitSeconds"
    )
}

# Log invocation details (safe logging - no secrets in current workflow)
Write-Host "Executing Python:"
Write-Host "  executable=$Python"
Write-Host "  mode=windows-e2e"
Write-Host "  inspect_only=$InspectOnly"
Write-Host "  record=$Record"
Write-Host "  dry_run=$DryRun"

# Invoke Python with array-based splatting
# PowerShell passes each array element as a separate argv entry
# Paths with spaces (e.g., "C:\Program Files (x86)\...") are preserved correctly
try {
    & $Python @PythonArgs
    $PythonExitCode = $LASTEXITCODE
} catch {
    throw "Hermes windows-e2e failed with exception: $_"
}

# Handle Python child process exit code
if ($PythonExitCode -ne 0) {
    throw "Hermes windows-e2e failed with exit code $PythonExitCode"
}

# Explicit success output
Write-Host "windows_e2e_status=completed"
Write-Host "windows_e2e_python_rc=0"

exit 0