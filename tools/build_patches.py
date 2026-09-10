"""Build reproducible native SH-2 patches. GNU SH binutils; Windows: --wsl Ubuntu."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x060E0000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl")
    parser.add_argument("--prefix", default="sh4-linux-gnu-")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    def path(p):
        p = str(Path(p).resolve())
        return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/") if args.wsl else p

    def run(tool, *params):
        cmd = [args.prefix + tool, *params]
        if args.wsl:
            cmd = ["wsl", "-d", args.wsl, "--", *cmd]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    sites = json.loads((ROOT / "plugin/asm/sites.json").read_text())
    with tempfile.TemporaryDirectory(dir=ROOT) as folder:
        folder = Path(folder)
        hooks = []
        for site in sites:
            hooks += [f'.section .{site["name"]},"ax"']
            if site["address"] % 4:
                hooks += [".org 2"]
            if site["kind"] == "pointer":
                hooks += [f".long {site['target']}"]
            elif site["kind"] == "instruction":
                hooks += [site["target"]]
            else:
                hooks += [
                    "mov.l 1f,r0",
                    "jmp @r0",
                    "nop",
                    ".balign 4",
                    f"1: .long {site['target']}",
                ]
                used = 10 if site["address"] % 4 == 2 else 12
                hooks += ["nop"] * ((site["size"] - used) // 2)
        (folder / "hooks.s").write_text("\n".join(hooks) + "\n")
        script = f"SECTIONS {{ .text 0x{BASE:x} : {{ *(.text) }}\n"
        script += "\n".join(
            f".{s['name']} 0x{s['address'] & ~3:x} : {{ *(.{s['name']}) }}"
            for s in sites
        )
        (folder / "link.ld").write_text(script + "\n}\n")
        try:
            run(
                "as",
                "--isa=sh2",
                "-big",
                "-o",
                path(folder / "native.o"),
                path(ROOT / "plugin/asm/native.s"),
            )
            run(
                "as",
                "--isa=sh2",
                "-big",
                "-o",
                path(folder / "hooks.o"),
                path(folder / "hooks.s"),
            )
            run(
                "ld",
                "-EB",
                "-T",
                path(folder / "link.ld"),
                "-o",
                path(folder / "native.elf"),
                path(folder / "native.o"),
                path(folder / "hooks.o"),
            )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(exc.stderr) from exc

        def section(name):
            out = folder / "section.bin"
            run(
                "objcopy",
                "-O",
                "binary",
                "--only-section=" + name,
                path(folder / "native.elf"),
                path(out),
            )
            return out.read_bytes()

        payload = section(".text")
        assert len(payload) < 0x8000
        patches = []
        for s in sites:
            data = section("." + s["name"])[s["address"] % 4 :][: s["size"]]
            assert len(data) == s["size"], (s["name"], len(data), s["size"])
            patches.append({**s, "bytes": data.hex()})
        result = {
            "abi": 4,
            "rom": "tgm2p",
            "base": BASE,
            "parameters": 0x060EF000,
            "payload": payload.hex(),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "patches": patches,
        }
        text = json.dumps(result, indent=2) + "\n"
        destination = ROOT / "plugin/native.json"
        if args.check:
            assert destination.read_text() == text, "native.json is stale: rebuild ASM"
        else:
            destination.write_text(text)
        print(
            f"{'Verified' if args.check else 'Built'} {len(patches)} hooks, {len(payload)} bytes of SH-2 code"
        )


if __name__ == "__main__":
    main()
