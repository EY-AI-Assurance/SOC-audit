param(
    [switch]$DebugBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "backend/.env")) {
    throw "backend/.env is missing. Copy backend/.env.example to backend/.env and add the API configuration before building."
}

Write-Warning "The local backend/.env file, including its API credentials, will be embedded in the executable. PyInstaller packaging does not encrypt secrets."

Write-Host "Installing Python packaging dependencies..."
python -m pip install -r requirements-desktop.txt

Write-Host "Building the React frontend..."
npm --prefix frontend ci
npm --prefix frontend run build

$bundleMode = if ($DebugBuild) { "--onedir" } else { "--onefile" }
$windowMode = if ($DebugBuild) { "--console" } else { "--windowed" }

$pyinstallerArgs = @(
    "--noconfirm"
    "--clean"
    $bundleMode
    $windowMode
    "--name", "SOC-Audit"
    "--paths", "backend"
    "--add-data", "frontend/dist:frontend/dist"
    "--add-data", "backend/app/prompts:backend/app/prompts"
    "--add-data", "backend/app/search_terms:backend/app/search_terms"
    "--add-data", "backend/.env:."
    "--collect-all", "pdfplumber"
    "--collect-all", "pdfminer"
    "--collect-all", "openpyxl"
    "--collect-submodules", "uvicorn"
    "desktop.py"
)

Write-Host "Building SOC-Audit..."
python -m PyInstaller @pyinstallerArgs

if ($DebugBuild) {
    Write-Host "Debug build created at dist/SOC-Audit/SOC-Audit.exe"
} else {
    Write-Host "Release build created at dist/SOC-Audit.exe"
}
