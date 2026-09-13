#Requires -Version 5.1
<#
.SYNOPSIS
    Diagnose why child processes die with 0xC0000142 (STATUS_DLL_INIT_FAILED).

.DESCRIPTION
    DeepSeek Harness starts every shell command through a private "Windows Job
    runner" child process. On this machine that child dies during DLL
    initialisation with exit code 3221225794 (0xC0000142), and because the
    harness refuses to silently fall back, every shell-based tool fails.

    This script runs a ladder of child-process probes to separate the three
    candidate causes:

      A. the machine cannot create console processes at all;
      B. the child environment block is missing a Windows-critical variable
         (classically SystemRoot -- without it the loader cannot locate
         conhost.exe and a console app dies at init);
      C. console allocation is what fails, in which case a child started with
         CREATE_NO_WINDOW still works.

    Run it from a normal PowerShell / Windows Terminal window. It only reads
    environment state and starts short-lived child processes; it changes nothing.

.EXAMPLE
    pwsh -NoProfile -ExecutionPolicy Bypass -File .\research\scripts\diagnose_windows_shell.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

function Write-Header {
    param([string]$Text)
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Format-ExitCode {
    param($Code)
    if ($null -eq $Code) { return 'not-started' }
    $unsigned = if ($Code -lt 0) { $Code + 0x100000000L } else { $Code }
    return ('{0} (0x{1:X8})' -f $Code, $unsigned)
}

function Get-Verdict {
    param($Code)
    if ($null -eq $Code) { return 'COULD NOT START' }
    $unsigned = if ($Code -lt 0) { $Code + 0x100000000L } else { $Code }
    if ($unsigned -eq 0) { return 'OK' }
    if ($unsigned -eq 0xC0000142) { return 'DLL INIT FAILED (0xC0000142)' }
    return "exit $unsigned"
}

function Invoke-ChildProbe {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string]$Arguments = '',
        [hashtable]$Environment,
        [switch]$EmptyEnvironment,
        [switch]$NoWindow
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = [bool]$NoWindow

    if ($EmptyEnvironment) {
        $psi.EnvironmentVariables.Clear()
    }
    elseif ($Environment) {
        $psi.EnvironmentVariables.Clear()
        foreach ($key in $Environment.Keys) {
            $psi.EnvironmentVariables[$key] = [string]$Environment[$key]
        }
    }

    $result = [ordered]@{
        ExitCode = $null
        StdOut   = ''
        StdErr   = ''
        Error    = ''
    }

    try {
        $process = [System.Diagnostics.Process]::Start($psi)
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $result.ExitCode = $process.ExitCode
        $result.StdOut = $stdout.Trim()
        $result.StdErr = $stderr.Trim()
    }
    catch {
        $result.Error = $_.Exception.Message
    }

    return [pscustomobject]$result
}

function Show-Probe {
    param([string]$Name, $Probe)
    $verdict = if ($Probe.Error) { "COULD NOT START: $($Probe.Error)" } else { Get-Verdict $Probe.ExitCode }
    $colour = if ($verdict -eq 'OK') { 'Green' } else { 'Red' }
    Write-Host ("  {0,-58} " -f $Name) -NoNewline
    Write-Host $verdict -ForegroundColor $colour
    if ($Probe.StdOut) { Write-Host ("      stdout: {0}" -f ($Probe.StdOut -split "`n")[0]) }
    if ($Probe.StdErr) { Write-Host ("      stderr: {0}" -f ($Probe.StdErr -split "`n")[0]) }
}

Write-Host '======================================================================'
Write-Host ' Windows child-process diagnostic (0xC0000142 / STATUS_DLL_INIT_FAILED)'
Write-Host '======================================================================'
Write-Host ("host powershell : {0}" -f $PSVersionTable.PSVersion)
Write-Host ("host OS         : {0}" -f ([System.Environment]::OSVersion.VersionString))
Write-Host ("64-bit process  : {0}" -f [System.Environment]::Is64BitProcess)

# --------------------------------------------------------------------------- #
Write-Header '1. Environment variables a Windows child process depends on'

