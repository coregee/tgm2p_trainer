# TGM2+ Trainer

A native SH-2 trainer and companion desktop app for MAME's `tgm2p`.

The game reads persistent trainer parameters through assembly patches at its
normal gravity, timing, progression and rendering routines. The Python app sends
settings when changed; the Lua plugin handles installation, communication and
telemetry. There are **no per-frame freezes, write taps, or Lua field scans**.
MAME's dynamic recompiler stays enabled.

## Run

Requires Python 3.10+, PySide6 6.6+, and your own MAME installation and TGM2+ ROM.
Development and live integration tests use MAME 0.289 on Windows.

```powershell
python -m pip install -r app/requirements.txt
python app/run_app.py
```

Choose your MAME executable, then **Launch MAME**. The app stages its matching
plugin automatically, without replacing your installed plugins. Wait for
**Ready — settings applied**. A socket connection alone does not mean the game
has finished booting or the patches passed validation.

The VS Code launch configurations run the app with the workspace bridge, MAME
alone with the recompiler, or an interpreter comparison. The executable path is
prompted. Tasks and debugger launches use the workspace `.venv` directly. If it
does not exist, create it with `python -m venv .venv`, then install
`app/requirements.txt` using that environment's Python.

## Controls

Each player has independent controls. Checked controls override the game;
unchecking returns the decision to the original game logic. Profiles store both
players and the shared music choice. Reconnecting publishes the complete desired
snapshot, including releases made while disconnected.

Reset Player and shared Music sit above the player tabs. Each player's controls
are grouped into Timing (preset, gravity, frame timings), Modifiers (visibility,
BIG, ITEM, ghost), and Progression (freeze, level, section, grade, M-roll,
torikan). Reset Player always targets the selected tab.

Numeric overrides pair an exact-entry field on the left with a slider on the
right. Timing controls use displayed frame counts throughout, including ARE's
minimum of 3 frames. Visibility and other categorical choices retain selectors.

- **Gravity:** override base falling speed while preserving soft drop, sonic
  drop and the game's forced-20G rules.
  Half the slider covers 0–1G and half covers 1–20G. Values use 1/256G steps
  to 1G, 4/256G steps from 1G to 5G, and quarter-G steps above 5G.
  Mixed fractions display as `1 + 4/256 G`. Enter a fraction such as `128/256`
  or a G value such as `0.5` in the field to the left. Profiles from the previous
  effective-gravity control retain their values and now apply to base gravity.
- **ARE, line ARE, line clear, lock and DAS:** independent durations/thresholds.
  Timers continue to count normally. ARE, line ARE and lock changes apply at their
  next load event, rather than altering a running countdown. Displayed ARE/line
  ARE/DAS include the conventional two-frame offset.
