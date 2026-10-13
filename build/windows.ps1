# Build the Windows release: dist\release\PivotBenchmark-<version>-windows-x64.zip + SHA256SUMS.txt
# Run from the repository root inside a Python environment that has requirements.txt installed:
#   powershell -ExecutionPolicy Bypass -File build\windows.ps1
# Steps: PyInstaller bundle (build\pivot_benchmark.spec) -> README-FIRST, LICENSE, THIRD-PARTY-NOTICES
# into the folder -> zip -> SHA-256. llama.cpp is NOT included; the app explains how to get it.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Version = python -c "from mbench.version import VERSION; print(VERSION)"
$Name = "PivotBenchmark-$Version-windows-x64"
Write-Host "== Pivot Benchmark $Version -> $Name.zip"

pip install -q pyinstaller pip-licenses
Remove-Item -Recurse -Force build\pyi, dist\PivotBenchmark -ErrorAction SilentlyContinue
pyinstaller --noconfirm --workpath build\pyi --distpath dist build\pivot_benchmark.spec | Out-Null
if (-not (Test-Path dist\PivotBenchmark\PivotBenchmark.exe)) { throw "PyInstaller produced no executable" }

(Get-Content build\README-FIRST.txt -Raw).Replace("__VERSION__", $Version) |
    Set-Content dist\PivotBenchmark\README-FIRST.txt -NoNewline
if (Test-Path LICENSE.md) { Copy-Item LICENSE.md dist\PivotBenchmark\LICENSE.md }
if (Test-Path NOTICE) { Copy-Item NOTICE dist\PivotBenchmark\NOTICE.txt }
pip-licenses --format=plain-vertical --with-license-file --no-license-path --with-urls `
    --ignore-packages pip setuptools wheel pip-licenses pyinstaller pyinstaller-hooks-contrib `
    | Set-Content dist\PivotBenchmark\THIRD-PARTY-NOTICES.txt

New-Item -ItemType Directory -Force dist\release | Out-Null
Remove-Item dist\release\$Name.zip -ErrorAction SilentlyContinue
Compress-Archive -Path dist\PivotBenchmark -DestinationPath dist\release\$Name.zip -CompressionLevel Optimal
$Hash = (Get-FileHash dist\release\$Name.zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::AppendAllText("$Root\dist\release\SHA256SUMS.txt", "$Hash  $Name.zip`n")   # LF, so sha256sum -c reads it
Get-Item dist\release\$Name.zip | Format-Table Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
Write-Host "ZIP DONE"
