"""Verify real soft/sonic-drop inputs with native base gravity and MAME DRC."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mame", type=Path)
    args = parser.parse_args()
    exe = args.mame.resolve()
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run(
            [
                str(exe),
                "tgm2p",
                "-video",
                "none",
                "-sound",
                "none",
                "-nothrottle",
                "-drc",
                "-noplugins",
                "-seconds_to_run",
                "52",
                "-skip_gameinfo",
                "-autoboot_delay",
                "0",
                "-autoboot_script",
                str(ROOT / "tools/drop_probe.lua"),
                "-cfg_directory",
                str(Path(directory) / "cfg"),
                "-nvram_directory",
                str(Path(directory) / "nvram"),
            ],
            cwd=exe.parent,
            env=dict(
                os.environ,
                TGM_TEST_PLUGIN=(ROOT / "plugin").as_posix(),
                TGM_TEST_GAMEPLAY=(ROOT / "tools/gameplay_probe.lua").as_posix(),
            ),
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        assert (
            result.returncode == 0
            and "DROP PASS" in result.stdout
            and "[LUA ERROR]" not in result.stderr
        ), result.stdout + result.stderr
        print(next(line for line in result.stdout.splitlines() if "DROP PASS" in line))


if __name__ == "__main__":
    main()
