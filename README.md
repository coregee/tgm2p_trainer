# TGM2P Trainer

Bridge plugin + companion app for MAME to enable various modifiers for playing Tetris The Absolute The Grand Master 2 Plus.

## How to use

1. Download the [latest release](https://github.com/coregee/tgm2p_trainer/releases) for your platform:
   - `tgm2p-trainer-windows-x64.zip`
   - `tgm2p-trainer-linux-x64.tar.gz`
   - `tgm2p-trainer-macos-arm64.zip` (Apple Silicon; Intel Macs: [build from source](#building-from-source))
2. Move the `tgm2p-trainer` folder from the archive into your MAME plugins directory:
   - **Windows:** `<your MAME folder>\plugins\`
   - **Linux / macOS:** `~/.mame/plugins/` (create it if needed), or the `plugins` folder next to your MAME binary
3. Run the trainer app (`tgm2p-trainer.exe` / `tgm2p-trainer` / `tgm2p-trainer.app`), click the 'Config' button, and select your MAME executable in the file browser.
   - **macOS:** the app is unsigned — the first time, right-click → Open, or run `xattr -d com.apple.quarantine tgm2p-trainer.app`.
   - **Linux:** if you downloaded the bare binary, make sure it is executable (`chmod +x tgm2p-trainer`).
4. Click "Launch MAME" to launch an instance of TGM2P with the trainer attached.

## Building from source

Requires Python 3.10+.

- **Windows:** `.\build.ps1`
- **Linux / macOS:** `bash build.sh`

The executable is written to `app/dist/`.

To run without building:

```sh
pip install -r app/requirements.txt
python app/run_app.py
```

## Notes

Please do not use this to cheat. I will hate you.
Use this to suffer, like Mihara-san intended.