- **Stack visibility:** choose Visible, Invisible (M-roll lock flash and brief
  fade), or Fading (the normal roll's 300-frame countdown, about 5 seconds).
  New locks use the game's own cell flags and renderer countdowns. Changing to
  Fading affects new locks; existing cells retain their timers. Invisible hides
  an ordinary existing stack immediately. End-of-game reveal follows the game.
- **Ghost:** override the visibility argument passed to the piece renderer.
- **Freeze level:** keep the current level at progression events. Explicit
  level and section jumps update the frozen target; uncheck to resume progression.
- **Death torikan:** bypass the time-limit decision.
- **M-roll qualification:** supply satisfied qualification bits at their readers.
  Actual grades and section times remain genuine game state; this is a deliberate
  replacement for the old "forge S9 and qualification RAM" recipe.
- **BIG / ITEM mode:** persistent practice toggles. BIG controls the queued
  piece's `0x0200` attribute in every mode, including the opening preview, taking
  effect at the next handoff. Its dropdown selects **TGM1** (2/4/4/4 levels for
  single/double/triple/tetris clears, 10-column movement), **TGM2** (2/4/4/4 levels,
  5-column movement), or **TAP** (1/2/3/4 levels, 5-column movement; the default).
  Ten-column movement steps one ordinary cell; five-column movement steps two
  and uses TAP's BIG spawn alignment. A mid-piece toggle or variant change
  changes the next piece; the active piece keeps its size, grid and clear rule.
  Older profiles with BIG enabled select TGM2. The BIG hotkey remembers the
  current dropdown selection when toggled off/on; holding it releases ownership.
  ITEM controls its mode bit at queued-piece events. Unchecking forces off.
- **Music:** override the shared director's scene choice and retain its transition
  handling. Both players share one soundtrack.

One-time practice actions jump to any level 000–999, move to the previous/next
section start, set internal grade, or restart a player. Level jumps update both
section index and section count; they do not reconstruct section history or
reset score/time. In Doubles, visibility controls the shared field: Player 1
takes precedence when both players have a visibility override.

All overrides are suspended during title screens, attract demos and service
mode. Settings stay selected and resume automatically during gameplay. The
native hooks read the game's dispatcher flag; no bridge freeze is involved.
Level, section, grade and Reset Player controls stay enabled. Their inputs are
silently discarded while disconnected, booting or outside gameplay; they are
never queued for the next game.

Built-in debug mode is available from the Game menu.

Hotkeys can be configured from **Game → Hotkeys**. They are polled through MAME's
host input layer and operate on the player selected in the app. **Toggle visibility**
switches between forced Invisible and Visible, keeping the override enabled so
already-hidden cells can be revealed. Fading switches to Visible; with no override,
the first tap selects Invisible. Holding the visibility or ghost hotkey releases
that override. Existing binding
IDs are retained. Closing the app leaves MAME running with its selected settings;
use **Release all overrides** first if you want normal behavior immediately.

## Architecture and assembly

- `plugin/asm/native.s`: authoritative, commented GNU SH-2 source.
- `plugin/asm/sites.json`: hook locations and required original bytes.
- `plugin/native.json`: generated payload and patch manifest, bundled for users.
- `plugin/catalog.json`: control ranges, units, flags and timing presets.
- `plugin/native.lua`: signature checks, installation, parameter commits and actions.
- `plugin/init.lua`: versioned JSON-lines transport and read-only telemetry.
- `app/tgmtrainer`: UI, validated profiles, acknowledged desired-state bridge, launcher.

See [the patch ABI and hook contracts](docs/native-patches.md) and
[the original reverse-engineering notes](docs/game-value-flow.md).

Build the assembly using GNU SH binutils (`binutils-sh4-linux-gnu` in WSL Ubuntu):

```powershell
python tools/build_patches.py --wsl Ubuntu
python tools/build_patches.py --wsl Ubuntu --check
```

On Linux use the same command without `--wsl Ubuntu`. The build needs no ROM,
Ghidra or private disassembly. Users run the prebuilt manifest. Unsupported or
modified hook bytes cause installation to fail before any patch is written.
Soft reset and save-state load trigger signature validation and reinstallation.

## Verify and package

```powershell
python -m unittest discover -s tests -v
python tools/verify_mame.py C:/Games/Emulators/MAME/mame.exe
python tools/verify_app.py C:/Games/Emulators/MAME/mame.exe
python tools/verify_attract.py C:/Games/Emulators/MAME/mame.exe
python tools/verify_practice.py C:/Games/Emulators/MAME/mame.exe
python tools/benchmark_mame.py C:/Games/Emulators/MAME/mame.exe
```

The live test launches a separate game with temporary configuration/NVRAM and
automates coin/start inputs. It checks actual movement, per-player parameters,
lock reloads, music scene selection, steady-state write counts and reset behavior.
The app test also checks real Qt controls through the bridge and staged launcher.
The patch document records benchmark results and remaining gameplay coverage.

Build a standalone app using `./build.ps1` or `bash build.sh`. The generated
executable is in `app/dist/`; the matching plugin is included. No ROM is bundled.
On Windows, `python tools/verify_package.py` checks packaged startup and its
bridge handshake. The packaging script isolates DLL discovery from unrelated
applications on PATH, which can otherwise introduce incompatible runtimes.

Please do not use this to cheat. I will hate you.
Use this to suffer, like Mihara-san intended.
