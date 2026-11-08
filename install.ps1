$ErrorActionPreference = 'Stop'
$basePython = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$env:TEMP = Join-Path $PSScriptRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
if (!(Test-Path -LiteralPath $python)) {
    & $basePython -m venv "$PSScriptRoot\.venv"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 environment creation failed' }
}
& $python -m pip install --upgrade pip --no-cache-dir
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
$wheels = Get-ChildItem -LiteralPath "$PSScriptRoot\wheelhouse" -Filter *.whl -ErrorAction SilentlyContinue
if ($wheels.Count -ge 25) {
    & $python -m pip install --no-cache-dir --find-links "$PSScriptRoot\wheelhouse" 'isaacsim[all,extscache]==5.1.0'
} else {
    & $python -m pip install --no-cache-dir --use-feature=fast-deps 'isaacsim[all,extscache]==5.1.0' --extra-index-url https://pypi.nvidia.com
}
if ($LASTEXITCODE -ne 0) { throw 'Isaac Sim installation failed' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed' }
& $python "$PSScriptRoot\scripts\prepare_urdf.py"
if ($LASTEXITCODE -ne 0) { throw 'Prepare the pinned Piper assets before importing' }
Write-Output 'Isaac Sim packages installed. Run start.ps1 -Check to validate actual physics and RTX rendering.'
