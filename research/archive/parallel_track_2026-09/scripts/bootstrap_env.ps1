#Requires -Version 5.1
<#
.SYNOPSIS
    Create the Python environment for the CN daily-frequency quant research track.

.DESCRIPTION
    Creates a virtual environment under research\.venv and installs the research
    dependency set. Safe to re-run: an existing venv is reused.

.PARAMETER Python
    Explicit Python launcher to use, e.g. "C:\Python311\python.exe" or "py -3.11".

.PARAMETER VenvDir
    Override the virtual environment directory. Defaults to research\.venv.

.EXAMPLE
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\research\scripts\bootstrap_env.ps1
#>
[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$VenvDir = ''
)

$ErrorActionPreference = 'Stop'

$ResearchRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $VenvDir = Join-Path $ResearchRoot '.venv'
}
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

$RequiredPackages = @(
    'pandas',
    'numpy',
    'pyarrow',
    'scipy',
    'statsmodels',
    'lightgbm',
    'matplotlib',
    'plotly',
    'tqdm',
    'pyyaml',
    'akshare',
    'baostock',
    'tushare'
)

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-PythonLauncher {
    param([string]$Requested)

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return ,@($Requested)
    }

    $attempts = @(
        @('py', '-3.12'),
        @('py', '-3.11'),
        @('py', '-3.10'),
        @('py', '-3'),
        @('python', ''),
        @('python3', '')
    )

    foreach ($attempt in $attempts) {
        $exe = $attempt[0]
        $prefixArg = $attempt[1]
        $found = Get-Command $exe -ErrorAction SilentlyContinue
        if (-not $found) { continue }

        $probeArgs = @()
        if ($prefixArg -ne '') { $probeArgs += $prefixArg }
        $probeArgs += @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')

        try {
            $version = & $exe @probeArgs 2>$null
        }
        catch {
            continue
        }
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) { continue }

        $parts = $version.Trim().Split('.')
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        if ($major -eq 3 -and $minor -ge 10) {
            Write-Host "    found $exe $prefixArg -> Python $version"
            $launcher = @($exe)
            if ($prefixArg -ne '') { $launcher += $prefixArg }
            return ,$launcher
        }
    }

    throw "No Python >= 3.10 found. Install Python 3.11 (https://www.python.org/downloads/) or pass -Python with an explicit path."
}

Write-Host '===================================================='
Write-Host ' CN daily-frequency quant research - environment setup'
Write-Host '===================================================='
Write-Host "research root : $ResearchRoot"
Write-Host "venv dir      : $VenvDir"

Write-Step 'Locating a Python >= 3.10'
$Launcher = Resolve-PythonLauncher -Requested $Python
Write-Host "    launcher: $($Launcher -join ' ')"

if (Test-Path -LiteralPath $VenvPython) {
    Write-Step "Reusing existing virtual environment"
    Write-Host "    $VenvPython"
}
else {
    Write-Step 'Creating virtual environment'
    $createArgs = @()
    if ($Launcher.Count -gt 1) { $createArgs += $Launcher[1..($Launcher.Count - 1)] }
    $createArgs += @('-m', 'venv', $VenvDir)
    & $Launcher[0] @createArgs
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $VenvPython)) { throw "venv python not found at $VenvPython" }
}

Write-Step 'Upgrading pip / setuptools / wheel'
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }

Write-Step 'Installing research dependencies'
$pipArgs = @('-m', 'pip', 'install') + $RequiredPackages
& $VenvPython @pipArgs
if ($LASTEXITCODE -ne 0) { throw "dependency install failed with exit code $LASTEXITCODE" }

Write-Step 'Installed versions'
& $VenvPython -m pip list --format=columns

Write-Step 'Done'
Write-Host "Interpreter: $VenvPython"
Write-Host ''
Write-Host 'Next step - verify the environment and the live data sources:'
Write-Host "  & '$VenvPython' `"$ResearchRoot\scripts\verify_env.py`""
Write-Host ''
