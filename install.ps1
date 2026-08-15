<#
.SYNOPSIS
    Install LiveWhisper - hotkey meeting transcription for Windows.

.DESCRIPTION
    Creates an isolated virtualenv, installs dependencies, detects your GPU and
    configures the best local model for it, optionally stores a Groq API key and
    pre-downloads the local model, then creates Start Menu and Desktop shortcuts.

    No admin rights needed. Everything lives under -InstallDir.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -InstallDir "E:\Apps\LiveWhisper" -GroqKey "gsk_..." -Startup
.EXAMPLE
    .\install.ps1 -Unattended        # accept every default, prompt for nothing
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\LiveWhisper",
    [string]$GroqKey = "",
    [switch]$DownloadModel,
    [switch]$SkipModel,
    [switch]$Startup,
    [switch]$Unattended,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path

function Say([string]$m, [string]$c = "Gray") { Write-Host $m -ForegroundColor $c }
function Step([string]$m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Warn([string]$m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die([string]$m) { Write-Host ""; Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

function Ask([string]$question, [string]$default = "") {
    if ($Unattended) { return $default }
    $suffix = if ($default) { " [$default]" } else { "" }
    $answer = Read-Host "  $question$suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim()
}

function AskYesNo([string]$question, [bool]$default = $true) {
    if ($Unattended) { return $default }
    $hint = if ($default) { "Y/n" } else { "y/N" }
    $answer = Read-Host "  $question ($hint)"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim().ToLower().StartsWith("y")
}

Write-Host ""
Write-Host "  LiveWhisper" -ForegroundColor Yellow
Write-Host "  Hotkey meeting transcription for Windows" -ForegroundColor DarkGray
Write-Host "  ----------------------------------------" -ForegroundColor DarkGray

# --------------------------------------------------------------------- python
Step "Checking Python"

$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try { $v = & $candidate -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null } catch { continue }
    if ($LASTEXITCODE -ne 0 -or -not $v) { continue }
    $parts = $v.Trim().Split('.')
    if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) { $python = $candidate; $pyver = $v.Trim(); break }
}

if (-not $python) {
    Say ""
    Die @"
Python 3.10 or newer is required and was not found on PATH.

Install it with:
    winget install Python.Python.3.12

then re-run this script. During a manual install from python.org, tick
'Add python.exe to PATH'.
"@
}
Say "  Python $pyver ($((Get-Command $python).Source))" "Green"

# ------------------------------------------------------------------- hardware
Step "Detecting hardware"

$hwJson = & $python -c @"
import sys, json
sys.path.insert(0, r'$Source')
from livewhisper import hardware
print(json.dumps(hardware.summary()))
"@ 2>$null

if ($LASTEXITCODE -ne 0 -or -not $hwJson) {
    Warn "Hardware detection failed; will use the defaults in config.yaml."
    $hw = $null
} else {
    $hw = $hwJson | ConvertFrom-Json
    $rec = $hw.recommended
    Say "  GPU   $($hw.gpu_label)" "Green"
    Say "  VRAM  $($hw.vram_gb) GB"
    Say "  RAM   $($hw.ram_gb) GB    CPU  $($hw.machine.cpus) cores"
    Say ""
    Say "  Recommended local model" "Yellow"
    Say "    $($rec.model)  -  $($rec.compute_type)  -  batch $($rec.batch_size)"
    Say "    $($rec.reason)" "DarkGray"
    Say "    Expect $($rec.speed)." "DarkGray"
}

# ----------------------------------------------------------------- target dir
Step "Install location"

if (-not $Unattended) { $InstallDir = Ask "Install to" $InstallDir }
Say "  $InstallDir"

if (Test-Path $InstallDir) {
    $existing = Join-Path $InstallDir "livewhisper"
    if (Test-Path $existing) {
        if (-not (AskYesNo "Existing install found. Upgrade in place (keeps config.yaml and .env)?" $true)) {
            Die "Cancelled."
        }
        $upgrade = $true
    }
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# ---------------------------------------------------------------- copy source
Step "Copying application files"

$items = @("livewhisper", "assets", "run.py", "requirements.txt", "check_setup.py",
           "README.md", "LICENSE", "start.bat", "uninstall.ps1", ".env.example")
foreach ($item in $items) {
    $src = Join-Path $Source $item
    if (-not (Test-Path $src)) { continue }
    Copy-Item $src -Destination $InstallDir -Recurse -Force
}
# Never clobber a user's settings or secrets on upgrade.
foreach ($keep in @("config.yaml", ".env")) {
    $dst = Join-Path $InstallDir $keep
    if (-not (Test-Path $dst)) {
        $src = Join-Path $Source $keep
        if ($keep -eq ".env") { $src = Join-Path $Source ".env.example" }
        if (Test-Path $src) { Copy-Item $src -Destination $dst -Force }
    } else {
        Say "  keeping your existing $keep" "DarkGray"
    }
}
Say "  Copied to $InstallDir" "Green"

# ----------------------------------------------------------------------- venv
Step "Creating virtual environment"

$venv = Join-Path $InstallDir ".venv"
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Die "Could not create the virtualenv at $venv" }
}
Say "  $venv" "Green"

