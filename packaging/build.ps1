# Build dist\Fizzy\Fizzy.exe and dist\Fizzy-Setup-<version>.exe.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
#
# Uses .venv\Scripts\python.exe when it exists, otherwise python on PATH.
# The installer step needs Inno Setup 6 (winget install JRSoftware.InnoSetup).

param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    # PowerShell 5.1 turns native stderr into errors under "Stop"; rely on the exit code instead.
    $ErrorActionPreference = "Continue"
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

$Version = (Select-String -Path "fizzy\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building Fizzy $Version"

& $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    Invoke-Checked $Python @("-m", "pip", "install", "pyinstaller>=6.10")
}

Write-Host "`n==> Icon"
Invoke-Checked $Python @("packaging\make_icon.py", "build\fizzy.ico")

Write-Host "`n==> PyInstaller"
Invoke-Checked $Python @("-m", "PyInstaller", "packaging\fizzy.spec", "--noconfirm", "--clean",
    "--distpath", "dist", "--workpath", "build\pyinstaller")

if ($SkipInstaller) {
    Write-Host "`nDone: dist\Fizzy\Fizzy.exe"
    exit 0
}

Write-Host "`n==> Inno Setup"
$Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) {
    throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup (or pass -SkipInstaller)"
}
Invoke-Checked $Iscc @("/Qp", "/DAppVersion=$Version", "packaging\installer.iss")

Write-Host "`nDone: dist\Fizzy-Setup-$Version.exe"
