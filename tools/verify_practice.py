"""Live Doubles renderer fixture with image evidence; requires local MAME/ROM."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mame", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".venv/practice-evidence")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        TGM_TEST_PLUGIN=(ROOT / "plugin").as_posix(),
        TGM_TEST_OUTPUT=output.as_posix(),
        TGM_TEST_GAMEPLAY=(ROOT / "tools/gameplay_probe.lua").as_posix(),
    )
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
                "55",
                "-skip_gameinfo",
                "-autoboot_delay",
                "0",
                "-autoboot_script",
                str(ROOT / "tools/practice_probe.lua"),
                "-cfg_directory",
                str(Path(directory) / "cfg"),
                "-nvram_directory",
                str(Path(directory) / "nvram"),
            ],
            cwd=exe.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        assert result.returncode == 0 and "PRACTICE PASS" in result.stdout, (
            result.stdout + result.stderr
        )

        def stack(name):
            image = QImage(str(output / f"{name}.png"))
            assert not image.isNull(), name
            # Sample tile interiors away from the two stationary active pieces.
            # The border highlight and animated field background can vary.
            return [
                image.pixelColor(x, 44).getRgb()[:3]
                for x in (107, 115, 147, 155, 163, 171, 203, 211)
            ]

        assert stack("stock") == stack("visible"), (
            "forced visible did not restore the full stack"
        )
        assert all(max(pixel) > 40 for pixel in stack("stock")), "fixture stack missing"
        assert all(max(pixel) < 32 for pixel in stack("hidden")), (
            "P1 invisible did not hide Doubles stack"
        )
        assert all(max(pixel) < 32 for pixel in stack("released")), (
            "release did not restore native invisibility"
        )
        print(
            f"PASS: P1 hides and reveals the Doubles shared stack, including expired invisible cells; stored attributes preserved; release restores game rendering. Screenshots: {output}"
        )


if __name__ == "__main__":
    main()
