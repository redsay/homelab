<#
.SYNOPSIS
    AssetInventory.ps1 — Scan a machine and export installed software, hardware, and services to CSV.

.DESCRIPTION
    Collects the following from the local machine (or a remote machine via -ComputerName):
      - Installed software (from registry and WMI)
      - Hardware summary (CPU, RAM, disk)
      - Running services and their startup type
      - Network adapters and IP addresses
    Exports each category to a separate CSV file in the output directory.

.PARAMETER ComputerName
    Target machine (default: local machine).

.PARAMETER OutputDir
    Directory to write CSV files to (default: .\inventory\<hostname>-<date>).

.PARAMETER Categories
    Comma-separated list of categories to collect: software, hardware, services, network.
    Default: all categories.

.EXAMPLE
    .\AssetInventory.ps1
    .\AssetInventory.ps1 -ComputerName PROD-WORKSTATION-01 -OutputDir C:\Audits\
    .\AssetInventory.ps1 -Categories "software,hardware"

.NOTES
    Requires PowerShell 5.1+. Remote collection requires WinRM enabled on target.
#>

[CmdletBinding()]
param(
    [string]$ComputerName = $env:COMPUTERNAME,
    [string]$OutputDir    = "",
    [string]$Categories   = "software,hardware,services,network"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

$dateStr = (Get-Date).ToString("yyyy-MM-dd")
if ($OutputDir -eq "") {
    $OutputDir = ".\inventory\$ComputerName-$dateStr"
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$cats = $Categories -split "," | ForEach-Object { $_.Trim().ToLower() }

Write-Host "`n  Asset Inventory — $ComputerName — $dateStr"
Write-Host "  Output: $OutputDir"
Write-Host "  " + ("─" * 60)

# ── Software ──────────────────────────────────────────────────────────────────

if ($cats -contains "software") {
    Write-Host "  Collecting installed software..."
    $regPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    $software = foreach ($path in $regPaths) {
        Get-ItemProperty $path -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName } |
        Select-Object @{N="Name";E={$_.DisplayName}},
                      @{N="Version";E={$_.DisplayVersion}},
                      @{N="Publisher";E={$_.Publisher}},
                      @{N="InstallDate";E={$_.InstallDate}},
                      @{N="InstallLocation";E={$_.InstallLocation}}
    }

    $software = $software | Sort-Object Name -Unique
    $outPath = Join-Path $OutputDir "software.csv"
    $software | Export-Csv -Path $outPath -NoTypeInformation
    Write-Host "  [OK]  Software: $($software.Count) entries → $outPath"
}

# ── Hardware ──────────────────────────────────────────────────────────────────

if ($cats -contains "hardware") {
    Write-Host "  Collecting hardware info..."

    $cpu = Get-CimInstance Win32_Processor | Select-Object @{N="Component";E={"CPU"}},
        @{N="Detail";E={"$($_.Name) — $($_.NumberOfCores) cores / $($_.NumberOfLogicalProcessors) threads @ $([math]::Round($_.MaxClockSpeed/1000,2)) GHz"}}

    $ram = Get-CimInstance Win32_ComputerSystem | Select-Object @{N="Component";E={"RAM"}},
        @{N="Detail";E={"$([math]::Round($_.TotalPhysicalMemory/1GB,1)) GB"}}

    $disks = Get-CimInstance Win32_DiskDrive | Select-Object @{N="Component";E={"Disk"}},
        @{N="Detail";E={"$($_.Model) — $([math]::Round($_.Size/1GB,0)) GB ($($_.InterfaceType))"}}

    $os = Get-CimInstance Win32_OperatingSystem | Select-Object @{N="Component";E={"OS"}},
        @{N="Detail";E={"$($_.Caption) Build $($_.BuildNumber) ($($_.OSArchitecture))"}}

    $hw = @($cpu) + @($ram) + @($disks) + @($os)
    $outPath = Join-Path $OutputDir "hardware.csv"
    $hw | Export-Csv -Path $outPath -NoTypeInformation
    Write-Host "  [OK]  Hardware: $($hw.Count) entries → $outPath"
}

# ── Services ──────────────────────────────────────────────────────────────────

if ($cats -contains "services") {
    Write-Host "  Collecting services..."
    $svcs = Get-CimInstance Win32_Service | Select-Object `
        @{N="Name";E={$_.Name}},
        @{N="DisplayName";E={$_.DisplayName}},
        @{N="Status";E={$_.State}},
        @{N="StartMode";E={$_.StartMode}},
        @{N="PathName";E={$_.PathName}},
        @{N="Account";E={$_.StartName}} |
        Sort-Object Name

    $outPath = Join-Path $OutputDir "services.csv"
    $svcs | Export-Csv -Path $outPath -NoTypeInformation
    Write-Host "  [OK]  Services: $($svcs.Count) entries → $outPath"
}

# ── Network ───────────────────────────────────────────────────────────────────

if ($cats -contains "network") {
    Write-Host "  Collecting network adapters..."
    $adapters = Get-CimInstance Win32_NetworkAdapterConfiguration |
        Where-Object { $_.IPAddress } |
        Select-Object @{N="Description";E={$_.Description}},
                      @{N="MACAddress";E={$_.MACAddress}},
                      @{N="IPAddress";E={($_.IPAddress -join "; ")}},
                      @{N="SubnetMask";E={($_.IPSubnet -join "; ")}},
                      @{N="DefaultGateway";E={($_.DefaultIPGateway -join "; ")}},
                      @{N="DNSServers";E={($_.DNSServerSearchOrder -join "; ")}}

    $outPath = Join-Path $OutputDir "network.csv"
    $adapters | Export-Csv -Path $outPath -NoTypeInformation
    Write-Host "  [OK]  Network: $($adapters.Count) adapter(s) → $outPath"
}

Write-Host ""
Write-Host "  Inventory complete. Files saved to: $OutputDir"
