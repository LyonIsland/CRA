param([int]$Port = 8875)
$ErrorActionPreference = 'Stop'
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$listener) { Write-Output 'No workshop is running.'; exit 0 }
$owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if ($owner.CommandLine -notmatch 'PiperIsaac.*workbench.py.*--task xr') { throw 'Refusing to stop a process outside this workshop.' }
Stop-Process -Id $owner.ProcessId
Write-Output 'Isaac XR workshop stopped.'
