# Native patch architecture (ABI 4)

The source of truth is `plugin/asm/native.s`, assembled as big-endian SH-2 by
GNU binutils. `sites.json` supplies original-byte signatures and detour sites.
`tools/build_patches.py` assembles both the payload and jump stubs, resolves
PC-relative literal pools and emits `native.json`. Hex in that generated file
is an artifact, not a second hand-maintained implementation.

The desktop UI exposes only base gravity, labelled **Gravity**, preserving
soft/sonic drop and forced-20G decisions downstream. The effective-gravity ABI
remains available to older protocol clients and diagnostic fixtures; desktop
profiles migrate effective-gravity values to base gravity on load.
UI gravity values snap to 1/256G to 1G, 4/256G to 5G, then quarter-G steps. The
payload continues to consume a full 16.16 value.

## Ownership and lifecycle

The app owns a complete desired snapshot. A missing control means **use game
logic**; a present value enables that control even if its value is zero. The
bridge sends a snapshot on edits and reconnect, and waits for acknowledgement.
Connection, patch readiness and acknowledged revision are separate states.

Lua validates the entire snapshot before changing anything. It writes guest RAM
only for installation, changed settings, explicit practice actions, and reset or
state-load recovery. Frame callbacks service communication, input and telemetry;
they do not enforce modifiers. Diagnostics count parameter and action writes.

After the boot copy appears, every hook must match either its original signature
or this build's generated patch. One mismatch prevents the whole installation.
Lua writes the payload, hooks and parameters between CPU slices. Reset and state
load invalidate readiness and republish the app's desired state. An unsupported
ROM or conflicting patch produces a visible error rather than a misleading
connected status. MAME runs with the SH-2 dynamic recompiler enabled.

Runtime code occupies `0x060E0000` onward (currently 2,656 bytes); settings start
at `0x060EF000`. These are trainer-reserved locations in work RAM, not ROM edits.
Other trainers using this area must not be combined with this plugin. Original
program code is copied from ROM offset `0x780` to `0x06000000` during boot.

## Parameter layout

Each player gets 256 bytes, selected using player structure byte `+0x30E`.
P1's record is `0x060EF000`, P2's is `0x060EF100`. All fields below are aligned
32-bit big-endian values. Disabled parameters may retain old values: the flag
word alone decides whether they are consumed.

| Flag | Parameter offset | Meaning |
| --- | --- | --- |
| `0x0001` | `+0x04` | Base gravity, unsigned 16.16 cells/update |
| `0x0002` | `+0x04` | Effective gravity; mutually exclusive with base gravity |
| `0x0004` | `+0x0C` | ARE counter reload |
| `0x0008` | `+0x10` | Line ARE counter reload |
| `0x0010` | `+0x14` | Line-clear counter reload |
| `0x0020` | `+0x18` | Lock duration/reload |
| `0x0040` | `+0x1C` | DAS threshold |
| `0x0080` | `+0x20` | Stack drawing: 0 show, 1 hide |
| `0x0100` | `+0x24` | Captured frozen level; explicit jumps update the anchor |
| `0x0200` | `+0x28` | Torikan bypass (flag is sufficient) |
| `0x0400` | `+0x2C` | Ghost: 0 off, 1 on |
| `0x0800` | `+0x30` | M-roll qualification override (flag is sufficient) |
| `0x1000` | `+0x34` | Queued BIG variant: 0 off, 1 TGM2 (legacy on), 2 TGM1, 3 TAP (UI default) |
| `0x2000` | `+0x38` | ITEM mode flag: 0 off, 1 on |

Offset zero contains the flag word. Global signed scene selection lives at
`0x060EF200`: -1 follows the game, 0..10 selects a scene. `catalog.json` defines
public ranges and the two-frame display adjustment for ARE, line ARE and DAS.

Runtime offset `+0x40` latches the active piece's BIG variant at handoff; -1
means original game logic. Offset `+0x44` is the `BIG5` initialization marker,
allowing state reloads to retain the active variant. These are guest-owned
runtime fields, not settings rewritten by the host. Queue edits, disabling and
releasing BIG leave the current piece's rules intact until handoff.

## Hook contracts

The `config` assembly macro reads a record and clobbers `r0`, `r1` and T. Callers
preserve registers where live. Detours replay displaced instructions, including
PC-relative values resolved at their original sites. Branch delay slots are
explicit. Absolute stubs use `r0`; return jumps choose another scratch register
where the original continuation still needs `r0`.