Step "Installing dependencies (this pulls ~1.5 GB of CUDA runtime, give it a few minutes)"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r (Join-Path $InstallDir "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { Die "Dependency installation failed. Re-run with -Verbose to see pip's output." }
Say "  Dependencies installed" "Green"

# --------------------------------------------------------------------- config
Step "Configuring"

Push-Location $InstallDir
try {
    if ($hw) {
        & $vpy -m livewhisper.bootstrap apply-recommended
    }
    & $vpy -m livewhisper.bootstrap make-icon | Out-Null

    # --- Groq key ---
    if (-not $GroqKey -and -not $Unattended) {
        Say ""
        Say "  Groq gives you cloud transcription that is roughly 2.5x faster than" "DarkGray"
        Say "  local, at about `$0.04/hour with a free tier. LiveWhisper uses it" "DarkGray"
        Say "  first and falls back to the local model automatically when it runs" "DarkGray"
        Say "  out or is unreachable. Leave blank to run fully local." "DarkGray"
        Say "  Get a free key at https://console.groq.com" "DarkGray"
        $GroqKey = Ask "Groq API key (optional)" ""
    }
    if ($GroqKey) {
        & $vpy -m livewhisper.bootstrap set-key $GroqKey
    } else {
        Say "  No Groq key. Defaulting to the local engine." "DarkGray"
        & $vpy -c @"
from livewhisper import config as c
from pathlib import Path
cfg = c.load('config.yaml'); cfg['transcription']['backend'] = 'local'; c.save('config.yaml', cfg)
print('  backend set to local')
"@
    }

    # --- local model ---
    $want = $false
    if ($DownloadModel) { $want = $true }
    elseif ($SkipModel) { $want = $false }
    elseif (-not $Unattended) {
        Say ""
        $modelName = if ($hw) { $rec.model } else { "large-v3" }
        Say "  The local engine needs the '$modelName' weights (about 3 GB)." "DarkGray"
        if ($GroqKey) {
            Say "  You have a Groq key, so this is only needed as the offline" "DarkGray"
            Say "  fallback. It downloads automatically the first time it is" "DarkGray"
            Say "  actually required, so skipping here is perfectly safe." "DarkGray"
            $want = AskYesNo "Download it now anyway?" $false
        } else {
            Say "  Without a Groq key this is required to transcribe anything." "DarkGray"
            $want = AskYesNo "Download it now?" $true
        }
    }
    if ($want) {
        Say "  Downloading model, this takes a while..." "DarkGray"
        & $vpy -m livewhisper.bootstrap download-model
        if ($LASTEXITCODE -ne 0) { Warn "Model download failed. It will retry on first use." }
    } else {
        Say "  Skipped. Download later from Settings > Engine, or it happens on first use." "DarkGray"
    }
} finally {
    Pop-Location
}

# ------------------------------------------------------------------ shortcuts
if (-not $NoShortcuts) {
    Step "Creating shortcuts"

    $pyw = Join-Path $venv "Scripts\pythonw.exe"
    $entry = Join-Path $InstallDir "run.py"
    $icon = Join-Path $InstallDir "assets\livewhisper.ico"
    $shell = New-Object -ComObject WScript.Shell

    function New-Shortcut($path) {
        $sc = $shell.CreateShortcut($path)
        $sc.TargetPath = $pyw
        $sc.Arguments = "`"$entry`""
        $sc.WorkingDirectory = $InstallDir
        $sc.IconLocation = "$icon,0"
        $sc.Description = "Hotkey meeting transcription"
        $sc.Save()
    }

    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    New-Shortcut (Join-Path $startMenu "LiveWhisper.lnk")
    Say "  Start Menu" "Green"

    if (AskYesNo "Add a Desktop shortcut?" $true) {
        New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "LiveWhisper.lnk")
        Say "  Desktop" "Green"
    }

    $wantStartup = if ($Startup) { $true } else { AskYesNo "Start LiveWhisper automatically when you sign in?" $true }
    if ($wantStartup) {
        $run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        Set-ItemProperty -Path $run -Name "LiveWhisper" -Value "`"$pyw`" `"$entry`""
        Say "  Runs at sign-in" "Green"
    }
}

# ---------------------------------------------------------------------- done
Step "Verifying"
Push-Location $InstallDir
try { & $vpy check_setup.py } finally { Pop-Location }

Write-Host ""
Write-Host "  Installed to $InstallDir" -ForegroundColor Green
Write-Host ""
Write-Host "  Ctrl+Alt+Space   start / stop recording" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+X       discard recording" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+P       next prompt profile" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+G       switch engine" -ForegroundColor Gray
Write-Host ""
Write-Host "  Right-click the tray icon for Settings." -ForegroundColor DarkGray
Write-Host ""

if (AskYesNo "Launch LiveWhisper now?" $true) {
    Start-Process -FilePath (Join-Path $venv "Scripts\pythonw.exe") `
                  -ArgumentList "`"$(Join-Path $InstallDir 'run.py')`"" `
                  -WorkingDirectory $InstallDir
    Say "  Running in the tray." "Green"
}

