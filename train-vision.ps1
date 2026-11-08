param([int]$Samples=256,[int]$Epochs=80,[int]$Episodes=8,[string]$TrainingPython='C:\Users\Administrator\miniconda3\python.exe')
$ErrorActionPreference='Stop'
$env:OMNI_KIT_ACCEPT_EULA='YES'
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$started=[DateTime]::UtcNow
& $python "$PSScriptRoot\scripts\workbench.py" --headless --task vision --samples $Samples
if ($LASTEXITCODE -ne 0) { throw 'Wrist RGB collection failed' }
$dataset=Get-Item "$PSScriptRoot\outputs\vision\localization.npz"
if ($dataset.LastWriteTimeUtc -lt $started) { throw 'No fresh image dataset' }
& $TrainingPython "$PSScriptRoot\scripts\train_vision.py" --epochs $Epochs
if ($LASTEXITCODE -ne 0) { throw 'Visual training failed' }
& $python "$PSScriptRoot\scripts\workbench.py" --headless --task vision --vision-mode evaluate --episodes $Episodes --seed 2000
if ($LASTEXITCODE -ne 0) { throw 'Visual evaluation failed' }
$report=Get-Item "$PSScriptRoot\outputs\vision\evaluation.json"
if ($report.LastWriteTimeUtc -lt $dataset.LastWriteTimeUtc) { throw 'No fresh visual evaluation' }
$result=Get-Content $report.FullName -Raw | ConvertFrom-Json
if ($result.successes -ne $Episodes -or $result.episodes.Count -ne $Episodes) { throw 'Visual task acceptance failed; see outputs\vision\evaluation.json' }
Write-Output "Visual grasp/place passed: $Episodes/$Episodes"
& $python "$PSScriptRoot\scripts\check_vision.py"
if ($LASTEXITCODE -ne 0) { throw 'Vision input/accuracy checks failed' }
