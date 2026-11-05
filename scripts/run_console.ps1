<#
.SYNOPSIS
  Start the Ghost Data Console (dashboard plus live analysis) with one command.

.DESCRIPTION
  Needs Docker Desktop and the participant dataset in .\dataset. It
    1. creates .env from .env.example when missing and adds a Neo4j password if there is none,
    2. starts Neo4j and the console container (builds any missing data and page file),
    3. waits until the console answers, then opens it in the browser.
  Nothing is sent anywhere. The console listens on 127.0.0.1 only.

.PARAMETER Port      Host port for the console (default 8765).
.PARAMETER Refresh   Rebuild dashboard_data.json and the stored insight data, then serve.
.PARAMETER NoBrowser Do not open the browser.
.PARAMETER Stop      Stop the console and Neo4j, then exit.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_console.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$Refresh,
    [switch]$NoBrowser,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step([string]$message) { Write-Host "==> $message" -ForegroundColor Cyan }

# Run a native command without PowerShell 5.1 turning its stderr into a terminating error.
function Invoke-Native([scriptblock]$command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $command } finally { $ErrorActionPreference = $previous }
}

if ($Stop) {
    Invoke-Native { docker compose --profile console down }
    exit 0
}

# 1. prerequisites
Invoke-Native { docker info *> $null }
if ($LASTEXITCODE -ne 0) {
    throw 'Docker is not running. Start Docker Desktop, wait until it says it is running, then run this again.'
}
if (-not (Test-Path (Join-Path $root 'dataset\deletion_requests.csv'))) {
    throw "The participant dataset is missing. Copy the HackerRank dataset so that $root\dataset\deletion_requests.csv exists."
}

# 2. .env: create it, and give Neo4j a password when there is none (the file is gitignored)
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root '.env.example') $envFile
    Step 'created .env from .env.example'
}
$text = [System.IO.File]::ReadAllText($envFile)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$add = ''
if ($text -notmatch '(?m)^NEO4J_URI=') { $add += "NEO4J_URI=bolt://neo4j:7687`n" }
if ($text -notmatch '(?m)^NEO4J_USER=') { $add += "NEO4J_USER=neo4j`n" }
if ($text -notmatch '(?m)^NEO4J_PASSWORD=') {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', ''
    $add += "NEO4J_PASSWORD=$password`n"
    Step 'generated a local Neo4j password in .env'
}
elseif ($text -notmatch '(?m)^NEO4J_PASSWORD=\S{8,}') {
    throw 'NEO4J_PASSWORD in .env must be at least 8 characters. Edit it or delete the line and run this again.'
}
if ($add) {
    $prefix = ''
    if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $prefix = "`n" }
    [System.IO.File]::AppendAllText($envFile, $prefix + $add, $utf8)
}
if ($text -notmatch '(?m)^SLAM_CONSOLE_PROVIDER=') {
    Write-Host '    Live runs explain cases with rules. For model-written explanations add GROQ_API_KEYS and SLAM_API_MAX_CALLS,' -ForegroundColor DarkGray
    Write-Host '    then SLAM_CONSOLE_PROVIDER=groq and SLAM_CONSOLE_MODEL=<model id> (see .env.example).' -ForegroundColor DarkGray
}

# 3. start Neo4j and the console
$env:SLAM_CONSOLE_PORT = "$Port"
$env:SLAM_CONSOLE_REFRESH = $(if ($Refresh) { '1' } else { '' })
Invoke-Native { docker rm -f slam-live *> $null }   # a console started by hand with an older command
Step 'starting Neo4j'
Invoke-Native { docker compose --profile console up -d neo4j }
if ($LASTEXITCODE -ne 0) { throw 'Could not start Neo4j. Run: docker compose --profile console logs neo4j' }
Step 'starting the console (the first start builds the image and audits all 518 cases, about a minute)'
Invoke-Native { docker compose --profile console up -d --force-recreate console }
if ($LASTEXITCODE -ne 0) { throw 'Could not start the console. Run: docker compose --profile console logs console' }

# 4. wait until it answers
$url = "http://127.0.0.1:$Port"
$ready = $null
$deadline = (Get-Date).AddMinutes(8)
while ((Get-Date) -lt $deadline) {
    try {
        $answer = Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 3
        if ($answer.live) { $ready = $answer; break }
    }
    catch { }
    $state = ''
    Invoke-Native { $script:state = (docker inspect -f '{{.State.Status}}' slam-console-1 2>$null) }
    if ($state -eq 'exited' -or $state -eq 'dead') {
        Invoke-Native { docker compose --profile console logs --tail 25 console }
        throw 'The console stopped while starting. The last log lines are above.'
    }
    Start-Sleep -Seconds 3
}
if (-not $ready) { throw "The console did not answer within 8 minutes. Run: docker compose --profile console logs console" }

# 5. report
$neo = if ($ready.neo4j.reachable) { 'reachable' } else { 'not reachable, NetworkX answers the graph queries' }
$model = if ($ready.max_llm_cases -gt 0) { $ready.model.name } else { 'none (rules only)' }
Write-Host ''
Write-Host "Console ready: $url" -ForegroundColor Green
Write-Host "  Neo4j : $neo"
Write-Host "  Model : $model"
Write-Host '  Stop  : powershell -ExecutionPolicy Bypass -File scripts\run_console.ps1 -Stop'
Write-Host '  Log   : docker compose --profile console logs -f console'
if (-not $NoBrowser) { Start-Process $url }
