#Requires -Version 7.0
param(
    [ValidateSet('Start', 'Stop', 'Env', 'Status')][string]$Action = 'Start'
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$runtimePath = Join-Path $projectRoot '.runtime\jaeger'
$exePath = Join-Path $runtimePath 'jaeger.exe'
$statePath = Join-Path $runtimePath 'process.json'
$manifestPath = Join-Path $runtimePath 'install.json'
$configPath = Join-Path $projectRoot 'examples\observability\jaeger.yaml'
$queryUrl = 'http://127.0.0.1:16686'
$ports = @(4317, 4318, 16685, 16686)

function Assert-SafePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Target is outside the project.'
    }
    $current = $full
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Project runtime path contains a reparse point.'
            }
        }
        $current = Split-Path -Parent $current
    }
}

function Get-OwnedProcess {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    Assert-SafePath $statePath
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if (-not [string]::Equals([string]$state.executable, $exePath, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Saved executable differs from the project Jaeger path; refusing to act.'
    }
    $owned = Get-Process -Id ([int]$state.process_id) -ErrorAction SilentlyContinue
    if ($null -eq $owned) { return $null }
    if (-not [string]::Equals($owned.Path, $exePath, [StringComparison]::OrdinalIgnoreCase) -or
        $owned.StartTime.ToUniversalTime().Ticks.ToString() -ne [string]$state.start_time_utc_ticks) {
        throw 'PID ownership does not match executable and start time; refusing to act.'
    }
    return $owned
}

function Get-ListenerState([int]$ProcessId) {
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -eq $ProcessId })
    if (@($listeners | Where-Object { -not [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($_.LocalAddress)) }).Count -gt 0) {
        throw 'Jaeger has a non-loopback listener.'
    }
    return $listeners
}

function Wait-Ready([Diagnostics.Process]$Owned) {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $Owned.Refresh()
        if ($Owned.HasExited) { throw 'Jaeger exited; inspect .runtime/jaeger stderr.log.' }
        $listeners = @(Get-ListenerState $Owned.Id)
        $bound = @($listeners | Select-Object -ExpandProperty LocalPort -Unique)
        if (@($ports | Where-Object { $_ -notin $bound }).Count -eq 0) {
            try {
                # Jaeger 2.21 removed /api/services; the native services API is v3.
                $response = Invoke-WebRequest -Uri "$queryUrl/api/v3/services" -TimeoutSec 2 -UseBasicParsing -NoProxy
                if ($response.StatusCode -eq 200) { return }
            } catch { }
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Jaeger API did not become ready within 30 seconds.'
}

if ($Action -eq 'Env') {
    $env:ANLAN_OTLP_ENDPOINT = 'http://127.0.0.1:4318/v1/traces'
    $env:ANLAN_JAEGER_QUERY_URL = $queryUrl
    Write-Output 'Jaeger environment ready for this PowerShell session.'
    return
}
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $mutexName = 'Local\AnlanJaeger-' + [BitConverter]::ToString(
        $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Replace('-', '')
} finally { $sha.Dispose() }
$mutex = [Threading.Mutex]::new($false, $mutexName)
$acquired = $false
try {
    try { $acquired = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw 'Another Jaeger lifecycle action is in progress; retry shortly.' }
Assert-SafePath $runtimePath
Assert-SafePath $exePath
Assert-SafePath $statePath
$owned = Get-OwnedProcess
if ($Action -eq 'Stop') {
    if ($null -eq $owned) {
        Write-Output 'Project Jaeger is not running.'
        return
    }
    # Recheck identity immediately before stopping; never stop a port owner by PID alone.
    $owned = Get-OwnedProcess
    $owned.Kill()
    if (-not $owned.WaitForExit(10000)) { throw 'Jaeger did not stop within 10 seconds.' }
    Remove-Item -LiteralPath $statePath
    Write-Output 'Project Jaeger stopped.'
    return
}
if ($Action -eq 'Status') {
    if ($null -eq $owned) {
        Write-Output 'Project Jaeger is not running.'
        return
    }
    Wait-Ready $owned
    [pscustomobject]@{ process_id = $owned.Id; version = '2.21.0'; query_url = $queryUrl; ready = $true } |
        ConvertTo-Json -Compress
    return
}
if ($null -ne $owned) {
    Wait-Ready $owned
    Write-Output "Project Jaeger already running (PID $($owned.Id)): $queryUrl"
    return
}
foreach ($file in @($exePath, $manifestPath, $configPath)) {
    Assert-SafePath $file
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw 'Jaeger runtime/config missing. Run python scripts/install_jaeger.py first.'
    }
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.version -ne '2.21.0' -or $manifest.archive_sha256 -ne '197c4b42aba6983b3d9cbca3577a0e14191bcb9431fde1b6661471b6fece39fc' -or
    (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.executable_sha256) {
    throw 'Jaeger executable or manifest integrity check failed.'
}
$conflicts = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports })
if ($conflicts.Count -gt 0) { throw 'A required Jaeger port is occupied; no process was stopped.' }
$stdout = Join-Path $runtimePath 'stdout.log'
$stderr = Join-Path $runtimePath 'stderr.log'
Assert-SafePath $stdout
Assert-SafePath $stderr
$owned = Start-Process -FilePath $exePath -ArgumentList @('--config', "`"$configPath`"") `
    -WorkingDirectory $runtimePath -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$identityDeadline = [DateTime]::UtcNow.AddSeconds(5)
$startTicks = $owned.StartTime.ToUniversalTime().Ticks.ToString()
do {
    # Start-Process may briefly expose a null Path while Windows initializes the image.
    $observed = Get-Process -Id $owned.Id -ErrorAction SilentlyContinue
    $observedPath = if ($null -ne $observed) { [string]$observed.Path } else { '' }
    $observedTicks = if ($null -ne $observed) { $observed.StartTime.ToUniversalTime().Ticks.ToString() } else { '' }
    if ([string]::Equals($observedPath, $exePath, [StringComparison]::OrdinalIgnoreCase) -and $observedTicks -eq $startTicks) { break }
    Start-Sleep -Milliseconds 50
} while ([DateTime]::UtcNow -lt $identityDeadline)
if (-not [string]::Equals($observedPath, $exePath, [StringComparison]::OrdinalIgnoreCase) -or $observedTicks -ne $startTicks) {
    throw 'Could not verify the started Jaeger process identity.'
}
$owned = $observed
[pscustomobject]@{
    process_id = $owned.Id
    executable = $observedPath
    start_time_utc_ticks = $observedTicks
} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
try {
    Wait-Ready $owned
} catch {
    $failure = $_
    $verified = Get-OwnedProcess
    if ($null -ne $verified) {
        $verified.Kill()
        $verified.WaitForExit(10000) | Out-Null
    }
    throw $failure
}
Write-Output "Project Jaeger ready (PID $($owned.Id)): $queryUrl"
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
