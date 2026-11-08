param([int]$Layouts=2,[int]$Seed=3200,[switch]$PickPrefix)
$ErrorActionPreference='Stop'
$env:OMNI_KIT_ACCEPT_EULA='YES'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$started=[DateTime]::UtcNow
$scanArgs=@("$PSScriptRoot\scripts\workbench.py",'--headless','--task','assembly','--episodes',"$Layouts",'--seed',"$Seed")
if ($PickPrefix) { $scanArgs += '--assembly-pick-prefix' }
& $python @scanArgs
if ($LASTEXITCODE -ne 0) { throw 'Assembly RGB scan failed' }
$report=Get-Item "$PSScriptRoot\outputs\assembly\rgb-scan-check.json"
if ($report.LastWriteTimeUtc -lt $started) { throw 'No fresh RGB scan report' }
Write-Output 'RGB inventory snapshots saved. These do not constitute physical assembly success.'
