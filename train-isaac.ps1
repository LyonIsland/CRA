param([int]$Episodes = 32,[int]$Epochs = 300,[string]$TrainingPython = 'C:\Users\Administrator\miniconda3\python.exe')
$ErrorActionPreference = 'Stop'
$env:OMNI_KIT_ACCEPT_EULA = 'YES'
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    & $python scripts\workbench.py --headless --task pick-place --episodes $Episodes
    if ($LASTEXITCODE -ne 0) { throw 'Demonstration collection failed' }
    & $TrainingPython scripts\train_bc.py --epochs $Epochs
    if ($LASTEXITCODE -ne 0) { throw 'Policy training failed' }
    & $python scripts\workbench.py --headless --task pick-place --policy outputs\policy.npz --episodes 20 --seed 1000
    if ($LASTEXITCODE -ne 0) { throw 'Policy evaluation failed' }
    & $python scripts\workbench.py --headless --task pick-place --baseline-open --episodes 3 --seed 5000
    if ($LASTEXITCODE -ne 0) { throw 'Negative control failed' }
    & $python scripts\workbench.py --headless --task pick-place --policy outputs\policy.npz --record --seed 1000 --result-name learned_demo
    if ($LASTEXITCODE -ne 0) { throw 'Video capture failed' }
    & $python scripts\check_capabilities.py
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance criteria failed' }
} finally { Pop-Location }
