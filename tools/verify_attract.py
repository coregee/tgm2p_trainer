"""Compare stock and overridden attract playback using the real SH-2 recompiler."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mame", type=Path)
    args = parser.parse_args()
    exe = args.mame.resolve()
    catalog = json.loads((ROOT / "plugin/catalog.json").read_text())
    profiles = {
        "stock": None,
        "patched_disabled": {"players": [{}, {}], "global": {}},
        "hidden_big": {
            "players": [
                {k: c["max"] for k, c in catalog["controls"].items() if k != "gravity"}
            ]
            * 2,
            "global": {"music": 3},
        },
        "visible_zero": {
            "players": [
                {
                    k: c["min"]
                    for k, c in catalog["controls"].items()
                    if k != "effective_gravity"
                }
            ]
            * 2,
            "global": {"music": 0},
        },
    }
    traces = {}
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for name, settings in profiles.items():
            prefix = (ROOT / "plugin").as_posix()
            setup = ""
            if settings:
                setup = f"""
local json=require('json')
local function load(n) local f=assert(io.open('{prefix}/'..n)); local t=json.parse(f:read('a')); f:close(); return t end
local native=dofile('{prefix}/native.lua').new(s,load('native.json'),load('catalog.json'))
native:sync(json.parse([==[{json.dumps(settings)}]==]))
local function ignored_actions()
 for p=0,1 do
  native:action('level',p,486)
  native:action('section',p,1)
  native:action('grade',p,12)
  native:action('restart',p)
 end
 assert(native.action_writes==0,'unavailable action wrote game RAM')
end
ignored_actions() -- still booting; must not access player RAM or raise an error
"""
            script = folder / f"{name}.lua"
            script.write_text(f"""
local s=manager.machine.devices[':maincpu'].spaces.program
local frame=0
{setup}
_G.attract_test=emu.add_machine_frame_notifier(function()
 frame=frame+1
 {"native:install(); assert(not native.error,native.error)" if settings else ""}
 {"if frame==2400 then local desired=native.desired; native:sync({players={{},{}},global={}}); native:sync(desired); assert(native.action_writes==0) end" if settings else ""}
 if frame>=1200 and frame%120==0 then
  assert(s:read_u16(0x06060022)==0,'unexpected gameplay')
  {"ignored_actions()" if settings and name != "patched_disabled" else ""}
  local h=0
  local bytes={{}}
  for a=0x06064880,0x06065000 do h=((h*33)~s:read_u8(a))&0xffffffff; bytes[#bytes+1]=string.format('%02x',s:read_u8(a)) end
  for p=0,1 do
   local b=0x06064898+p*0x3b4
   local field=s:read_u32(b)
   local size=s:read_u8(b+0xde)*s:read_u8(b+0xdf)*6
   for a=field,field+size-1 do h=((h*33)~s:read_u8(a))&0xffffffff end
  end
  print(string.format('TRACE %d %08x %d %d %d %s',frame,h,s:read_u8(0x06064bf5),s:read_u16(0x06064bba),s:read_i16(0x06064892),table.concat(bytes)))
 end
end)
""")
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
                    "-seconds_to_run",
                    "360",
                    "-noplugins",
                    "-skip_gameinfo",
                    "-autoboot_delay",
                    "0",
                    "-autoboot_script",
                    str(script),
                    "-cfg_directory",
                    str(folder / name / "cfg"),
                    "-nvram_directory",
                    str(folder / name / "nvram"),
                ],
                cwd=exe.parent,
                capture_output=True,
                text=True,
                timeout=80,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "Error" not in result.stdout and "error" not in result.stderr, (
                result.stdout + result.stderr
            )
            trace = [
                line for line in result.stdout.splitlines() if line.startswith("TRACE")
            ]
            assert len(trace) >= 170, result.stdout[-2000:] + result.stderr
            assert any(line.split()[3] == "2" for line in trace), "demo never played"
            traces[name] = trace
            # Additional trampoline instructions can change a later demo's RNG
            # seed timing. Compare desired-on against installed-but-disabled:
            # this proves suspension without conflating it with stock timing.
            if name not in ("stock", "patched_disabled"):
                for stock, patched in zip(
                    traces["patched_disabled"], trace, strict=True
                ):
                    if stock != patched:
                        a, b = (
                            bytes.fromhex(stock.split()[-1]),
                            bytes.fromhex(patched.split()[-1]),
                        )
                        differences = [
                            (hex(0x06064880 + i), x, y)
                            for i, (x, y) in enumerate(zip(a, b))
                            if x != y
                        ]
                        raise AssertionError(
                            (name, stock[:40], patched[:40], differences[:30])
                        )
            print(
                f"PASS {name}: {len(trace)} samples across six minutes of attract playback",
                flush=True,
            )
    print(
        "PASS: enabled settings match disabled settings byte-for-byte in player state, shared fields and music throughout attract playback"
    )


if __name__ == "__main__":
    main()
