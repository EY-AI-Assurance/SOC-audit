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

$bundleMode = if ($DebugBuild) { "--onedir" } else { "--onefile" }
$windowMode = if ($DebugBuild) { "--console" } else { "--windowed" }
$distPath = Join-Path $PSScriptRoot "dist"
$backendPath = Join-Path $PSScriptRoot "backend"
$desktopEntryPath = Join-Path $PSScriptRoot "desktop.py"
$promptsPath = Join-Path $backendPath "app\prompts"
$searchTermsPath = Join-Path $backendPath "app\search_terms"
$envPath = Join-Path $backendPath ".env"
$tempBuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("SOC-Audit-Build-" + [guid]::NewGuid().ToString("N"))
$frontendSourcePath = Join-Path $PSScriptRoot "frontend"
$frontendWorkPath = Join-Path $tempBuildRoot "frontend"
$frontendDistPath = Join-Path $frontendWorkPath "dist"
$pyinstallerWorkPath = Join-Path $tempBuildRoot "pyinstaller"
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

New-Item -ItemType Directory -Path $frontendWorkPath -Force | Out-Null
New-Item -ItemType Directory -Path $pyinstallerWorkPath -Force | Out-Null

try {
    Write-Host "Installing Python packaging dependencies..."
    python -m pip install -r requirements-desktop.txt
    Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "Python dependency installation"

    # npm ci deletes and recreates node_modules. Perform it in a temporary copy
    # outside OneDrive so sync clients, Defender, and editors cannot lock files.
    Write-Host "Copying the frontend to a temporary build directory..."
    $excludedFrontendItems = @("node_modules", "dist", "dist-ssr")
    Get-ChildItem -LiteralPath $frontendSourcePath -Force |
        Where-Object { $excludedFrontendItems -notcontains $_.Name } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $frontendWorkPath -Recurse -Force
        }

    Write-Host "Building the React frontend in: $frontendWorkPath"
    npm --prefix $frontendWorkPath ci
    Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "Frontend dependency installation"
    npm --prefix $frontendWorkPath run build
    Assert-NativeSuccess -ExitCode $LASTEXITCODE -Step "Frontend production build"

    $frontendIndexPath = Join-Path $frontendDistPath "index.html"
    if (-not (Test-Path $frontendIndexPath -PathType Leaf)) {
        throw "Frontend build reported success, but '$frontendIndexPath' was not created."
    }

    if (Test-Path $artifactTarget) {
        try {
            Remove-Item $artifactTarget -Recurse -Force
        } catch {
            throw "Cannot replace '$artifactTarget'. Close every running SOC-Audit.exe and try again. $($_.Exception.Message)"
        }
    }

    # PyInstaller resolves relative inputs from the generated spec file's
    # directory. The spec lives under %TEMP%, so every project input must be
    # absolute. PathSeparator is ';' on Windows, which also avoids ambiguity
    # with the drive-letter colon in paths such as C:\\... .
    $dataSeparator = [System.IO.Path]::PathSeparator
    $frontendDataArg = "{0}{1}frontend/dist" -f $frontendDistPath, $dataSeparator
    $promptsDataArg = "{0}{1}backend/app/prompts" -f $promptsPath, $dataSeparator
    $searchTermsDataArg = "{0}{1}backend/app/search_terms" -f $searchTermsPath, $dataSeparator
    $envDataArg = "{0}{1}." -f $envPath, $dataSeparator
    $pyinstallerArgs = @(
        "--noconfirm"
        "--clean"
        $bundleMode
        $windowMode
        "--name", "SOC-Audit"
        "--paths", $backendPath
        "--distpath", $distPath
        "--workpath", $pyinstallerWorkPath
        "--specpath", $pyinstallerWorkPath
        "--add-data", $frontendDataArg
        "--add-data", $promptsDataArg
        "--add-data", $searchTermsDataArg
        "--add-data", $envDataArg
        "--collect-all", "pdfplumber"
        "--collect-all", "pdfminer"
        "--collect-all", "openpyxl"
        "--collect-submodules", "uvicorn"
        $desktopEntryPath
    )

    Write-Host "Building SOC-Audit..."
    Write-Host "Temporary build root: $tempBuildRoot"
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
    if (Test-Path $tempBuildRoot) {
        Remove-Item $tempBuildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
