# TGM2+ game value flow: initial reverse engineering

Status: original game code inspected on 2026-09-10 using Ghidra and GNU SH-2
disassembly. This is the initial investigation snapshot; the subsequent native
implementation and validation are documented in [native-patches.md](native-patches.md).
The proposals below describe the reasoning that preceded that implementation.
The old address map is evidence to check, not a complete
specification. This document deliberately distinguishes confirmed paths from
remaining work.

Addresses are CPU addresses for the `tgm2p` program. The primary player structure
is at `0x06064898`; P2 is at `0x06064C4C` (stride `0x3B4`). Code executes from
work RAM. The original boot copy maps ROM offset `0x780` to RAM `0x06000000`.

## Gravity: confirmed producer and consumers

`0x06007BFA` selects base gravity from the player's mode and level. It receives
the player pointer in `r4` and returns gravity in `r0`.

| Input / output | Player offset | Meaning |
| --- | --- | --- |
| Mode | `+0x30C`, u16 | Chooses the mode path and special cases |
| Level | `+0x322`, u16 | Index into gravity tables, with mode adjustments |
| Special flag | `+0x339`, byte, bit `0x08` | Selector can return `0x4000` |
| Cached base gravity | `+0x358`, u32 | P1 `0x06064BF0` |
| Vertical position | `+0x368`, 32-bit fixed point | P1 `0x06064C00` |

Gravity uses 16 fractional bits: `0x10000` = 1 cell per update, and `0x140000`
= 20G. The existing display field at `0x06064BF1`, size 2, reads the middle
two bytes of the full value. It expresses common values in 1/256G units but
omits both the highest and lowest byte. It is not the full physics variable.

The selector uses table bases `0x0003660C` (Master / Versus), `0x000375B0`
(Normal), `0x00037A68` (Doubles), and `0x00037F1C` (TGM+). Death offsets the
Master lookup by 700 and caps it at 999; other mode flags can select the last
entry. These are 32-bit entries indexed by level.

Three call sites were found: `0x06003C6C`, `0x06005E6A`, and `0x06006022`.
Their function-pointer literals are respectively `0x06003D40`, `0x06005F78`,
and `0x060060D4`. The latter two paths still need full gameplay classification.

The active movement function at `0x060038C4` does the following (descriptive
pseudocode, not literal source):

```c
gravity = select_base_gravity(player);
player->cached_gravity = gravity;
// gravity remains in r12; writing the cache does not replace this register.
if (soft_drop) gravity = max(gravity, ONE_G);
else if (sonic_drop) gravity = TWENTY_G;
if (forced_20g_conditions) {
    player->cached_gravity = TWENTY_G;
    gravity = TWENTY_G;
}
move_and_handle_lock(player, gravity);
```

The register-to-cache store is at `0x06003C76`. The consumer at `0x060036AE`
passes its gravity argument to `0x06003812`, which subtracts fractional gravity
from vertical position and checks collision while stepping whole cells. Falling
therefore decreases this coordinate. Neither routine needs to reload gravity
from the cached field to perform that movement.

This explains why intercepting a store to the cache is insufficient: it can
change observable RAM while leaving the movement argument unchanged. The active
movement path selects gravity again, rather than relying on a once-initialized
RAM value. Exact invocation counts across game states have not been measured in
this static investigation.

### Proposed native override

Keep a trainer-owned enabled flag and full-width gravity value in reserved RAM.
Have the selector return that value when enabled, otherwise run its original
logic. The bridge writes these parameters only when the setting changes.

This adds a small amount of guest SH-2 work at the existing calculation point;
it requires no Lua callback or host write per movement update. It should retain
the recompiler, but installation, code-cache invalidation, reset handling, and
performance must be verified with an actual implementation.

The semantics matter: overriding base gravity preserves downstream soft drop,
sonic drop, and forced-20G behavior. Overriding effective gravity requires a
different point after those adjustments and a review of the other two callers.
Changing a return value is preferable to merely preventing the cache store.

## Other values: different roles

| Value | Confirmed evidence | Implication for a trainer |
| --- | --- | --- |
| Level | `player+0x322` is read directly by the gravity selector and DAS logic (`0x06003508`). | A level edit affects multiple systems. A speed-level override can instead supply an alternate level to speed selection. Holding actual progression requires tracing progression writers and boundary checks. |
| Section | `player+0x38C` indexes per-section records in `0x060112A0`, including timing and qualification checks. The map also names a distinct byte at `+0x346` as `section_count`; `0x060059D0` increments it. | Section is bookkeeping, not just a displayed quotient of level. The relationship of these counters and every transition is not yet fully mapped. |
| Lock duration | `0x06002840` selects a duration from tables using mode/level, stores it at `+0x348`, then copies it to `+0x347`. `0x060036AE` reloads and decrements the latter. | Override the selected duration while allowing the countdown to run. **The existing map's description of `+0x348` as remaining frames is wrong:** remaining frames are at `+0x347` (P1 `0x06064BDF`); reload duration is at `+0x348` (P1 `0x06064BE0`). |
| DAS | `0x06003508` selects a threshold from mode/level, compares charge byte `+0x349` against it, and increments/resets that charge in response to input. | Override the threshold, not the charge. The charge remains normal gameplay state. |
| ARE, line ARE, line-clear delay | Existing patches target their selection/assignment code near `0x06002950`–`0x06002B4A`. | Their complete producers, counters, and reset paths remain to be traced before treating the old patches as a specification. |
| Music | Director `0x06008F2C` derives scenes from game state, consumes request byte `0x06079299`, resets it to `0xFF`, and manages transitions. Loader `0x0602DE2A` records the loaded track at `0x06064767` and initializes playback data. | A scene request and a loaded-track status are different. A one-time request can change music; persistent selection should override the director's choice while retaining its transition logic. Changing the status byte alone does not load audio. |
| Invisible blocks | Renderer `0x060161B8` reads 6-byte field cells and suppresses drawing based on cell attribute bit `0x4000`; it also handles cell timers and animation flags. | A native drawing-condition override is a candidate for persistent invisibility. Complete behavior also needs active-piece, locking, fade, reveal, and mode paths checked. The existing player flag and per-cell attributes must not be treated as interchangeable. |

## Rewrite boundary

The app should send desired settings on change/reconnect. The plugin can install
version-checked ASM patches and update their parameters on change. Game routines
then consume those parameters at their normal selection points. Telemetry can
be sampled independently; it does not need to enforce settings.

This investigation does not establish that every modifier can use one hook, or
that the current application failure has a single cause. It does establish why
an address-only schema cannot adequately describe all these controls.
