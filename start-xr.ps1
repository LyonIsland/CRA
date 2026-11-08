param([int]$Port = 8875)
$ErrorActionPreference = 'Stop'
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$runArgs = @("$PSScriptRoot\scripts\workbench.py",'--headless','--task','xr','--port',"$Port",'--seed','1000')
if (Test-Path -LiteralPath "$PSScriptRoot\outputs\tabletop\acceptance.json") {
    $accepted=Get-Content "$PSScriptRoot\outputs\tabletop\acceptance.json" -Raw | ConvertFrom-Json
    $modelHash=(Get-FileHash "$PSScriptRoot\outputs\tabletop\localizer.pt" -Algorithm SHA256).Hash
    if ($modelHash -ne $accepted.model_sha256) { throw 'Tabletop model changed after validation. Run train-tabletop.ps1.' }
    $runArgs += '--tabletop'
}
elseif (Test-Path -LiteralPath "$PSScriptRoot\outputs\vision\localizer.pt") { $runArgs += '--wrist-vision' }
& "$PSScriptRoot\.venv\Scripts\python.exe" @runArgs
exit $LASTEXITCODE
