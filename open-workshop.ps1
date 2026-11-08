param([int]$Port = 8875,[switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$url = "http://127.0.0.1:$Port"
$health = $null
try { $health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2 } catch { }
if ($health -and $health.physics -ne 'Isaac Sim / PhysX') { throw 'The selected port belongs to another service.' }
if (!$health) {
    $env:OMNI_KIT_ACCEPT_EULA = 'YES'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backendArgs = @("$PSScriptRoot\scripts\workbench.py",'--headless','--task','xr','--seed','1000','--port',"$Port")
    if (Test-Path -LiteralPath "$PSScriptRoot\outputs\tabletop\acceptance.json") {
        $accepted=Get-Content "$PSScriptRoot\outputs\tabletop\acceptance.json" -Raw | ConvertFrom-Json
        $modelHash=(Get-FileHash "$PSScriptRoot\outputs\tabletop\localizer.pt" -Algorithm SHA256).Hash
        if ($modelHash -ne $accepted.model_sha256) { throw 'Tabletop model changed after validation. Run train-tabletop.ps1.' }
        $backendArgs += '--tabletop'
    }
    elseif (Test-Path -LiteralPath "$PSScriptRoot\outputs\vision\localizer.pt") { $backendArgs += '--wrist-vision' }
    $backend = Start-Process -FilePath "$PSScriptRoot\.venv\Scripts\pythonw.exe" -ArgumentList $backendArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot\outputs\xr-$stamp.log" -RedirectStandardError "$PSScriptRoot\outputs\xr-$stamp-errors.log"
    $backend.Id | Set-Content -LiteralPath "$PSScriptRoot\outputs\xr-backend.pid"
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($backend.HasExited) { throw "Isaac XR backend stopped. See outputs\xr-$stamp-errors.log" }
        try { $health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2 } catch { }
        if ($health -and $health.state) { break }
        Start-Sleep -Milliseconds 300
    }
    if (!$health -or !$health.state) { throw 'Isaac XR backend did not become ready in time.' }
}
if (!$NoBrowser) { Start-Process $url }
Write-Output "Workshop: $url. Use page controls to start/resume. Keep one control tab open."
