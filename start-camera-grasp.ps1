param(
 [string]$Task,
 [int]$Seed=51001,
 [int]$Frames=6500,
 [switch]$RandomOrientations,
 [switch]$NegativeOpen,
 [switch]$Headless
)
$ErrorActionPreference='Stop'
if(!$Task){
 $Task=Join-Path $PSScriptRoot 'outputs\camera_grasp\single-task\task.json'
 if(!(Test-Path -LiteralPath $Task)){
  & "$PSScriptRoot\.tools\bricklab-venv\Scripts\python.exe" "$PSScriptRoot\scripts\bricklab_prepare.py" "$PSScriptRoot\assets\manuals\bricklab_grasp_single\model.json" --output "$PSScriptRoot\outputs\camera_grasp\single-task"
  if($LASTEXITCODE -ne 0){throw 'BRICKLAB task preparation failed.'}
 }
}
$output=Join-Path $PSScriptRoot ('outputs\camera_grasp\runs\'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+$Seed)
$runArgs=@("$PSScriptRoot\scripts\workbench.py",'--task','camera-only','--camera-mode','grasp','--camera-task',$Task,'--camera-output',$output,'--seed',"$Seed",'--frames',"$Frames")
if(!$RandomOrientations){$runArgs+='--grasp-flat'}
if($Headless){$runArgs+='--headless'}
if($NegativeOpen){$runArgs+='--grasp-negative-open'}
Write-Output "Basic RGB-only simulation grasp. Report: $output\result.json"
& "$PSScriptRoot\.venv\Scripts\python.exe" @runArgs
if($LASTEXITCODE -ne 0){throw 'Simulator process failed.'}
Get-Content -LiteralPath (Join-Path $output 'result.json')
