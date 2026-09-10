"""Check each player's BIG opening preview, spawn grid and tap/DAS movement."""

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
    for players in ("10", "01"):
        output = ROOT / ".venv/big-evidence" / players
        output.mkdir(parents=True, exist_ok=True)
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
                    "58",
                    "-skip_gameinfo",
                    "-autoboot_delay",
                    "0",
                    "-autoboot_script",
                    str(ROOT / "tools/big_probe.lua"),
                    "-cfg_directory",
                    directory + "/cfg",
                    "-nvram_directory",
                    directory + "/nvram",
                ],
                cwd=exe.parent,
                env=dict(
                    os.environ,
                    TGM_TEST_PLUGIN=(ROOT / "plugin").as_posix(),
                    TGM_TEST_GAMEPLAY=(ROOT / "tools/gameplay_probe.lua").as_posix(),
                    TGM_TEST_BIG_PLAYERS=players,
                    TGM_TEST_OUTPUT=output.as_posix(),
                ),
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
        (output / "mame.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        assert (
            result.returncode == 0
            and result.stdout.count("BIG PASS") == 2
            and "[LUA ERROR]" not in result.stderr
        ), result.stdout + result.stderr[:3000]
        print(
            "\n".join(line for line in result.stdout.splitlines() if "BIG PASS" in line)
        )


if __name__ == "__main__":
    main()
