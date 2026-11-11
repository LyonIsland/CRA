param(
 [string]$Goal,
 [string]$Task,
 [ValidateSet('collect','evaluate')][string]$Mode='evaluate',
 [string]$Policy="$PSScriptRoot\outputs\camera_only\policy.pt",
 [string]$Episode,
 [string]$Group,
 [int]$Seed=6000,
 [int]$Frames=1000
)
$ErrorActionPreference='Stop'
$runArgs=@("$PSScriptRoot\scripts\workbench.py",'--task','camera-only','--camera-mode',$Mode,'--seed',"$Seed",'--frames',"$Frames")
if($Task -and !$Goal){$runArgs+=@('--camera-task',$Task)}
elseif($Goal -and !$Task){$runArgs+=@('--camera-goal',$Goal)}
else{throw 'Supply either -Task (BRICKLAB task.json) or -Goal (photograph).'}
if($Mode -eq 'evaluate'){$runArgs+=@('--policy',$Policy)}
else{
 if(!$Episode -or !$Group){throw 'Collection requires -Episode and -Group.'}
 $runArgs+=@('--camera-episode',$Episode,'--camera-group',$Group)
}
& "$PSScriptRoot\.venv\Scripts\python.exe" @runArgs
if($LASTEXITCODE -ne 0){throw 'Camera-only task failed; inspect terminal output.'}
