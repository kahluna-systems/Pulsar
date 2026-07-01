#Requires -Version 5.1
<#
.SYNOPSIS
    KahLuna Pulsar - Network Test Client for Windows
.DESCRIPTION
    A lightweight, transparent network testing tool.
    Tests connectivity, latency, download and upload speeds.
    No installation required - just run this script.
.NOTES
    - No data collected beyond what's shown on screen
    - Self-deleting option after completion
    - Source code fully visible and auditable
#>

param(
    [string]$ServerUrl = "{{SERVER_URL}}"
)

$Version = "1.0.0"
$ErrorActionPreference = "SilentlyContinue"

# Skip SSL certificate validation for internal servers
add-type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-ColorText {
    param([string]$Text, [string]$Color = "White")
    Write-Host $Text -ForegroundColor $Color
}

function Show-Banner {
    Clear-Host
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  KAHLUNA PULSAR - NETWORK TEST" -ForegroundColor White
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Version: $Version"
    Write-Host "Server:  $ServerUrl"
    Write-Host "Time:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host ""
    Write-Host "This tool will:"
    Write-Host "  1. Test connectivity to the diagnostic server"
    Write-Host "  2. Measure network latency (ping)"
    Write-Host "  3. Test download speed"
    Write-Host "  4. Test upload speed"
    Write-Host "  5. Display results"
    Write-Host ""
    Write-Host ("-" * 60) -ForegroundColor Gray
    Read-Host "Press Enter to start the test"
    Write-Host ""
}

function Test-Connectivity {
    Write-ColorText "[1/5] Testing connectivity..." "Cyan"
    try {
        $response = Invoke-WebRequest -Uri "$ServerUrl/api/speedtest/ping" -TimeoutSec 10 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-ColorText "      [OK] Server is reachable" "Green"
            return $true
        }
    } catch {
        Write-ColorText "      [FAIL] Connection failed: $_" "Red"
        return $false
    }
    return $false
}

function Test-Latency {
    param([int]$Count = 10)
    
    Write-ColorText "[2/5] Measuring latency ($Count samples)..." "Cyan"
    $times = @()
    
    for ($i = 1; $i -le $Count; $i++) {
        try {
            $start = Get-Date
            $null = Invoke-WebRequest -Uri "$ServerUrl/api/speedtest/ping" -TimeoutSec 5 -UseBasicParsing
            $elapsed = ((Get-Date) - $start).TotalMilliseconds
            $times += $elapsed
            Write-Host "`r      Sample $i/$Count : $([math]::Round($elapsed, 1))ms" -NoNewline
        } catch {}
    }
    Write-Host ""
    
    if ($times.Count -gt 0) {
        $result = @{
            Min = [math]::Round(($times | Measure-Object -Minimum).Minimum, 2)
            Avg = [math]::Round(($times | Measure-Object -Average).Average, 2)
            Max = [math]::Round(($times | Measure-Object -Maximum).Maximum, 2)
            Samples = $times.Count
        }
        Write-ColorText "      [OK] Latency: $($result.Avg)ms avg (min: $($result.Min)ms, max: $($result.Max)ms)" "Green"
        return $result
    } else {
        Write-ColorText "      [FAIL] Could not measure latency" "Red"
        return $null
    }
}

function Test-Download {
    param([int]$Duration = 10)
    
    Write-ColorText "[3/5] Testing download speed ($Duration`s)..." "Cyan"
    
    $totalBytes = 0
    $startTime = Get-Date
    $endTime = $startTime.AddSeconds($Duration)
    
    while ((Get-Date) -lt $endTime) {
        try {
            $response = Invoke-WebRequest -Uri "$ServerUrl/api/speedtest/download?size=1048576" -TimeoutSec 30 -UseBasicParsing
            $totalBytes += $response.Content.Length
            
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            $currentMbps = [math]::Round(($totalBytes * 8) / ($elapsed * 1000000), 1)
            $downloadedMB = [math]::Round($totalBytes / 1MB, 1)
            Write-Host "`r      Downloaded: $downloadedMB MB | Speed: $currentMbps Mbps" -NoNewline
        } catch {}
    }
    Write-Host ""
    
    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $mbps = [math]::Round(($totalBytes * 8) / ($elapsed * 1000000), 2)
    $downloadedMB = [math]::Round($totalBytes / 1MB, 1)
    
    Write-ColorText "      [OK] Download: $mbps Mbps ($downloadedMB MB in $([math]::Round($elapsed, 1))s)" "Green"
    
    return @{
        Mbps = $mbps
        Bytes = $totalBytes
        Duration = [math]::Round($elapsed, 2)
    }
}

