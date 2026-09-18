param(
    [ValidateSet('Start', 'Stop', 'Env', 'Status')][string]$Action = 'Start',
    [string]$PgBin = '',
    [int]$Port = 55432
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.runtime\postgres-dev'
$asciiRuntime = Join-Path $env:LOCALAPPDATA 'Anlan2Runtime\postgres-17.11'
$dataPath = Join-Path $asciiRuntime 'anlan2-data'
$configPath = Join-Path $runtimePath 'connection.json'
if (-not $PgBin) { $PgBin = Join-Path $asciiRuntime 'pgsql\bin' }
$ctl = Join-Path $PgBin 'pg_ctl.exe'
if (-not (Test-Path -LiteralPath $ctl)) {
    throw 'PostgreSQL 17 binaries missing. See README setup instructions or supply -PgBin.'
}
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
if (Test-Path -LiteralPath $configPath) {
    $devConfig = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    if ($devConfig.port -ne $Port) { throw 'Port differs from existing project dev cluster.' }
} elseif ($Action -eq 'Start') {
    $devConfig = [pscustomobject]@{ port = $Port; password = [guid]::NewGuid().ToString('N') }
    $devConfig | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
} else { throw 'Project dev cluster is not initialized.' }

function Invoke-HiddenPg([string]$Executable, [string[]]$PgArguments, [string]$LogName) {
    $process = Start-Process -FilePath $Executable -ArgumentList $PgArguments -WindowStyle Hidden `
        -PassThru -RedirectStandardOutput (Join-Path $runtimePath "$LogName.out.log") `
        -RedirectStandardError (Join-Path $runtimePath "$LogName.err.log")
    # Wait only for pg_ctl itself; Start-Process -Wait also waits for its long-lived server child.
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "PostgreSQL $LogName failed; inspect local .runtime logs." }
}

if ($Action -eq 'Stop') {
    Invoke-HiddenPg $ctl @('-D', "`"$dataPath`"", '-w', '-t', '30', 'stop', '-m', 'fast') 'stop'
    Write-Output 'Project PostgreSQL stopped. Existing system service unchanged.'
    return
}
if ($Action -eq 'Status') {
    & $ctl -D $dataPath status
    return
}
if ($Action -eq 'Start') {
    if (-not (Test-Path -LiteralPath (Join-Path $dataPath 'PG_VERSION'))) {
        $passwordFile = Join-Path $runtimePath 'init-password.tmp'
        [IO.File]::WriteAllText($passwordFile, $devConfig.password)
        try {
            Invoke-HiddenPg (Join-Path $PgBin 'initdb.exe') @(
                '-D', "`"$dataPath`"", '-U', 'anlan_dev', '--encoding=UTF8', '--locale=C',
                '--auth=scram-sha-256', "--pwfile=`"$passwordFile`""
            ) 'initdb'
        } finally { Remove-Item -LiteralPath $passwordFile -ErrorAction SilentlyContinue }
    }
    & $ctl -D $dataPath status *> $null
    if ($LASTEXITCODE -ne 0) {
        Invoke-HiddenPg $ctl @(
            '-D', "`"$dataPath`"", '-l', "`"$(Join-Path $runtimePath 'server.log')`"",
            '-o', "`"-h 127.0.0.1 -p $Port`"", '-w', '-t', '30', 'start'
        ) 'start'
    }
    $previousPassword = $env:PGPASSWORD
    try {
        $env:PGPASSWORD = $devConfig.password
        $psql = Join-Path $PgBin 'psql.exe'
        $exists = & $psql -w -h 127.0.0.1 -p $Port -U anlan_dev -d postgres -tAc `
            "SELECT 1 FROM pg_database WHERE datname = 'anlan_dev'"
        if ($LASTEXITCODE -ne 0) { throw 'Project PostgreSQL connection failed.' }
        if ($exists -ne '1') {
            & $psql -w -h 127.0.0.1 -p $Port -U anlan_dev -d postgres -c 'CREATE DATABASE anlan_dev' | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not create project database.' }
        }
    } finally { $env:PGPASSWORD = $previousPassword }
}
$env:ANLAN_DATABASE_URL = "postgresql://anlan_dev:$($devConfig.password)@127.0.0.1:$Port/anlan_dev"
$env:ANLAN_TEST_DATABASE_URL = $env:ANLAN_DATABASE_URL
Write-Output "Project PostgreSQL environment ready: 127.0.0.1:$Port/anlan_dev (credential hidden)."