$critical = @('SystemRoot', 'windir', 'PATH', 'TEMP', 'TMP', 'ComSpec', 'PATHEXT',
              'NUMBER_OF_PROCESSORS', 'USERPROFILE', 'PROCESSOR_ARCHITECTURE')
$missing = @()
foreach ($name in $critical) {
    $value = [System.Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host ("  {0,-24} MISSING" -f $name) -ForegroundColor Red
        $missing += $name
    }
    else {
        $shown = if ($value.Length -gt 70) { $value.Substring(0, 70) + '...' } else { $value }
        Write-Host ("  {0,-24} {1}" -f $name, $shown)
    }
}
if ($missing.Count -eq 0) {
    Write-Host '  -> all critical variables present in THIS shell' -ForegroundColor Green
}
else {
    Write-Host ("  -> MISSING in this shell: {0}" -f ($missing -join ', ')) -ForegroundColor Red
}

# --------------------------------------------------------------------------- #
Write-Header '2. Key system files'

$systemRoot = [System.Environment]::GetEnvironmentVariable('SystemRoot')
if ([string]::IsNullOrWhiteSpace($systemRoot)) { $systemRoot = 'C:\Windows' }

$files = @{
    'cmd.exe'      = Join-Path $systemRoot 'System32\cmd.exe'
    'conhost.exe'  = Join-Path $systemRoot 'System32\conhost.exe'
    'ucrtbase.dll' = Join-Path $systemRoot 'System32\ucrtbase.dll'
    'kernel32.dll' = Join-Path $systemRoot 'System32\kernel32.dll'
}
foreach ($name in $files.Keys) {
    $path = $files[$name]
    if (Test-Path -LiteralPath $path) {
        $info = Get-Item -LiteralPath $path
        Write-Host ("  {0,-24} present  ({1:N0} bytes, {2})" -f $name, $info.Length, $info.LastWriteTime.ToString('yyyy-MM-dd'))
    }
    else {
        Write-Host ("  {0,-24} MISSING  {1}" -f $name, $path) -ForegroundColor Red
    }
}

