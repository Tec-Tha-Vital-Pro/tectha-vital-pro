# Tec Tha Vital - one-command demo on a Windows laptop.
#
#   Double-click setup-and-run-demo.bat, or in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\setup-and-run-demo.ps1 [-Port 8010] [-NoBrowser] [-KeepData] [-Fresh]
#
# Creates .venv, installs requirements, loads sample data for two branches, creates an admin
# login called "demo", starts the server on http://127.0.0.1:<port> and opens the browser.
# WhatsApp is forced to simulator mode (nothing is sent). The demo uses data\demo.db so a real
# database is never wiped by accident. Stop the server with Ctrl+C.
param(
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$KeepData,
    [switch]$Fresh
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$AdminUser = if ($env:TT_DEMO_USER) { $env:TT_DEMO_USER } else { "demo" }

function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

# ---- 1. Python 3.10 or newer ("py" launcher first, then python)
$Py = $null
foreach ($cand in @(@("py", "-3"), @("python"), @("python3"))) {
    $exe = $cand[0]; $pre = @($cand | Select-Object -Skip 1)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        & $exe @pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = $cand; break }
    }
}
if (-not $Py) { Fail "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again." }
$PyExe = $Py[0]; $PyPre = @($Py | Select-Object -Skip 1)
Say ("Using " + (& $PyExe @PyPre --version))

# ---- 2. Virtual environment and requirements
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Say "Creating virtual environment in .venv"
    & $PyExe @PyPre -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv" }
}
$ReqHash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
$Stamp = Join-Path $Root ".venv\.tt-requirements.sha256"
if (-not (Test-Path $Stamp) -or ((Get-Content $Stamp -Raw).Trim() -ne $ReqHash)) {
    Say "Installing requirements (first run takes a minute or two)"
    & $VPy -m pip install --disable-pip-version-check -q --upgrade pip
    & $VPy -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed (check the internet connection)" }
    Set-Content -Path $Stamp -Value $ReqHash
} else { Say "Requirements already installed" }

# ---- 3. Demo settings (never live WhatsApp from this script)
if (-not $env:TT_DB_PATH) { $env:TT_DB_PATH = Join-Path $Root "data\demo.db" }
if ($env:TT_WHATSAPP_MODE -and $env:TT_WHATSAPP_MODE -ne "simulator") {
    Fail "TT_WHATSAPP_MODE is '$($env:TT_WHATSAPP_MODE)'. This demo script only runs in simulator mode."
}
$env:TT_WHATSAPP_MODE = "simulator"
if (-not $env:TT_SESSION_SECRET) { $env:TT_SESSION_SECRET = (& $VPy -c "import secrets; print(secrets.token_urlsafe(32))") }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $env:TT_DB_PATH) | Out-Null

if ($Fresh -and (Test-Path $env:TT_DB_PATH)) {
    Say "Deleting demo database $($env:TT_DB_PATH)"
    Remove-Item -Force "$($env:TT_DB_PATH)*"
}

# ---- 4. Sample data
if (-not $KeepData -or -not (Test-Path $env:TT_DB_PATH)) {
    Say "Loading sample data for two branches into $($env:TT_DB_PATH) (staff logins are kept)"
    & $VPy -m app.seed
    if ($LASTEXITCODE -ne 0) { Fail "Loading sample data failed" }
}

# ---- 5. Admin login
$Exists = (& $VPy -c "import sys; from app import db; db.init_db(); print(1 if db.one('SELECT id FROM users WHERE username = ?', (sys.argv[1].lower(),)) else 0)" $AdminUser).Trim()
$ShowPassword = $null
if ($Exists -eq "1") {
    Say "Login '$AdminUser' already exists in this demo database; use the password you chose before."
    Write-Host "    Forgot it? Run again with -Fresh to start over with a new password."
} else {
    $Password = $env:TT_ADMIN_PASSWORD
    if (-not $Password -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        Write-Host "`nChoose a password for the demo login '$AdminUser' (at least 8 characters)."
        Write-Host "Press Enter without typing anything to get a random password instead."
        while ($true) {
            $s1 = Read-Host "Password" -AsSecureString
            $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
            if (-not $Password) { break }
            if ($Password.Length -lt 8) { Write-Host "Too short, try again."; continue }
            $s2 = Read-Host "Repeat password" -AsSecureString
            $P2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
            if ($Password -eq $P2) { break }
            Write-Host "The two passwords do not match, try again."
        }
    }
    if (-not $Password) {
        $Password = (& $VPy -c "import secrets; print(secrets.token_urlsafe(12))").Trim()
        $ShowPassword = $Password
    }
    $env:TT_ADMIN_PASSWORD = $Password
    & $VPy -m app.auth create-admin $AdminUser "Demo Admin"
    $code = $LASTEXITCODE
    Remove-Item Env:\TT_ADMIN_PASSWORD
    $Password = $null; $P2 = $null
    if ($code -ne 0) { Fail "Could not create the demo login" }
}

$Url = "http://127.0.0.1:$Port"

# ---- 6. Open the browser once the server answers
if (-not $NoBrowser -and $env:TT_NO_BROWSER -ne "1") {
    Start-Job -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 60; $i++) {
            try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$u/api/health" | Out-Null; Start-Process "$u/login"; return }
            catch { Start-Sleep -Milliseconds 500 }
        }
    } -ArgumentList $Url | Out-Null
}

# ---- 7. Start
Write-Host ""
Write-Host "------------------------------------------------------------------"
Write-Host " Tec Tha Vital demo"
Write-Host "   Open:      $Url/login"
Write-Host "   Login:     $AdminUser"
if ($ShowPassword) { Write-Host "   Password:  $ShowPassword   (random, shown only once; not saved anywhere)" }
Write-Host "   Database:  $($env:TT_DB_PATH)   (sample data, WhatsApp simulator)"
Write-Host "   Stop:      Ctrl+C"
Write-Host "------------------------------------------------------------------"
# One worker only: the automation scheduler runs inside the server process.
& $VPy -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1
