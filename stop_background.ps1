param(
    [int]$Port = 8001
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogsDir = Join-Path $ProjectRoot "logs"
$PidFile = Join-Path $LogsDir "server-$Port.pid"
$ParentPidFile = Join-Path $LogsDir "server-$Port.parent.pid"
$LauncherLog = Join-Path $LogsDir "launcher.log"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Write-LauncherLog {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Path $LauncherLog -Value $line
    Write-Host $Message
}

$processIdsToStop = @()
if (Test-Path $PidFile) {
    $processIdsToStop += [int](Get-Content $PidFile -Raw)
}
if (Test-Path $ParentPidFile) {
    $processIdsToStop += [int](Get-Content $ParentPidFile -Raw)
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $processIdsToStop += [int]$listener.OwningProcess
    $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($listenerProcess) {
        $parentProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listenerProcess.ParentProcessId)" -ErrorAction SilentlyContinue
        if ($parentProcess -and $parentProcess.CommandLine -like "*$ProjectRoot*" -and $parentProcess.CommandLine -like "*main.py*") {
            $processIdsToStop += [int]$parentProcess.ProcessId
        }
    }
}

if (-not $processIdsToStop) {
    Write-LauncherLog "No Job Auto-Apply server found on port $Port."
    exit 0
}

function Get-ChildProcessIds {
    param([int]$RootProcessId)
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $RootProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        [int]$child.ProcessId
        Get-ChildProcessIds -RootProcessId ([int]$child.ProcessId)
    }
}

$allProcessIds = @()
foreach ($processId in ($processIdsToStop | Select-Object -Unique)) {
    $allProcessIds += Get-ChildProcessIds -RootProcessId $processId
    $allProcessIds += $processId
}
$allProcessIds = $allProcessIds | Select-Object -Unique

foreach ($processId in $allProcessIds) {
    try {
        $null = Get-Process -Id $processId -ErrorAction Stop
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-LauncherLog "Stopped Job Auto-Apply process on port $Port (PID $processId)."
    } catch {
        Write-LauncherLog "PID $processId was already stopped."
    }
}

if (Test-Path $PidFile) {
    Remove-Item -Path $PidFile -Force
}
if (Test-Path $ParentPidFile) {
    Remove-Item -Path $ParentPidFile -Force
}
