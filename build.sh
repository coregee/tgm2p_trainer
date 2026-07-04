#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root/app"

python3 -m pip install --disable-pip-version-check -q PySide6 pyinstaller
python3 -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name tgm2p-trainer \
    --paths . \
    --collect-submodules tgmtrainer \
    --add-data "$root/plugin/addresses.json:." \
    run_app.py

echo "Built: $root/app/dist/tgm2p-trainer"
if [ -d "$root/app/dist/tgm2p-trainer.app" ]; then
    echo "Built: $root/app/dist/tgm2p-trainer.app"
fi