| Hook site(s) | Existing decision and replacement |
| --- | --- |
| `06003D40`, `06005F78`, `060060D4` | Function-pointer literals for selector `06007BFA`. Input `r4` is player, return `r0` is base gravity. Disabled path tail-calls the original selector. |
| `06003812` | Physics entry receives player in `r4`, displacement in `r5`. Effective override replaces `r5`, then replays the original prologue and resumes at `06003820`. |
| `06002840` | Lock initializer wrapper calls original code, then replaces player `+348` duration and `+347` initial countdown. |
| `06002988` | Line-clear initializer wrapper changes the newly loaded `+300` countdown. |
| `06002A5C` | Entry initializer wrapper selects ARE versus line ARE using original `r5`, then changes the new `+300` countdown. Timing wrappers retain `r8/r9`, PR, input `r4/r5` and original return `r0`. |
| `060035AC` | DAS consumer: player is `r14`, selected threshold is `r4`. Only the threshold changes; input charging and repeats remain original. |
| `06009254` | Music director consumes/clears its original request, then optionally replaces the pending scene before original transition logic resumes. |
| `06006B88` | Piece-entry progression: restores the freeze anchor and skips the increment/cap; disabled path replays stock progression. |
| `06006FE0` | Line progression: TGM1/TGM2 add rows beyond the ordinary four-level cap, then freeze overrides the result before original section/grade calls and boundary checks. |
| `06006EEE`, `06006F14` | BIG count normalization and progression predicates: TAP uses the stock BIG path (two physical rows per big line); TGM1/TGM2 use physical row counts. Unowned and attract paths retain the mode predicate. |
| `06007016` | Torikan decision: enabled path skips to `06007038`; disabled path replays the time/qualification test. |
| `06016136`, `060164FA` | Alternate drawing predicate and main gameplay renderer (both single-player and Doubles). Visible clears `0x5000` in the temporary attribute register. Invisible hides ordinary mature cells, preserving `0x80` lock flash and `0x1000` timed fade. Fading follows stored cell timers. States 7, 9, 10, 11 and 13 retain original reveal behavior. |
| `06003DCA`; eight `tst` sites in `06003F34..06004882` | Lock setup computes the invariant roll-mode predicate in `r9`; the cell writers test that value. Invisible/Fading initialize the original timed-cell mechanism with 3/300 for actual locks only. No extra traversal or mode/qualification mutation. |
| `060024FC` | Ghost render call: replace its `r6` visibility bit (`0x4000`) before calling the original renderer. |
| `06003DA2`, `0600510C`, `0602219E` | Qualification consumers in lock, clear and roll handling: return satisfied `0x75` bits when enabled. No grade or time forgery. |
| `06005AB4`, `06005BD4` | Before handoff and after generation: force queued BIG (`0x0200`) and ITEM mode (`0x0200`), preserving unrelated bits. Current geometry changes only at normal handoff. |
| `06001100` | Apply queued flags at the end of player initialization, after the original opening-preview generator and BIG-mode adjustment. Replay the original epilogue. |
| `06003620`, `06003658`, `06005C42` | Left/right input and spawn alignment: TGM1 uses one-column movement and x=4; TGM2/TAP use the active geometry to select two-column movement and x=5. Unowned and attract paths use the original mode predicate. |

The cached gravity at player `+358` is telemetry, not necessarily the effective
physics argument. Base gravity still permits downstream soft drop and forced
20G. Effective gravity changes displacement after those choices. A native hook
can execute each physics update without any per-update host write or Lua tap.

The `config` macro checks the 16-bit main dispatcher at `06060022`: only value
**1** permits overrides. The original dispatcher at `06009440` selects
attract/title for 0, gameplay for 1, and service for 2. Music uses the same guard.
Lua gates immediate BIG/ITEM writes and practice actions. Player IDs outside
0–1 return no override flags instead of indexing beyond parameter records.

Level jumps set level `+322`, section index `+38C`, and section count `+346`.
They update the freeze anchor if enabled. Section +/- actions read current RAM
and jump to the adjacent section start. History, score and timers are not
reconstructed. TRANS FORM is removed; old profiles drop it and migrate numeric
held-level settings to the current-level freeze toggle.

## Verification and limits

### Canonical lock feedback and fading