$nodePath = (Get-Command node -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if ($nodePath) {
    Write-Host ("  {0,-24} {1}" -f 'node.exe', $nodePath)
}
else {
    Write-Host ("  {0,-24} not on PATH" -f 'node.exe') -ForegroundColor Yellow
}

# --------------------------------------------------------------------------- #
Write-Header '3. Child-process probe ladder'

$cmdPath = $files['cmd.exe']

Write-Host '  A. inherit this shell''s full environment, normal console allocation'
$probeA = Invoke-ChildProbe -FilePath $cmdPath -Arguments '/c ver'
Show-Probe -Name 'cmd /c ver  [full env, console]' -Probe $probeA

Write-Host ''
Write-Host '  B. completely EMPTY environment block (the SystemRoot hypothesis)'
$probeB = Invoke-ChildProbe -FilePath $cmdPath -Arguments '/c ver' -EmptyEnvironment
Show-Probe -Name 'cmd /c ver  [empty env]' -Probe $probeB

Write-Host ''
Write-Host '  C. minimal environment: SystemRoot + PATH + TEMP only'
$minimal = @{}
if ($systemRoot) { $minimal['SystemRoot'] = $systemRoot }
$minimal['windir'] = $systemRoot
$minimal['PATH'] = [System.Environment]::GetEnvironmentVariable('PATH')
$minimal['TEMP'] = [System.Environment]::GetEnvironmentVariable('TEMP')
$minimal['TMP'] = [System.Environment]::GetEnvironmentVariable('TMP')
$minimal['ComSpec'] = $cmdPath
$probeC = Invoke-ChildProbe -FilePath $cmdPath -Arguments '/c ver' -Environment $minimal
Show-Probe -Name 'cmd /c ver  [SystemRoot+PATH+TEMP]' -Probe $probeC

Write-Host ''
Write-Host '  D. empty environment again, but WITHOUT a console (CREATE_NO_WINDOW)'
Write-Host '     -- this mirrors the fallback spawn path the harness can be forced onto'
$probeD = Invoke-ChildProbe -FilePath $cmdPath -Arguments '/c ver' -EmptyEnvironment -NoWindow
Show-Probe -Name 'cmd /c ver  [empty env, no window]' -Probe $probeD

if ($nodePath) {
    Write-Host ''
    Write-Host '  E. node.exe with the full environment'
    $probeE = Invoke-ChildProbe -FilePath $nodePath -Arguments '--version'
    Show-Probe -Name 'node --version  [full env]' -Probe $probeE

    Write-Host ''
    Write-Host '  F. node.exe with an empty environment'
    $probeF = Invoke-ChildProbe -FilePath $nodePath -Arguments '--version' -EmptyEnvironment
    Show-Probe -Name 'node --version  [empty env]' -Probe $probeF
}

# --------------------------------------------------------------------------- #
Write-Header 'Verdict'

function Test-Ok {
    param($Probe)
    if ($null -eq $Probe -or $null -eq $Probe.ExitCode) { return $false }
    $unsigned = if ($Probe.ExitCode -lt 0) { $Probe.ExitCode + 0x100000000L } else { $Probe.ExitCode }
    return ($unsigned -eq 0)
}

$a = Test-Ok $probeA
$b = Test-Ok $probeB
$c = Test-Ok $probeC
$d = Test-Ok $probeD
$e = if ($nodePath) { Test-Ok $probeE } else { $true }

if ($a -and $e) {
    Write-Host '  PASS: this shell can create console child processes normally.' -ForegroundColor Green
    Write-Host '  => The failure is specific to how DeepSeek Harness was launched or to the'
    Write-Host '     environment IT received. Restart DSH from THIS kind of terminal window.'
    if (-not $b) {
        Write-Host ''
        Write-Host '  NOTE: an empty environment block also fails, which confirms that a child'
        Write-Host '        environment missing SystemRoot/windir dies with 0xC0000142. If DSH was'
        Write-Host '        started by a GUI launcher that passed a minimal environment, that alone'
        Write-Host '        explains every tool failing.' -ForegroundColor Yellow
    }
    if ($d -and -not $b) {
        Write-Host ''
        Write-Host '  NOTE: the no-console variant survives an empty environment, so forcing the' -ForegroundColor Yellow
        Write-Host '        harness onto its CREATE_NO_WINDOW fallback path is a viable workaround.' -ForegroundColor Yellow
    }
    if (-not $c) {
        Write-Host ''
        Write-Host '  NOTE: even a minimal SystemRoot+PATH+TEMP environment fails, so the harness' -ForegroundColor Yellow
        Write-Host '        child environment should be checked for missing Windows variables.' -ForegroundColor Yellow
    }
}
else {
    Write-Host '  FAIL: this shell ALSO cannot create child processes.' -ForegroundColor Red
    Write-Host '  => This is a machine-level problem, not a DeepSeek Harness problem.' -ForegroundColor Red
    Write-Host ''
    Write-Host '  Do this, in an ADMINISTRATOR console, then reboot:'
    Write-Host '      sfc /scannow'
    Write-Host '      DISM /Online /Cleanup-Image /RestoreHealth'
    Write-Host ''
    Write-Host '  Also check: third-party antivirus/EDR injecting a broken DLL into every new'
    Write-Host '  process (temporarily disable it and retest), and free desktop heap / handle'
    Write-Host '  exhaustion (a reboot clears it).'
}

Write-Host ''
Write-Host 'Raw exit codes:'
Write-Host ("  A full env      : {0}" -f (Format-ExitCode $probeA.ExitCode))
Write-Host ("  B empty env     : {0}" -f (Format-ExitCode $probeB.ExitCode))
Write-Host ("  C minimal env   : {0}" -f (Format-ExitCode $probeC.ExitCode))
Write-Host ("  D no-window     : {0}" -f (Format-ExitCode $probeD.ExitCode))
if ($nodePath) {
    Write-Host ("  E node full env : {0}" -f (Format-ExitCode $probeE.ExitCode))
    Write-Host ("  F node empty env: {0}" -f (Format-ExitCode $probeF.ExitCode))
}
Write-Host ''
