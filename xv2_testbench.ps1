<#
Open CAN Test Bench on Windows against the live XV2 CAN bus over Tailscale.

  XV2 bus -> Pi can0 -> cannelloni TCP server (Pi, port 20000) -> Tailscale -> CAN Test Bench "cannelloni"

The Pi runs the server permanently as the systemd service xv2-start-canneloni.service
(cannelloni -I can0 -C s -l 20000 -p), so nothing is started or stopped here. This script checks over
SSH, read-only, that the service is up, can0 is UP and no other client holds the server
(cannelloni serves one client at a time), then opens CAN Test Bench. No vcan or local cannelloni is
involved: CAN Test Bench speaks cannelloni itself (cannelloni_bus.py).

Usage (PowerShell):
  .\xv2_testbench.ps1                                   check, then open CAN Test Bench from source (venv)
  .\xv2_testbench.ps1 -Exe C:\path\to\can_testbench.exe  check, then open a built executable
  .\xv2_testbench.ps1 -CheckOnly                        only check

In CAN Test Bench choose Interface Type "cannelloni", Channel "xv2-pi-0", Port 20000 (it remembers this).
Listen Mode is on by default for cannelloni and the bus then refuses to send. With it off, anything
CAN Test Bench transmits goes onto the boat.
#>
param(
    [string]$Exe = "",
    [switch]$CheckOnly,
    [string]$PiHost = "xv2-pi-0",
    [string]$PiUser = "envgo",
    [int]$Port = 20000
)
# Not "Stop": in Windows PowerShell 5.1 a native command's redirected stderr would then abort the script.
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Warn($text) { Write-Host "WARNING: $text" -ForegroundColor Yellow }
function Die($text) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit 1 }

# --- 1. Prerequisites --------------------------------------------------------
$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { $ts = "$env:ProgramFiles\Tailscale\tailscale.exe" }
if (-not (Test-Path $ts)) { Die "Tailscale is not installed." }
if (-not $CheckOnly) {
    if ($Exe) {
        if (-not (Test-Path $Exe)) { Die "No such file: $Exe" }
    } elseif (-not (Test-Path "$here\venv\Scripts\python.exe")) {
        Die "No venv in $here (README, 'Remote CAN bus over cannelloni'), or pass -Exe"
    }
}
$pcIp = (& $ts ip -4 2>$null | Select-Object -First 1)
if (-not $pcIp) { Die "Tailscale is not up on this PC." }
$piIp = (& $ts ip -4 $PiHost 2>$null | Select-Object -First 1)
if (-not $piIp) { Die "Tailscale doesn't know $PiHost. Is it shared with you?" }

# --- 2. Read-only checks on the Pi ------------------------------------------
Say "Checking $PiHost ($piIp); this PC is $pcIp"
$check = @"
echo "service: `$(systemctl is-active xv2-start-canneloni.service)"
echo "can0: `$(ip -br link show can0 2>/dev/null | awk '{print `$2}')"
echo "clients: `$(ss -Htn state established '( sport = :$Port )' | awk '{print `$4}' | paste -sd' ')"
"@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($check.Replace("`r`n", "`n")))
$out = & ssh -o BatchMode=yes -o ConnectTimeout=10 "$PiUser@$PiHost" "echo $b64 | base64 -d | bash" 2>$null
if ($LASTEXITCODE -ne 0) {
    Warn "Can't SSH to $PiUser@$PiHost, so the checks are skipped. Is XV2 powered on and online in 'tailscale status'?"
} else {
    $status = @{}
    foreach ($line in $out) { if ($line -match '^(\w+): ?(.*)$') { $status[$Matches[1]] = $Matches[2].Trim() } }
    Write-Host "cannelloni service: $($status.service); can0: $($status.can0); connected clients: $(if ($status.clients) { $status.clients } else { 'none' })"
    if ($status.service -ne "active") { Die "xv2-start-canneloni.service is not running on the Pi (sudo systemctl status xv2-start-canneloni there)." }
    if ($status.can0 -ne "UP") { Warn "can0 is not UP on the Pi; no traffic will arrive." }
    if ($status.clients) { Die "Another client is connected ($($status.clients)); cannelloni serves one at a time. Close it first." }
}
if ($CheckOnly) { Say "Checks done."; exit 0 }

# --- 3. CAN Test Bench -------------------------------------------------------
Say "Opening CAN Test Bench: choose cannelloni / $PiHost / port $Port, then Connect"
Push-Location $here
try {
    if ($Exe) { & $Exe } else { & "$here\venv\Scripts\python.exe" "$here\can_testbench.py" }
} finally { Pop-Location }
