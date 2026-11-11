param(
 [double]$Hours=7,
 [int]$Frames=512,
 [string]$TrainingRoot='D:\PiperCameraTraining',
 [string]$Tasks='D:\PiperCameraTraining\curriculum\tasks.json'
)
$ErrorActionPreference='Stop'
$python=Join-Path $TrainingRoot 'venv\Scripts\python.exe'
if(!(Test-Path -LiteralPath $python)){throw 'Create the isolated CUDA environment first; see CAMERA_ONLY.md.'}
if(!(Test-Path -LiteralPath $Tasks)){throw 'Prepare the camera curriculum first; see CAMERA_ONLY.md.'}
& $python -c "import torch; assert torch.cuda.is_available(), 'CUDA is required'; x=torch.randn(32,32,device='cuda'); print(torch.cuda.get_device_name(0), (x@x).sum().item())"
if($LASTEXITCODE -ne 0){throw 'CUDA compute preflight failed.'}
$runs=Join-Path $TrainingRoot 'runs'
New-Item -ItemType Directory -Path $runs -Force | Out-Null
# Refuse a second supervisor if a known run still has a matching live PID.
Get-ChildItem -LiteralPath $runs -Directory | ForEach-Object {
 $statusPath=Join-Path $_.FullName 'status.json'
 if(Test-Path -LiteralPath $statusPath){
  $status=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
  if($status.stage -notin @('completed','failed','stopped')){
   $existing=Get-CimInstance Win32_Process -Filter "ProcessId = $($status.pid)"
   if($existing -and $existing.CommandLine -like '*camera_overnight.py*'){throw "An overnight run is already active: $($_.FullName)"}
  }
 }
}
$run=Join-Path $runs (Get-Date -Format 'yyyyMMdd-HHmmss')
$stdout="$run.stdout.log"
$stderr="$run.stderr.log"
$arguments=@("`"$PSScriptRoot\scripts\camera_overnight.py`"",'--out',"`"$run`"",'--python',"`"$python`"",'--tasks',"`"$Tasks`"",'--hours',"$Hours",'--frames',"$Frames")
$process=Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$pointer=Join-Path $PSScriptRoot 'outputs\camera_only\overnight.json'
New-Item -ItemType Directory -Path (Split-Path $pointer) -Force | Out-Null
@{run=$run;launcher_pid=$process.Id;stdout=$stdout;stderr=$stderr;stop_file=(Join-Path $run 'STOP')} | ConvertTo-Json | Set-Content -LiteralPath $pointer -Encoding UTF8
Write-Output "Started training supervisor PID $($process.Id). Run: $run"
Write-Output "Status: $run\status.json"
Write-Output "Stop gracefully: New-Item -ItemType File -Path '$run\STOP'"
