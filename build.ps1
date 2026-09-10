$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location (Join-Path $root "app")
try {
    python -m pip install --disable-pip-version-check -q PySide6 pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    python (Join-Path $root 'tools/package_app.py')
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
    Write-Host "Built: $(Join-Path $root 'app\dist\tgm2p-trainer.exe')"
}
finally {
    Pop-Location
}
