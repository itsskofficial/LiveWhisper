<#
.SYNOPSIS
    Install LiveWhisper - voice typing that writes your language the way you type it.

.DESCRIPTION
    Works two ways:

      1. From a clone:   .\install.ps1
      2. From nothing:   irm https://raw.githubusercontent.com/itsskofficial/LiveWhisper/main/install.ps1 | iex

    In the second case it downloads the project first. Either way it creates an
    isolated virtualenv, installs dependencies, detects your GPU and configures
    the best local model for it, and creates Start Menu and Desktop shortcuts.

    No admin rights needed. Everything lives under -InstallDir.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -InstallDir "E:\Apps\LiveWhisper" -Language ta -Startup
.EXAMPLE
    .\install.ps1 -Unattended
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\LiveWhisper",
    [string]$GroqKey = "",
    [string]$Language = "",
    [switch]$DownloadModel,
    [switch]$SkipModel,
    [switch]$Startup,
    [switch]$Unattended,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"
$Repo = "itsskofficial/LiveWhisper"

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
Write-Host "  Voice typing in Hinglish, Tanglish, Banglish and 9 more" -ForegroundColor DarkGray
Write-Host "  --------------------------------------------------------" -ForegroundColor DarkGray

# ---------------------------------------------------------------- get source
# When piped from the web there is no script file on disk, so fetch the project.
$Source = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }

if (-not $Source -or -not (Test-Path (Join-Path $Source "livewhisper"))) {
    Step "Downloading LiveWhisper"
    $tmp = Join-Path $env:TEMP "livewhisper-src-$(Get-Random)"
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zip = Join-Path $tmp "src.zip"
    try {
        Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/main.zip" `
                          -OutFile $zip -UseBasicParsing
    } catch {
        Die "Could not download the project. Check your connection, or clone it manually:`n    git clone https://github.com/$Repo.git"
    }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $Source = (Get-ChildItem $tmp -Directory | Where-Object { $_.Name -like "LiveWhisper-*" } |
               Select-Object -First 1).FullName
    if (-not $Source) { Die "Downloaded archive did not contain the project." }
    Say "  Downloaded to $Source" "Green"
}

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
    Say "  VRAM  $($hw.vram_gb) GB    RAM  $($hw.ram_gb) GB    CPU  $($hw.machine.cpus) cores"
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

if (Test-Path (Join-Path $InstallDir "livewhisper")) {
    if (-not (AskYesNo "Existing install found. Upgrade in place (keeps your settings)?" $true)) {
        Die "Cancelled."
    }
} elseif (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# ---------------------------------------------------------------- copy source
Step "Copying application files"

$items = @("livewhisper", "assets", "data", "tools", "ci", "docs", "run.py",
           "requirements.txt", "check_setup.py", "verify.py", "demo_seed.py",
           "README.md", "CONTRIBUTING.md", "LICENSE", "start.bat",
           "uninstall.ps1", ".env.example")
foreach ($item in $items) {
    $src = Join-Path $Source $item
    if (-not (Test-Path $src)) { continue }
    Copy-Item $src -Destination $InstallDir -Recurse -Force
}
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

# torch powers the character model that handles words the dictionary misses.
# CPU-only is plenty - the model is 4.5M parameters - and it keeps the download
# to ~200 MB rather than 2.5 GB.
Say "  Installing the spelling model runtime (CPU torch, ~200 MB)..." "DarkGray"
& $vpy -m pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    Warn "torch did not install. The dictionary still covers ~87% of words; unknown ones stay in the original script."
}
Say "  Dependencies installed" "Green"

# --------------------------------------------------------------------- config
Step "Configuring"

