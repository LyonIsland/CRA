param([int]$Port=8878,[int]$Seed=5200,[int]$Extractions=6,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$url="http://127.0.0.1:$Port"
$health=$null
try{$health=Invoke-RestMethod "$url/health" -TimeoutSec 2}catch{}
if($health -and $health.state.assembly.scene_mode -ne 'physical_heap'){throw 'This port belongs to a different workbench.'}
if(!$health){
 $env:OMNI_KIT_ACCEPT_EULA='YES'
 $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
 $runArgs=@("$PSScriptRoot\scripts\workbench.py",'--headless','--task','xr','--assembly-clutter','--clutter-extractions',"$Extractions",'--port',"$Port",'--seed',"$Seed")
 $process=Start-Process "$PSScriptRoot\.venv\Scripts\pythonw.exe" -ArgumentList $runArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot\outputs\clutter-$stamp.log" -RedirectStandardError "$PSScriptRoot\outputs\clutter-$stamp-errors.log"
 $process.Id | Set-Content "$PSScriptRoot\outputs\clutter.pid"
 $deadline=[DateTime]::UtcNow.AddSeconds(150)
 while([DateTime]::UtcNow -lt $deadline){
  if($process.HasExited){throw "Clutter backend exited. See outputs\clutter-$stamp-errors.log"}
  try{$health=Invoke-RestMethod "$url/health" -TimeoutSec 2}catch{}
  if($health.state.assembly.scene_mode -eq 'physical_heap'){break}
  Start-Sleep -Milliseconds 300
 }
 if($health.state.assembly.scene_mode -ne 'physical_heap'){throw 'Clutter backend did not become ready.'}
}
if(!$NoBrowser){Start-Process "$url/assembly"}
Write-Output "Physical heap workbench: $url/assembly. Check reports for actual extraction/normalization/assembly status."
