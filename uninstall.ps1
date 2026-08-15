<#
.SYNOPSIS
    Remove LiveWhisper.
.EXAMPLE
    .\uninstall.ps1 -InstallDir "E:\Apps\LiveWhisper"
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\LiveWhisper",
    [switch]$KeepTranscripts
)

$ErrorActionPreference = "Stop"
function Say([string]$m, [string]$c = "Gray") { Write-Host $m -ForegroundColor $c }

Write-Host ""
Say "Uninstalling LiveWhisper from $InstallDir" "Yellow"

# Stop it if it is running out of this install.
Get-Process pythonw, python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir) } |
    ForEach-Object { Say "  stopping pid $($_.Id)"; Stop-Process -Id $_.Id -Force }

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if (Get-ItemProperty -Path $run -Name "LiveWhisper" -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $run -Name "LiveWhisper"
    Say "  removed sign-in entry" "Green"
}

foreach ($lnk in @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\LiveWhisper.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "LiveWhisper.lnk"))) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Say "  removed $(Split-Path -Leaf $lnk)" "Green" }
}

if (Test-Path $InstallDir) {
    $transcripts = Join-Path $InstallDir "transcripts"
    if ($KeepTranscripts -and (Test-Path $transcripts)) {
        $keep = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "LiveWhisper-transcripts"
        Move-Item $transcripts $keep -Force
        Say "  transcripts moved to $keep" "Green"
    }
    Remove-Item $InstallDir -Recurse -Force
    Say "  removed $InstallDir" "Green"
}

Write-Host ""
Say "Done. The downloaded Whisper models are in the HuggingFace cache" "Gray"
Say "(%USERPROFILE%\.cache\huggingface or `$env:HF_HOME) and were left alone." "Gray"
Write-Host ""
