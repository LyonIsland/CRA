param([switch]$Check)
$ErrorActionPreference = 'Stop'
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
$env:TEMP = Join-Path $PSScriptRoot 'tmp'
$env:TMP = $env:TEMP
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'scripts\workbench.py'
if ($Check) {
    & $python $script --headless --check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $reportPath = Join-Path $PSScriptRoot 'outputs\smoke.json'
    if (!(Test-Path -LiteralPath $reportPath)) { throw 'No successful check report was produced. See outputs\failure.json and runtime logs.' }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'physics_and_viewport_render_passed') { throw 'Isaac Sim scene verification failed.' }
} else {
    & $python $script
}
exit 0
