param(
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogsDir = Join-Path $ProjectRoot "logs"
$PidFile = Join-Path $LogsDir "server-$Port.pid"
$ParentPidFile = Join-Path $LogsDir "server-$Port.parent.pid"
$LauncherLog = Join-Path $LogsDir "launcher.log"
$OutLog = Join-Path $LogsDir "server-$Port.out.log"
$ErrLog = Join-Path $LogsDir "server-$Port.err.log"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Write-LauncherLog {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Path $LauncherLog -Value $line
    Write-Host $Message
}

function Test-ProcessAlive {
    param([int]$ProcessId)
    try {
        $null = Get-Process -Id $ProcessId -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

if (Test-Path $PidFile) {
    $savedPid = [int](Get-Content $PidFile -Raw)
    if (Test-ProcessAlive $savedPid) {
        Write-LauncherLog "Job Auto-Apply is already running on http://localhost:$Port (PID $savedPid)."
        exit 0
    }
    Remove-Item -Path $PidFile -Force
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Write-LauncherLog "Port $Port is already in use by PID $($listener.OwningProcess). Not starting another server."
    Set-Content -Path $PidFile -Value $listener.OwningProcess
    exit 0
}

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PORT = "$Port"
$process = Start-Process `
    -FilePath $Python `
    -ArgumentList "main.py" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

Set-Content -Path $ParentPidFile -Value $process.Id

$serverPid = $process.Id
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    $newListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($newListener) {
        $serverPid = [int]$newListener.OwningProcess
        break
    }
}

Set-Content -Path $PidFile -Value $serverPid
Write-LauncherLog "Started Job Auto-Apply on http://localhost:$Port (PID $serverPid, parent PID $($process.Id)). Logs: $OutLog and $ErrLog"
