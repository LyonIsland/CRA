param([int]$Port=8877,[int]$Seed=4200,[switch]$NoBrowser,[switch]$FixedYaw)
$ErrorActionPreference='Stop'
$url="http://127.0.0.1:$Port"
$health=$null
try{$health=Invoke-RestMethod "$url/health" -TimeoutSec 2}catch{}
if($health -and !$health.state.assembly_live){throw 'The selected port belongs to a different workbench.'}
if(!$health){
 $env:OMNI_KIT_ACCEPT_EULA='YES'
 $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
 $runArgs=@("$PSScriptRoot\scripts\workbench.py",'--headless','--task','xr','--assembly-live','--port',"$Port",'--seed',"$Seed")
 if(!$FixedYaw){$runArgs+='--assembly-random-yaw'}
 $process=Start-Process "$PSScriptRoot\.venv\Scripts\pythonw.exe" -ArgumentList $runArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot\outputs\assembly-live-$stamp.log" -RedirectStandardError "$PSScriptRoot\outputs\assembly-live-$stamp-errors.log"
 $process.Id | Set-Content "$PSScriptRoot\outputs\assembly-live.pid"
 $deadline=[DateTime]::UtcNow.AddSeconds(120)
 while([DateTime]::UtcNow -lt $deadline){
  if($process.HasExited){throw "Assembly backend exited. See outputs\assembly-live-$stamp-errors.log"}
  try{$health=Invoke-RestMethod "$url/health" -TimeoutSec 2}catch{}
  if($health.state.assembly_live){break}
  Start-Sleep -Milliseconds 300
 }
 if(!$health.state.assembly_live){throw 'Assembly backend did not become ready.'}
}
if(!$NoBrowser){Start-Process "$url/assembly"}
Write-Output "Live concept assembly: $url/assembly. Contact-gated connector approximation; real snap-fit unvalidated."
