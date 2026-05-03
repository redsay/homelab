<#
.SYNOPSIS
    ServiceMonitor.ps1 — Check that required Windows services are running and log results.

.DESCRIPTION
    Reads a list of required service names, checks their status, attempts to start
    any stopped services (if -AutoRestart is specified), and logs results to a
    structured log file. Optionally sends a summary to a webhook URL.

.PARAMETER ServiceNames
    Comma-separated list of service names to check. If omitted, reads from -ConfigPath.

.PARAMETER ConfigPath
    Path to a JSON config file containing service definitions. Defaults to
    .\service_monitor_config.json if it exists.

.PARAMETER LogPath
    Path to the log file. Defaults to .\logs\service_monitor.log

.PARAMETER AutoRestart
    If specified, attempt to start any stopped services automatically.

.PARAMETER WebhookUrl
    If provided, POST a plain-text summary to this URL when services are down.

.EXAMPLE
    .\ServiceMonitor.ps1 -ServiceNames "Spooler,W32Time,WinRM"
    .\ServiceMonitor.ps1 -ConfigPath .\services.json -AutoRestart -LogPath C:\Logs\svc.log

.NOTES
    Exit code 0: all services running
    Exit code 1: one or more services not running after checks
#>

[CmdletBinding()]
param(
    [string]$ServiceNames = "",
    [string]$ConfigPath   = ".\service_monitor_config.json",
    [string]$LogPath      = ".\logs\service_monitor.log",
    [switch]$AutoRestart,
    [string]$WebhookUrl   = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Logging ──────────────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Level, [string]$Message)
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $entry = "$ts [$Level] $Message"

    $logDir = Split-Path $LogPath -Parent
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    Add-Content -Path $LogPath -Value $entry
    Write-Host "  $entry"
}

# ── Load service list ─────────────────────────────────────────────────────────

$services = @()

if ($ServiceNames -ne "") {
    $services = $ServiceNames -split "," | ForEach-Object { $_.Trim() }
}
elseif (Test-Path $ConfigPath) {
    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $services = $config.services | ForEach-Object { $_.name }
}
else {
    Write-Log "ERROR" "No service names provided and config file not found: $ConfigPath"
    exit 1
}

# ── Check each service ────────────────────────────────────────────────────────

$results = @()
$countOk = 0
$countDown = 0

foreach ($svcName in $services) {
    try {
        $svc = Get-Service -Name $svcName -ErrorAction Stop
        $status = $svc.Status.ToString()

        if ($status -eq "Running") {
            Write-Log "INFO" "[OK]      $svcName   status=Running"
            $countOk++
            $results += [PSCustomObject]@{ Name=$svcName; Status="Running"; Action="none" }
        }
        else {
            $action = "none"
            if ($AutoRestart) {
                try {
                    Start-Service -Name $svcName -ErrorAction Stop
                    Start-Sleep -Seconds 2
                    $svc.Refresh()
                    $newStatus = $svc.Status.ToString()
                    if ($newStatus -eq "Running") {
                        $action = "restarted"
                        $countOk++
                        Write-Log "WARN" "[RESTARTED] $svcName   was=$status now=Running"
                    }
                    else {
                        $action = "restart_failed"
                        $countDown++
                        Write-Log "ERROR" "[FAILED]  $svcName   restart attempted, still $newStatus"
                    }
                }
                catch {
                    $action = "restart_error"
                    $countDown++
                    Write-Log "ERROR" "[FAILED]  $svcName   restart error: $_"
                }
            }
            else {
                $countDown++
                Write-Log "WARN" "[DOWN]    $svcName   status=$status"
            }
            $results += [PSCustomObject]@{ Name=$svcName; Status=$status; Action=$action }
        }
    }
    catch {
        Write-Log "ERROR" "[MISSING] $svcName   service not found: $_"
        $countDown++
        $results += [PSCustomObject]@{ Name=$svcName; Status="NotFound"; Action="none" }
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Log "INFO" "Result: $countOk OK, $countDown down out of $($services.Count) checked"

if ($countDown -gt 0 -and $WebhookUrl -ne "") {
    $downList = ($results | Where-Object { $_.Status -ne "Running" } | ForEach-Object { $_.Name }) -join ", "
    $body = @{ text = "Service monitor on $env:COMPUTERNAME: $countDown service(s) down: $downList" } | ConvertTo-Json
    try {
        Invoke-RestMethod -Uri $WebhookUrl -Method Post -Body $body -ContentType "application/json" | Out-Null
    }
    catch {
        Write-Log "WARN" "Webhook notification failed: $_"
    }
}

exit ($countDown -gt 0 ? 1 : 0)