function Test-Upload {
    param([int]$Duration = 10)
    
    Write-ColorText "[4/5] Testing upload speed ($Duration`s)..." "Cyan"
    
    # Generate test data (256KB)
    $testData = New-Object byte[] 262144
    (New-Object Random).NextBytes($testData)
    
    $totalBytes = 0
    $startTime = Get-Date
    $endTime = $startTime.AddSeconds($Duration)
    
    while ((Get-Date) -lt $endTime) {
        try {
            $null = Invoke-WebRequest -Uri "$ServerUrl/api/speedtest/upload" -Method POST -Body $testData -ContentType "application/octet-stream" -TimeoutSec 30 -UseBasicParsing
            $totalBytes += $testData.Length
            
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            $currentMbps = [math]::Round(($totalBytes * 8) / ($elapsed * 1000000), 1)
            $uploadedMB = [math]::Round($totalBytes / 1MB, 1)
            Write-Host "`r      Uploaded: $uploadedMB MB | Speed: $currentMbps Mbps" -NoNewline
        } catch {}
    }
    Write-Host ""
    
    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $mbps = [math]::Round(($totalBytes * 8) / ($elapsed * 1000000), 2)
    $uploadedMB = [math]::Round($totalBytes / 1MB, 1)
    
    Write-ColorText "      [OK] Upload: $mbps Mbps ($uploadedMB MB in $([math]::Round($elapsed, 1))s)" "Green"
    
    return @{
        Mbps = $mbps
        Bytes = $totalBytes
        Duration = [math]::Round($elapsed, 2)
    }
}

function Show-Results {
    param($Results)
    
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  TEST RESULTS" -ForegroundColor White
    Write-Host ("=" * 60) -ForegroundColor Cyan
    
    if ($Results.Latency) {
        Write-Host ""
        Write-Host "  Latency:   $($Results.Latency.Avg) ms"
        Write-Host "             (min: $($Results.Latency.Min) ms, max: $($Results.Latency.Max) ms)"
    }
    
    if ($Results.Download) {
        Write-Host ""
        Write-Host "  Download:  $($Results.Download.Mbps) Mbps"
    }
    
    if ($Results.Upload) {
        Write-Host ""
        Write-Host "  Upload:    $($Results.Upload.Mbps) Mbps"
    }
    
    Write-Host ""
    Write-Host "  Tested:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "  Server:    $ServerUrl"
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Send-Results {
    param($Results)
    
    Write-Host ""
    Write-ColorText "[5/5] Upload results to support team?" "Cyan"
    
    $customerId = Read-Host "      Enter ticket/circuit ID (or press Enter to skip)"
    $choice = Read-Host "      Upload results? (Y/n)"
    
    if ($choice -eq 'n') {
        Write-Host "      Results not uploaded."
        return
    }
    
    try {
        $payload = @{
            ping_ms = $Results.Latency.Avg
            ping_min = $Results.Latency.Min
            ping_max = $Results.Latency.Max
            download_mbps = $Results.Download.Mbps
            upload_mbps = $Results.Upload.Mbps
            customer_id = if ($customerId) { $customerId } else { $null }
            client_type = "powershell_client"
            client_version = $Version
            timestamp = (Get-Date -Format "o")
        } | ConvertTo-Json
        
        $null = Invoke-WebRequest -Uri "$ServerUrl/api/speedtest/result" -Method POST -Body $payload -ContentType "application/json" -TimeoutSec 10 -UseBasicParsing
        Write-ColorText "      [OK] Results uploaded successfully!" "Green"
    } catch {
        Write-ColorText "      [FAIL] Upload failed: $_" "Red"
    }
}

function Remove-Script {
    Write-Host ""
    Write-Host ("-" * 60) -ForegroundColor Gray
    Write-Host "Test complete!"
    Write-Host ""
    
    $choice = Read-Host "Delete this test script from your computer? (y/N)"
    
    if ($choice -eq 'y') {
        $scriptPath = $MyInvocation.ScriptName
        if ($scriptPath) {
            Write-Host "Deleting: $scriptPath"
            Remove-Item -Path $scriptPath -Force -ErrorAction SilentlyContinue
            Write-ColorText "[OK] Script deleted." "Green"
        }
    } else {
        Write-Host "Script kept. You can delete it manually when done."
    }
    
    Write-Host ""
    Write-Host "Thank you for using KahLuna Pulsar!"
    Write-Host ""
    Read-Host "Press Enter to exit"
}

# Main
if ($ServerUrl -eq "{{SERVER_URL}}" -or [string]::IsNullOrEmpty($ServerUrl)) {
    Write-ColorText "Error: No server URL configured." "Red"
    Write-Host "Usage: .\network_test.ps1 -ServerUrl http://server:8000"
    exit 1
}

$ServerUrl = $ServerUrl.TrimEnd('/')

Show-Banner

$results = @{}

if (-not (Test-Connectivity)) {
    Write-ColorText "`nCannot reach server. Please check your connection." "Red"
    Read-Host "`nPress Enter to exit"
    exit 1
}

$results.Latency = Test-Latency
$results.Download = Test-Download
$results.Upload = Test-Upload

Show-Results -Results $results
Send-Results -Results $results
Remove-Script
