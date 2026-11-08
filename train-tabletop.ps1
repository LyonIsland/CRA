param([int]$Samples=768,[int]$Epochs=140,[int]$Episodes=12,[string]$TrainingPython='C:\Users\Administrator\miniconda3\python.exe')
$ErrorActionPreference='Stop'
$env:OMNI_KIT_ACCEPT_EULA='YES'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$started=[DateTime]::UtcNow
& $python "$PSScriptRoot\scripts\workbench.py" --headless --task tabletop --tabletop-mode collect --samples $Samples --seed 67
if ($LASTEXITCODE -ne 0) { throw 'Wide-view image collection failed' }
if ((Get-Item "$PSScriptRoot\outputs\tabletop\localization.npz").LastWriteTimeUtc -lt $started) { throw 'Missing fresh image dataset' }
& $TrainingPython "$PSScriptRoot\scripts\train_vision.py" --directory tabletop --epochs $Epochs
if ($LASTEXITCODE -ne 0) { throw 'Wide-view training failed' }
& $python "$PSScriptRoot\scripts\workbench.py" --headless --task tabletop --episodes $Episodes --seed 7100
if ($LASTEXITCODE -ne 0) { throw 'Tabletop physical evaluation failed' }
& $python "$PSScriptRoot\scripts\workbench.py" --headless --task tabletop --tabletop-recovery
if ($LASTEXITCODE -ne 0) { throw 'Visual grasp recovery evaluation failed' }
& $python "$PSScriptRoot\scripts\workbench.py" --headless --task tabletop --tabletop-negative
if ($LASTEXITCODE -ne 0) { throw 'Negative evaluation failed' }
& $python "$PSScriptRoot\scripts\check_tabletop.py"
if ($LASTEXITCODE -ne 0) { throw 'Tabletop acceptance failed' }
