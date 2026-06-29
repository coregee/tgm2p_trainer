$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location (Join-Path $root "app")
try {
    python -m pip install --disable-pip-version-check -q PySide6 pyinstaller
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name TGM2Trainer `
        --paths . `
        --collect-submodules tgmtrainer `
        --add-data "$(Join-Path $root 'plugin\addresses.json');." `
        run_app.py
    Write-Host "Built: $(Join-Path $root 'app\dist\tgm2p-trainer.exe')"
}
finally {
    Pop-Location
}
