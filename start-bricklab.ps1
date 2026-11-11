param([int]$Port=18110,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$python=Join-Path $PSScriptRoot '.tools\bricklab-venv\Scripts\python.exe'
if(!(Test-Path -LiteralPath $python)){throw 'Run setup-bricklab.ps1 -Source <ZIP-or-directory> first.'}
$url="http://127.0.0.1:$Port"
$health=$null
try{$health=Invoke-RestMethod "$url/api/health" -TimeoutSec 2}catch{}
if($health -and $health.service -ne 'piper-bricklab-local'){throw 'Selected port belongs to another service.'}
if(!$health){
 $out=Join-Path $PSScriptRoot 'outputs\bricklab'
 New-Item -ItemType Directory -Path $out -Force | Out-Null
 $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
 $process=Start-Process $python -ArgumentList @("`"$PSScriptRoot\scripts\bricklab_server.py`"",'--port',"$Port") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$out\server-$stamp.log" -RedirectStandardError "$out\server-$stamp-errors.log"
 $process.Id | Set-Content "$out\server.pid"
 for($attempt=0;$attempt -lt 40;$attempt++){
  if($process.HasExited){throw "BRICKLAB stopped; see $out\server-$stamp-errors.log"}
  try{$health=Invoke-RestMethod "$url/api/health" -TimeoutSec 2}catch{}
  if($health.service -eq 'piper-bricklab-local'){break}
  Start-Sleep -Milliseconds 250
 }
 if($health.service -ne 'piper-bricklab-local'){throw 'BRICKLAB did not become ready.'}
}
if(!$NoBrowser){Start-Process $url}
Write-Output "BRICKLAB training platform: $url"