Push-Location $InstallDir
try {
    if ($hw) { & $vpy -m livewhisper.bootstrap apply-recommended }
    & $vpy -m livewhisper.bootstrap make-icon | Out-Null

    # --- language ---
    if (-not $Language -and -not $Unattended) {
        Say ""
        Say "  Which language do you speak and type in Latin letters?" "Yellow"
        Say "    hi Hindi      bn Bengali    ur Urdu       pa Punjabi" "DarkGray"
        Say "    mr Marathi    te Telugu     ta Tamil      gu Gujarati" "DarkGray"
        Say "    kn Kannada    ml Malayalam  si Sinhala    sd Sindhi" "DarkGray"
        Say "    auto - detect it from what you say each time" "DarkGray"
        $Language = Ask "Language" "auto"
    }
    if ($Language) {
        & $vpy -c @"
import sys
from livewhisper import config as c
from livewhisper.script.languages import supported
lang = sys.argv[1].strip().lower()
if lang != 'auto' and not supported(lang):
    print(f'  unknown language {lang!r}, using auto'); lang = 'auto'
cfg = c.load('config.yaml'); cfg.setdefault('script', {})['language'] = lang
c.save('config.yaml', cfg); print(f'  language set to {lang}')
"@ $Language
    }

    # --- Groq key ---
    if (-not $GroqKey -and -not $Unattended) {
        Say ""
        Say "  Optional: a Groq key makes transcription ~2.5x faster, free tier" "DarkGray"
        Say "  available. Leave blank to run entirely on your own machine." "DarkGray"
        Say "  https://console.groq.com" "DarkGray"
        $GroqKey = Ask "Groq API key (optional)" ""
    }
    if ($GroqKey) {
        & $vpy -m livewhisper.bootstrap set-key $GroqKey
    } else {
        Say "  No Groq key - running fully local." "DarkGray"
        & $vpy -c @"
from livewhisper import config as c
cfg = c.load('config.yaml'); cfg['transcription']['backend'] = 'local'
c.save('config.yaml', cfg); print('  engine set to local')
"@
    }

    # --- speech model ---
    $want = $false
    if ($DownloadModel) { $want = $true }
    elseif ($SkipModel) { $want = $false }
    elseif (-not $Unattended) {
        Say ""
        $modelName = if ($hw) { $rec.model } else { "large-v3" }
        Say "  The speech model '$modelName' is about 3 GB." "DarkGray"
        if ($GroqKey) {
            Say "  You have a Groq key, so this is only the offline fallback and" "DarkGray"
            Say "  downloads automatically the first time it is needed." "DarkGray"
            $want = AskYesNo "Download it now anyway?" $false
        } else {
            Say "  Without a Groq key this is required to transcribe anything." "DarkGray"
            $want = AskYesNo "Download it now?" $true
        }
    }
    if ($want) {
        Say "  Downloading, this takes a while..." "DarkGray"
        & $vpy -m livewhisper.bootstrap download-model
        if ($LASTEXITCODE -ne 0) { Warn "Model download failed. It will retry on first use." }
    } else {
        Say "  Skipped - downloads on first use." "DarkGray"
    }

    # --- specialist speech model for the chosen language ---
    # large-v3 is one model for 99 languages and is weak on some of ours. Only
    # models measured against it on real speech are offered; see
    # livewhisper/specialists.py.
    if (-not $Unattended -and $Language -and $Language -ne "auto") {
        $spec = & $vpy -c @"
import sys
from livewhisper.specialists import recommended
s = recommended(sys.argv[1].strip().lower())
print(f'{s.name}|{s.size_gb}|{s.note}' if s else '')
"@ $Language | Select-Object -Last 1
        if ($spec) {
            $parts = $spec -split '\|', 3
            Say ""
            Say "  A speech model tuned for this language is available: $($parts[0]) (~$($parts[1]) GB)." "Yellow"
            if ($parts[2]) { Say "  $($parts[2])" "DarkGray" }
            if (AskYesNo "Install it? It is used automatically whenever you speak this language." $true) {
                Say "  Installing the converter and downloading, this takes a while..." "DarkGray"
                & $vpy -m pip install --quiet "transformers>=4.44,<5" | Out-Null
                & $vpy -m livewhisper.specialists install $Language
                if ($LASTEXITCODE -ne 0) { Warn "Specialist install failed; large-v3 will be used for everything." }
            }
        }
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
        $sc.Description = "Voice typing in your own spelling"
        $sc.Save()
    }

    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    New-Shortcut (Join-Path $startMenu "LiveWhisper.lnk")
    Say "  Start Menu" "Green"

    if (AskYesNo "Add a Desktop shortcut?" $true) {
        New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "LiveWhisper.lnk")
        Say "  Desktop" "Green"
    }

    $wantStartup = if ($Startup) { $true } else { AskYesNo "Start automatically when you sign in?" $true }
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
Write-Host "  Ctrl+Alt+Space   dictate" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+W       speak an instruction, it writes the text" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+F       fix grammar, keeping your style" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+N       notes from system audio" -ForegroundColor Gray
Write-Host "  Ctrl+Alt+H       keep the next dictation in the original script" -ForegroundColor Gray
Write-Host ""
Write-Host "  On first run a one-minute setup learns how you spell." -ForegroundColor DarkGray
Write-Host "  Right-click the tray icon for Settings." -ForegroundColor DarkGray
Write-Host ""

if (AskYesNo "Launch LiveWhisper now?" $true) {
    Start-Process -FilePath (Join-Path $venv "Scripts\pythonw.exe") `
                  -ArgumentList "`"$(Join-Path $InstallDir 'run.py')`"" `
                  -WorkingDirectory $InstallDir
    Say "  Running in the tray." "Green"
}
