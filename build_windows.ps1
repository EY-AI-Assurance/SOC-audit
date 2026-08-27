param(
    [switch]$DebugBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Assert-NativeSuccess {
    param(
        [int]$ExitCode,
        [string]$Step
    )

    if ($ExitCode -ne 0) {
        throw "$Step failed with exit code $ExitCode. Review the error output above."
    }
}

if (-not (Test-Path "backend/.env")) {
    throw "backend/.env is missing. Copy backend/.env.example to backend/.env and add the API configuration before building."
}

Write-Warning "The local backend/.env file, including its API credentials, will be embedded in the executable. PyInstaller packaging does not encrypt secrets."

Write-Host "Installing Python packaging dependencies..."
python -m pip install -r requirements-desktop.txt
Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "Python dependency installation"

Write-Host "Building the React frontend..."
npm --prefix frontend ci
Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "Frontend dependency installation"
npm --prefix frontend run build
Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "Frontend production build"

$bundleMode = if ($DebugBuild) { "--onedir" } else { "--onefile" }
$windowMode = if ($DebugBuild) { "--console" } else { "--windowed" }
$distPath = Join-Path $PSScriptRoot "dist"
$workPath = Join-Path ([System.IO.Path]::GetTempPath()) ("SOC-Audit-PyInstaller-" + [guid]::NewGuid().ToString("N"))
$artifactPath = if ($DebugBuild) {
    Join-Path $distPath "SOC-Audit\SOC-Audit.exe"
} else {
    Join-Path $distPath "SOC-Audit.exe"
}
$artifactTarget = if ($DebugBuild) {
    Join-Path $distPath "SOC-Audit"
} else {
    $artifactPath
}

# PyInstaller work files are intentionally kept outside the repository. This
# avoids OneDrive/Defender locks on build/SOC-Audit/localpycs.
New-Item -ItemType Directory -Path $workPath -Force | Out-Null

if (Test-Path $artifactTarget) {
    try {
        Remove-Item $artifactTarget -Recurse -Force
    } catch {
        throw "Cannot replace '$artifactTarget'. Close every running SOC-Audit.exe and try again. $($_.Exception.Message)"
    }
}

$pyinstallerArgs = @(
    "--noconfirm"
    "--clean"
    $bundleMode
    $windowMode
    "--name", "SOC-Audit"
    "--paths", "backend"
    "--distpath", $distPath
    "--workpath", $workPath
    "--specpath", $workPath
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

try {
    Write-Host "Building SOC-Audit..."
    Write-Host "Temporary PyInstaller work directory: $workPath"
    python -m PyInstaller @pyinstallerArgs
    Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "PyInstaller build"

    if (-not (Test-Path $artifactPath -PathType Leaf)) {
        throw "PyInstaller reported success, but the expected output was not found at '$artifactPath'."
    }

    if ($DebugBuild) {
        Write-Host "Debug build created at $artifactPath"
    } else {
        Write-Host "Release build created at $artifactPath"
    }
} finally {
    if (Test-Path $workPath) {
        Remove-Item $workPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}