`06003D54` writes each locked cell with `0xA0`: `0x80` selects the grey flash
and `0x70` contains its two-frame countdown. Roll mode (`player+30C & 0x10`)
also writes `0x1000` and a 16-bit timer at `cell+4`. Qualification bits
`player+338 & 0x75 == 0x75` select **3**; otherwise the timer is **300**.
The trainer supplies those timers at the same writer without forging roll mode.
Parameter `+32` remains backwards compatible: 0=Visible, 1=Invisible, 2=Fading.

The main renderer `060161B8`, used by both single-player and Doubles, handles
the flash at `06016538`, then the timed fade at `06016794`. The original
override set `0x4000` before those branches, suppressing even fresh lock flashes.
It now lets fresh timed cells pass through the original rendering logic.

Measured render sequence, counting the first lock draw as frame 1:

| Frames | Invisible / M-roll | Fading / other roll |
| --- | --- | --- |
| 1–2 | Grey flash; timer stays 3 | Grey flash; timer stays 300 |
| 3–4 | Two darkening palette steps; timer 2, then 1 | Full colour; timer 299, then 298 |
| 5 onward | Hidden at timer 0 | Full colour through frame 292 (timer 10) |
| 293–301 | Hidden | Five darker palette levels, timer 9 down to 1 |
| 302 onward | Hidden | Hidden at timer 0 |

The 300-frame setting is about **five seconds**, not a multi-second continuous
fade: most of that time is fully visible, followed by nine drawn fade frames.
Palette selection is base palette plus `timer >> 1` below 10. At zero the draw
is skipped; a later renderer visit sets the persistent `0x4000` hidden flag.
MAME snapshots in the fixture show the preceding frame's render packet.

Doubles temporarily stamps the other player's piece using writer operation 1
(`06001314`), then restores attributes through `060049E8`. This does **not**
restore `cell+4`: enabling the roll writer for these stamps repeatedly resets
the fade timer. The override therefore initializes timers only for operation 0
(actual locks), leaving collision stamps and operation 2 out of the timed path.
The disabled path retains the original mode-dependent behavior.

`tools/verify_invisible.py` uses real input/locks, a raised landing surface and
the original mode/qualification readers as a reference. It compares per-frame
attributes, countdowns and rendered tile interiors for Invisible and Fading,
including BIG and Doubles. Doubles has no canonical M-roll, so its result is
compared against the single-player roll sequence. This fixture verifies the
lock/render mechanisms, not a complete earned GM qualification run.

`python -m unittest discover -s tests -v` covers profile validation, full snapshot
reconnect including offline releases, transport framing, UI units/player
isolation and acknowledgement, and generated hook ranges. `build_patches.py
--check` checks reproducibility from assembly source.

`tools/verify_mame.py` runs a real, isolated MAME game with DRC and automated
coin/start input. It checks actual stationary 0G movement and falling at 20G,
independent P2 gravity, lock reload, held level across piece progression,
effective gravity, music scene selection, steady parameter-write counts and
fresh-game recovery after soft reset.

`tools/verify_drop.py` checks real Down/Up inputs with the exposed base-gravity
override at 0G: the airborne piece stays still, soft drop moves it, releasing
Down restores 0G, and sonic drop reaches the floor. P2 stays still and no trainer
parameters are rewritten during these inputs. `verify_app.py` exercises the
base-gravity control through the actual Qt app and staged bridge.

`tools/verify_big.py` selects all three BIG variants independently for P1 and P2
before game start. It checks opening-preview and first-piece flags, spawn x=5
for TGM2/TAP versus x=4 for TGM1/off, and real taps plus held DAS movement in
both directions. Changing the queued toggle during a piece retains its grid.
Opening-preview screenshots and logs are saved under `.venv/big-evidence`.
No stock BIG game-mode bit is set.

`tools/verify_big_lines.py` seeds full rows then drops and locks real pieces.
For both players, single through tetris gains are 2/4/6/8 in TGM1/TGM2 and
1/2/3/4 in TAP/off (off uses ordinary-sized rows). It also checks section
crossings, level freeze, and variant changes before the active piece locks.
The fixture checks native clear processing on seeded fields, not a complete
played game or historical scoring fidelity outside the requested level/grid rules.

