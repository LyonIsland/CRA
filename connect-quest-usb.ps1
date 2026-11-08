param([string]$Serial = '',[int]$Port = 8875)
$ErrorActionPreference = 'Stop'
$adb = Join-Path $PSScriptRoot 'tools\platform-tools\adb.exe'
if (!(Test-Path -LiteralPath $adb)) { throw 'Install Google platform-tools first: .venv\Scripts\python.exe scripts\install_adb.py' }
$health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
if ($health.physics -ne 'Isaac Sim / PhysX') { throw 'Start the Isaac XR workbench before connecting the headset.' }
$devices = & $adb devices
$authorized = @($devices | Where-Object { $_ -match '^\S+\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
if (!$Serial) {
    if ($authorized.Count -ne 1) { throw 'Connect one Quest with Developer Mode enabled and accept USB debugging in the headset, or specify -Serial.' }
    $Serial = $authorized[0]
}
if ($authorized -notcontains $Serial) { throw 'The selected device is not authorized for USB debugging.' }
$manufacturer = & $adb -s $Serial shell getprop ro.product.manufacturer
$model = & $adb -s $Serial shell getprop ro.product.model
if (("$manufacturer $model") -notmatch 'Oculus|Meta|Quest') { throw 'Selected Android device was not identified as a Meta Quest.' }
& $adb -s $Serial reverse "tcp:$Port" "tcp:$Port"
if ($LASTEXITCODE -ne 0) { throw 'USB port forwarding failed.' }
& $adb -s $Serial shell am start -a android.intent.action.VIEW -d "http://localhost:$Port/"
if ($LASTEXITCODE -ne 0) { throw 'Could not open the Quest browser.' }
Write-Output "Quest browser opened at http://localhost:$Port/. Select Enter VR inside the headset. Actual tracking must be checked on the device."
