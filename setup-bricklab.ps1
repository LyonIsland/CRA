param([Parameter(Mandatory=$true)][string]$Source)
$ErrorActionPreference='Stop'
$bootstrap=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $bootstrap "$PSScriptRoot\scripts\install_bricklab.py" $Source
if($LASTEXITCODE -ne 0){throw 'BRICKLAB source installation failed.'}
$python=Join-Path $PSScriptRoot '.tools\bricklab-venv\Scripts\python.exe'
if(!(Test-Path -LiteralPath $python)){
 & $bootstrap -m venv "$PSScriptRoot\.tools\bricklab-venv"
 if($LASTEXITCODE -ne 0){throw 'Could not create the isolated tools environment.'}
}
$bricklabTemp=Join-Path $PSScriptRoot 'tmp\bricklab-pip'
New-Item -ItemType Directory -Path $bricklabTemp -Force | Out-Null
$savedTemp=$env:TEMP
$savedTmp=$env:TMP
try{
 $env:TEMP=$bricklabTemp
 $env:TMP=$bricklabTemp
 & $python -m pip install -r "$PSScriptRoot\bricklab-requirements.txt"
 if($LASTEXITCODE -ne 0){throw 'BRICKLAB dependency installation failed.'}
}finally{$env:TEMP=$savedTemp;$env:TMP=$savedTmp}
Write-Output 'BRICKLAB is ready. Run .\start-bricklab.ps1.'
