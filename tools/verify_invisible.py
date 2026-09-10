"""Compare actual M-roll and trainer lock/fade frames under MAME's recompiler."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]


def run(exe, output, canonical, doubles=False, big=False, fading=False):
    output.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        TGM_TEST_PLUGIN=(ROOT / "plugin").as_posix(),
        TGM_TEST_OUTPUT=output.as_posix(),
        TGM_TEST_GAMEPLAY=(ROOT / "tools/gameplay_probe.lua").as_posix(),
        TGM_TEST_CANONICAL=str(int(canonical)),
        TGM_TEST_DOUBLES=str(int(doubles)),
        TGM_TEST_BIG=str(int(big)),
        TGM_TEST_FADING=str(int(fading)),
    )
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
                "65",
                "-skip_gameinfo",
                "-autoboot_delay",
                "0",
                "-autoboot_script",
                str(ROOT / "tools/invisible_probe.lua"),
                "-cfg_directory",
                str(Path(directory) / "cfg"),
                "-nvram_directory",
                str(Path(directory) / "nvram"),
            ],
            cwd=exe.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    (output / "mame.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert (
        result.returncode == 0
        and "INVISIBLE PASS" in result.stdout
        and "[LUA ERROR]" not in result.stderr
    ), result.stdout + result.stderr
    return json.loads((output / "trace.json").read_text())


def pixels(folder, frame):
    cell = json.loads((folder / "cell.json").read_text())
    image = QImage(str(folder / f"{frame}.png"))
    assert not image.isNull(), (folder, frame)
    return [
        image.pixelColor(cell["x"] + dx, cell["y"] + dy).getRgb()[:3]
        for dx, dy in ((2, 2), (3, 3), (5, 5))
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mame", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".venv/invisible-evidence"
    )
    parser.add_argument("--canonical-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    for name, doubles, big, fading in (
        ("normal", False, False, False),
        ("big", False, True, False),
        ("doubles", True, False, False),
        ("fading", False, False, True),
        ("fading-doubles", True, False, True),
        ("fading-big", False, True, True),
    ):
        # Doubles has no canonical credit roll. Compare its override against
        # the single-player roll: temporary collision stamps must not restart
        # the shared field's countdown every frame.
        stock = run(
            args.mame.resolve(), output / name / "canonical", True, False, big, fading
        )
        print(name, "canonical:", stock[:6], stock[-2:])
        if not args.canonical_only:
            override = run(
                args.mame.resolve(),
                output / name / "override",
                False,
                doubles,
                big,
                fading,
            )
            mismatch = next(
                ((s, o) for s, o in zip(stock, override, strict=True) if s != o), None
            )
            assert mismatch is None, (name, mismatch)
            expected_timer = 300 if fading else 3
            assert [s["timer"] for s in stock] == [expected_timer, expected_timer] + [
                max(0, expected_timer - n + 1) for n in range(2, len(stock))
            ]
            # Snapshots present the preceding frame's render packet. Compare
            # visible tile interiors, excluding the independently animated
            # backgrounds exposed after the sprite disappears.
            for frame in range(1, expected_timer + 2):
                if (output / name / "canonical" / f"{frame}.png").exists():
                    assert pixels(output / name / "canonical", frame) == pixels(
                        output / name / "override", frame
                    ), (name, frame, "rendered pixels differ")
            assert min(pixels(output / name / "override", 1)[0]) > 100, (
                name,
                "grey lock flash missing",
            )
            assert max(pixels(output / name / "override", len(stock) - 1)[0]) < 40, (
                name,
                "expired cell remains visible",
            )
            print(
                name,
                "PASS: canonical flags, timers and rendered lock/fade pixels match",
            )


if __name__ == "__main__":
    main()
