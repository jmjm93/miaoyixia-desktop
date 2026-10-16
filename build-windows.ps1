$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.cmd first.' }
& $python -m pip install -r requirements-build.txt
if ($LASTEXITCODE) { throw 'Build dependency installation failed.' }
& $python tools/prepare_release.py
if ($LASTEXITCODE) { throw 'Release asset preparation failed.' }
& $python -m PyInstaller --noconfirm miaoyixia.spec
if ($LASTEXITCODE) { throw 'Executable build failed.' }
$report = Join-Path $PSScriptRoot 'build\self-test.json'
$previousPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = 'offscreen'
$process = Start-Process -FilePath (Join-Path $PSScriptRoot 'dist\Miaoyixia\Miaoyixia.exe') -ArgumentList @('--self-test', '--report', ('"' + $report + '"')) -WindowStyle Hidden -Wait -PassThru
$env:QT_QPA_PLATFORM = $previousPlatform
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'Packaged self-test failed.' }
$result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
if (-not $result.ok) { throw 'Packaged self-test did not pass.' }
Copy-Item -LiteralPath README.md, THIRD_PARTY_NOTICES.md -Destination dist\Miaoyixia
Compress-Archive -Path dist\Miaoyixia -DestinationPath dist\Miaoyixia-windows-x64.zip -Force
Get-FileHash -Algorithm SHA256 -LiteralPath dist\Miaoyixia-windows-x64.zip | Format-List
Write-Host 'Ready: dist\Miaoyixia-windows-x64.zip'
