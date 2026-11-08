param([switch]$Headless,[switch]$Record,[switch]$Expert,[int]$Seed = 1000,[int]$Episodes = 1)
$ErrorActionPreference = 'Stop'
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runArgs = @("$PSScriptRoot\scripts\workbench.py",'--task','pick-place','--seed',"$Seed",'--episodes',"$Episodes",'--result-name','last_task')
if ($Headless) { $runArgs += '--headless' }
if ($Record) { $runArgs += '--record' }
if (!$Expert) { $runArgs += @('--policy',"$PSScriptRoot\outputs\policy.npz") }
$taskStart = [DateTime]::UtcNow
& $python @runArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$report = 'last_task.json'
if (!(Test-Path -LiteralPath "$PSScriptRoot\outputs\$report")) { throw 'No task result was written.' }
if ((Get-Item -LiteralPath "$PSScriptRoot\outputs\$report").LastWriteTimeUtc -lt $taskStart) { throw 'The task did not produce a fresh result.' }