Music scene `06064892` is the director's selected scene, not proof of audible
playback. The loaded-track byte `06064767` stayed `0xFF` in both patched and
unpatched headless runs; the UI therefore reports **Scene**, not **Playing**.
Audible playback still needs a listening check. Full M-roll qualification,
torikan crossing, line-clear timing, end-of-game reveal and save-state
recovery need dedicated gameplay coverage beyond this smoke test. They have
source-level hooks and signature validation; the smoke test does not establish
every game-mode edge case.

### ABI 4 regression coverage (2026-09-10)

`verify_attract.py` runs stock, patched-disabled and two complete override
profiles through six minutes of attract playback each. Desired-on and
desired-off traces match byte-for-byte for player structures, fields and music,
including settings edits during demo playback. Stock and patched runs can select
different later-demo RNG seeds because instruction timings differ; suspension
is compared against the installed-disabled build.

`verify_app.py` also checks 486 -> section 4, section up -> 500, updating a frozen
anchor, and actual queued BIG / ITEM toggle bits. `verify_mame.py` observes BIG
handoff to active geometry while the stock BIG-mode bit remains clear.

`verify_practice.py` uses a test-only Doubles initialization/seeded-stack fixture,
then compares rendered tile interiors for hidden, forced-visible (including
expired timed-invisible cells), and released visibility. Stored cell flags
remain intact. This is targeted renderer coverage, not a full Doubles game or
every item/mode interaction. The following benchmarks describe their recorded
ABI 3 builds, not this revised payload.

On 2026-09-10, three paired 90-second unthrottled headless runs with MAME 0.289
and DRC measured median stock throughput of **23.47x real time** versus **22.89x**
with all native hooks installed and overrides disabled (**2.5% lower**). Both
used the same automated game input, video disabled and audio muted. This measures
the plugin and inactive-hook overhead, not every enabled-control combination or
normal windowed rendering. This was the initial benchmark, without a connected
client; the current benchmark below includes an active telemetry connection.

### Enabled overrides benchmark (2026-09-10)

Five repeats per configuration, each running 120 emulated seconds in MAME 0.289
with DRC, no host video output, muted audio, temporary configuration/NVRAM and
the same automated two-player coin/start input. Measurement order rotates.
Every trainer run has a connected client draining telemetry and periodically
reading diagnostics. The client sends its settings exactly once.

| Configuration | Median speed | Observed speed range | Execution time / stock |
| --- | ---: | ---: | ---: |
| Stock, no plugin | 22.75x | 21.80–22.81x | 1.000x |
| Connected, all overrides disabled | 21.58x | 21.41–21.67x | 1.054x |
| Base gravity and visible stack overrides enabled | 21.39x | 20.94–21.52x | 1.064x |
| Effective gravity and hidden stack overrides enabled | 21.30x | 21.07–21.54x | 1.068x |

Both enabled profiles additionally enable all five timing controls, held level,
torikan bypass, ghost, M-roll qualification and TRANS FORM for both players, plus
a global music scene. Gravity is 1024 in 16.16 (1/64G), level is held at zero,
and timers use the initial Master preset. Base and effective gravity are mutually
exclusive, so they are measured in separate profiles. Exact settings, individual
speeds and verification counters are in
[benchmarks/native-overrides.json](benchmarks/native-overrides.json).

Compared with the connected disabled case, enabled profiles required about
**0.9% and 1.3% more execution time**. Their observed speed ranges overlap;
these measurements do not establish that such a small difference is significant.
The entire connected trainer cost roughly **5.4–6.8%** over stock in this batch.
That includes telemetry serialization, sockets, client activity and native
hooks; it is not a profile attributing cost to any one component.

Every trainer run verified acknowledged settings, sustained active play for both
players, and unchanged parameter/action write counts after setup. Enabled runs
also observed transformed active pieces for both players, demonstrating a native
handoff override taking effect. Hiding blocks and holding level change the game
workload, so these are practical enabled-profile comparisons, not an instruction
cost isolation experiment. Boot is included in MAME's average; normal-mode
gameplay does not exercise full M-roll, Death torikan, every line-clear path or
Doubles rendering. Host GPU presentation cost is excluded.

Reproduce with:

```powershell
python tools/benchmark_mame.py C:/Games/Emulators/MAME/mame.exe --runs 5 --seconds 120 --output docs/benchmarks/native-overrides.json
```

`tools/verify_app.py <mame.exe>` additionally drives the actual Qt gravity control
through the app's bridge and staging launcher, checking stationary 0G, applied
revision status and restored falling after unchecking the override.
