! TGM2+ trainer ABI 4. GNU SH-2 big-endian assembly.
! Each hook changes a producer or consumer at its existing execution point.
! No frame callback, RAM write tap, or extra field traversal enforces settings.
! See docs/native-patches.md for hook contracts and settings layout.
.section .text,"ax"

! Select the 256-byte parameter record using the game's player ID byte.
! Clobbers r0, r1, T. All callers explicitly save registers that remain live.
.macro config player
    ! Main dispatcher 0x06009440: 0=attract/title, 1=game, 2=service.
    ! Never alter prerecorded demo physics (its input stream assumes stock).
    mov.l .Lconfig_6\@,r1
    mov.w @r1,r0
    cmp/eq #1,r0
    bf .Lconfig_5\@
    mov.l .Lconfig_9\@,r1
    mov.w .Lconfig_8\@,r0
    mov.b @(r0,\player),r0
    extu.b r0,r0
    cmp/eq #0,r0
    bt .Lconfig_4\@
    cmp/eq #1,r0
    bf .Lconfig_5\@
.Lconfig_4\@:
    shll8 r0
    add r0,r1
    mov.l @r1,r0
    bra .Lconfig_7\@
    nop
.Lconfig_5\@:  mov #0,r0
    bra .Lconfig_7\@
    nop
    .balign 4
.Lconfig_6\@:  .long 0x06060022
.Lconfig_9\@:  .long 0x060ef000
.Lconfig_8\@:  .word 0x030e
.Lconfig_7\@:
.endm

! Absolute tail jump; r0 is scratch unless another register is specified.
.macro jump address,reg=r0
    mov.l 9f,\reg
    jmp @\reg
    nop
    .balign 4
9:  .long \address
.endm

.global gravity
gravity:
    mov.l r1,@-r15
    config r4
    tst #1,r0
    bt 1f
    mov.l @(4,r1),r0
    mov.l @r15+,r1
    rts
    nop
1:  mov.l @r15+,r1
    jump 0x06007bfa

.global effective
effective:
    mov.l r1,@-r15
    config r4
    tst #2,r0
    bt 1f
    mov.l @(4,r1),r5
1:  mov.l @r15+,r1
    ! Relocated 0x06003812..0x0600381e, including the original prologue.
    mov #1,r2
    mov.l r14,@-r15
    mov.l r13,@-r15
    mov.l r12,@-r15
    mov r5,r13
    mov.w 2f,r0
    mov r4,r12
    jump 0x06003820,r3
2:  .word 0x0362

! The three timing routines are wrapped at ENTRY. Their original logic runs
! before replacement of the newly loaded duration. Existing countdowns are
! never frozen. r8/r9, r4/r5, PR and the original r0 return are preserved.
.macro timing_begin gateway
    mov.l r8,@-r15
    mov.l r9,@-r15
    sts.l pr,@-r15
    mov r4,r8
    mov r5,r9
    mov.l 9f,r0
    jsr @r0
    nop
    bra 8f
    nop
    .balign 4
9:  .long \gateway
8:  mov.l r0,@-r15
    config r8
.endm
.macro timing_end
    mov.l @r15+,r0
    mov r8,r4
    mov r9,r5
    lds.l @r15+,pr
    mov.l @r15+,r9
    rts
    mov.l @r15+,r8
.endm

.global lock
lock:
    timing_begin lock_original
    tst #32,r0
    bt 1f
    mov.l @(24,r1),r2
    mov.w 2f,r0
    mov.b r2,@(r0,r8)
    add #-1,r0
    mov.b r2,@(r0,r8)
1:  timing_end
2:  .word 0x0348
lock_original:
    mov.w 1f,r0
    mov r4,r5
    mov.l 2f,r3
    mov.w @(r0,r5),r2
    and r3,r2
    mov.w r2,@(r0,r5)
    jump 0x0600284c,r1
1:  .word 0x035c
    .balign 4
2:  .long 0x0000ff00

.global clear
clear:
    timing_begin clear_original
    tst #16,r0
    bt 1f
    mov.l @(20,r1),r2
    mov.w 2f,r0
    mov.w r2,@(r0,r8)
1:  timing_end
2:  .word 0x0300
clear_original:
    mov.w 1f,r0
    mov r4,r5
    mov.l 2f,r3
    mov.w @(r0,r5),r2
    mov.l 3f,r7
    and r3,r2
    jump 0x06002994,r1
1:  .word 0x035c
    .balign 4
2:  .long 0x0000ff00
3:  .long 0x0003903e

.global entry
entry:
    timing_begin entry_original
    tst r9,r9
    bf 1f
    tst #4,r0
    bt 3f
    bra 2f
    mov.l @(12,r1),r2
1:  tst #8,r0
    bt 3f
    mov.l @(16,r1),r2
2:  mov.w 4f,r0
    mov.w r2,@(r0,r8)
3:  timing_end
4:  .word 0x0300
entry_original:
    mov.w 1f,r0
    mov r4,r6
    mov.w 2f,r3
    extu.b r5,r5
    mov.l @(r0,r4),r2
    tst r5,r5
    jump 0x06002a68,r1
1:  .word 0x0308
2:  .word 0xff7f

.global das
das:
    config r14
    tst #64,r0
    bt 1f
    mov.l @(28,r1),r4
1:  ! Relocate the threshold-consumer prefix, original r4 is the threshold.
    mov.b @r15,r7
    mov #0,r1
    mov.l 2f,r0
    mov #16,r6
    mov r1,r5
    extu.b r7,r7
    jump 0x060035b8,r2
    .balign 4
2:  .long 0x0606475a

.global music
music:
    ! Global director override; still consume the game's one-shot request.
    mov.l 3f,r5
    mov.b @r5,r4
    exts.b r4,r2
    cmp/gt r11,r2
    bf 1f
    mov.b r4,@r9
    mov.b r11,@r5
1:  mov.l 5f,r5
    mov.w @r5,r0
    cmp/eq #1,r0
    bf 2f
    mov.l 4f,r5
    mov.l @r5,r4
    cmp/pz r4
    bf 2f
    mov.b r4,@r9
2:  jump 0x06009262
    .balign 4
3:  .long 0x06079299
4:  .long 0x060ef200
5:  .long 0x06060022

! Keep progression at the requested level at progression events, before the
! subsequent section/grade/torikan checks. No movement-frame enforcement.
.global level_spawn
level_spawn:
    mov.l r1,@-r15
    config r14
    mov.w 3f,r2
    tst r2,r0
    bt 1f
    mov.l @(36,r1),r2
    mov.w 4f,r0
    mov.w r2,@(r0,r14)
    mov.l @r15+,r1
    jump 0x06006b9c,r5
1:  mov.w 4f,r0
    mov.w @(r0,r14),r2
    add #1,r2
    mov.w 4f,r0
    mov.w r2,@(r0,r14)
    mov.w @(r0,r14),r3
    exts.w r4,r2
    mov.l @r15+,r1
    jump 0x06006b94,r5
3:  .word 0x0100
4:  .word 0x0322

.global level_lines
level_lines:
    ! Retain the stock four-level cap, including TGM1/TGM2 BIG clears.
    config r14
    mov.w 3f,r2
    tst r2,r0
    bt 1f
    mov.l @(36,r1),r2
    mov.w 4f,r0
    mov.w r2,@(r0,r14)
1:  mov.l 5f,r3
    mov r10,r5
    jsr @r3
    mov r14,r4
    mov.l 6f,r2
    jsr @r2
    mov r14,r4
    jump 0x06006fee
3:  .word 0x0100
4:  .word 0x0322
    .balign 4
5:  .long 0x06011028
6:  .long 0x0601121c

.global torikan
torikan:
    config r14
    mov.w 3f,r2
    tst r2,r0
    bf 2f
    mov.w 4f,r0
    mov.b @(r0,r14),r1
    tst r1,r1
    bf 2f
    mov.w 5f,r2
    mov.w 6f,r0
    mov.l @(r0,r14),r1
    jump 0x06007024
2:  jump 0x06007038
3:  .word 0x0200
4:  .word 0x03a1
5:  .word 0x300c
6:  .word 0x0350

! Visibility helper: r14=player, r0: -1 stock, 0 show, 1 invisible, 2 fading.
! Suppress override during reveal states; r1/r2 preserved. Called by the
! existing cell renderer and once at lock setup. No second field traversal.
visibility:
    mov.l r1,@-r15
    mov.l r2,@-r15
    mov.l 4f,r1
    mov.w @r1,r0
    cmp/eq #1,r0
    bf 2f
    config r14
    mov r0,r2
    mov.l 5f,r0
    mov.l @r0,r0
    tst #4,r0
    bt 6f
    mov.l 7f,r0
    mov.l @r0,r0
    tst #128,r0
    bt 6f
    mov.l 7f,r1
    mov r0,r2
6:  mov r2,r0
    tst #128,r0
    bt 2f
    mov.w 3f,r0
    mov.b @(r0,r14),r0
    cmp/eq #7,r0
    bt 2f
    cmp/eq #9,r0
    bt 2f
    cmp/eq #10,r0
    bt 2f
    cmp/eq #11,r0
    bt 2f
    cmp/eq #13,r0
    bt 2f
    mov.l @(32,r1),r0
    bra 1f
    nop
2:  mov #-1,r0
1:  mov.l @r15+,r2
    mov.l @r15+,r1
    rts
    nop
3:  .word 0x035d
    .balign 4
4:  .long 0x06060022
5:  .long 0x06064880
7:  .long 0x060ef000

.global visible_normal
visible_normal:
    sts.l pr,@-r15
    bsr visibility
    nop
    lds.l @r15+,pr
    cmp/eq #1,r0
    bf 5f
    ! This alternate renderer has lock flash but no timed fade. Preserve its
    ! stock flash; the main gameplay renderer below handles the full M-roll.
    mov.w 6f,r2
    tst r2,r5
    bt 2f
    bra 1f
    nop
5:
    tst r0,r0
    bt 1f
    mov.w 3f,r2
    tst r2,r5
    bf 2f
1:  mov.l 4f,r2
    mov #80,r3
    mov.l r3,@-r15
    mov r11,r7
    jump 0x06016144
2:  jump 0x06016150
3:  .word 0x4000
6:  .word 0x0080
    .balign 4
4:  .long 0x06010e1c

! Main gameplay renderer (both single-player and Doubles). Preserve the stock
! flash and timed-fade branches for fresh locks. Mature ordinary stack cells
! are hidden immediately. Force-show still changes only the attribute register.
.global visible_doubles
visible_doubles:
    sts.l pr,@-r15
    bsr visibility
    nop
    lds.l @r15+,pr
    extu.w r12,r7
    cmp/eq #1,r0
    bt 2f
    tst r0,r0
    bf 1f
    mov.w 3f,r2
    bra 1f
    and r2,r7
2:  mov.w 8f,r2
    tst r2,r7
    bf 1f
    mov.w 4f,r2
    or r2,r7
1:  mov r7,r2
    tst r11,r2
    bt 5f
    mov.l 6f,r5
    mov.w 7f,r0
    mov.b @(r0,r14),r2
    jump 0x06016508,r3
5:  jump 0x06016538
3:  .word 0xafff
4:  .word 0x4000
7:  .word 0x00de
8:  .word 0x1080
    .balign 4
6:  .long 0x000a5e28

! Lock writer 0x06003d54: hoist the invariant mode-bit test into r9 once,
! replacing its eight per-cell tst r9,r3 instructions with tst r9,r9. r9 is
! otherwise only saved/restored by this leaf routine. Ordinary and BIG writers
! retain their original special-operation guards and attribute/timer stores.
! Invisible requests the canonical M-roll countdown (3), without changing
! gameplay mode or qualification. The renderer consumes it after two flashes.
.global invisible_lock
invisible_lock:
    mov.w 1f,r0
    mov.w @(r0,r4),r0
    and #16,r0
    mov r0,r9
    mov.l r14,@-r15
    sts.l pr,@-r15
    mov r4,r14
    bsr visibility
    nop
    lds.l @r15+,pr
    mov.l @r15+,r14
    cmp/eq #1,r0
    bt 7f
    cmp/eq #2,r0
    bf 2f
7:  mov r0,r9
    ! Doubles temporarily stamps the other piece with operation 1 for
    ! collision checks, then restores attributes but NOT cell+4. Do not let
    ! these stamps reset an existing settled cell's invisibility countdown.
    extu.b r5,r0
    tst r0,r0
    bt 8f
    bra 2f
    mov #0,r9
8:  mov r9,r0
    cmp/eq #1,r0
    bt 5f
    mov #16,r9
    mov.w 6f,r11
    bra 2f
    nop
5:
    mov #16,r9
    mov #3,r11
2:  mov.w 3f,r6
    mov.w 4f,r8
    mov.b @(12,r15),r0
    extu.b r0,r0
    jump 0x06003dd4,r3
1:  .word 0x030c
3:  .word 0x2000
4:  .word 0x1000
6:  .word 300

.global ghost
ghost:
    config r14
    mov.w 3f,r3
    tst r3,r0
    bt 1f
    mov.l @(44,r1),r6
    shll8 r6
    shll2 r6
    shll2 r6
    shll2 r6
    bra 2f
    nop
1:  mov.w 4f,r3
    mov.w 5f,r0
    mov.l @(r0,r14),r6
    and r3,r6
2:  mov #2,r5
    jsr @r11
    mov r14,r4
    jump 0x0600250a
3:  .word 0x0400
4:  .word 0x4000
5:  .word 0x0308

! Override qualification at its readers, without continually forging grades,
! times or qualification bookkeeping. The three consumers control locking,
! clear handling and the roll decision.
.macro qualification player
    mov.l r1,@-r15
    config \player
    mov.w 3f,r1
    tst r1,r0
    bt 1f
    bra 2f
    mov #117,r0
1:  mov.w 4f,r0
    mov.b @(r0,\player),r0
    and #117,r0
2:  mov.l @r15+,r1
    bra 5f
    nop
3:  .word 0x0800
4:  .word 0x0338
5:
.endm
.global qualify_lock
qualify_lock:
    qualification r4
    mov r0,r6
    extu.b r6,r0
    cmp/eq #117,r0
    bf 1f
    jump 0x06003db0,r2
1:  jump 0x06003db4,r2

.global qualify_clear
qualify_clear:
    qualification r14
    mov r0,r4
    mov.l @r9,r0
    tst #7,r0
    jump 0x06005118,r2

.global qualify_roll
qualify_roll:
    qualification r14
    and r5,r0
    cmp/eq #117,r0
    bf 1f
    mov #-32,r2
    jump 0x060221ac,r3
1:  jump 0x060221c0,r3

.global next_handoff
.global first_next
first_next:
    ! The opening preview is generated by player initialization, separately
    ! from 0x06005a50. Apply flags after the stock BIG-mode adjustment.
    bsr queued_flags
    nop
    ! Original initializer epilogue at 0x06001100..0x0600110a.
    add #8,r15
    lds.l @r15+,macl
    lds.l @r15+,pr
    mov.l @r15+,r8
    mov.l @r15+,r9
    mov.l @r15+,r10
    jump 0x0600110c,r1

! r14=player; r0=-1 for game logic, otherwise the active piece's latched
! variant: 0=off, 1=TGM2 (legacy value), 2=TGM1, 3=TAP. Preserve r1.
active_big:
    mov.l r1,@-r15
    mov.l 1f,r1
    mov.w @r1,r0
    cmp/eq #1,r0
    bf 2f
    mov.w 3f,r0
    mov.b @(r0,r14),r0
    extu.b r0,r0
    cmp/eq #0,r0
    bt 4f
    cmp/eq #1,r0
    bf 2f
4:  shll8 r0
    mov.l 5f,r1
    add r0,r1
    mov.l @r1,r0
    bra 6f
    nop
2:  mov #-1,r0
6:  mov.l @r15+,r1
    rts
    nop
    .balign 4
1:  .long 0x06060022
5:  .long 0x060ef040
3:  .word 0x030e

! r14=player. Return nonzero for two-column movement.
big_grid:
    sts.l pr,@-r15
    bsr active_big
    nop
    lds.l @r15+,pr
    cmp/pz r0
    bf .Lnatural_grid
    cmp/eq #2,r0
    bt .Lnormal_grid
    mov.w .Lactive_piece,r0
    mov.w @(r0,r14),r0
    mov.l r1,@-r15
    mov.w .Lbig_piece_bit,r1
    and r1,r0
    mov.l @r15+,r1
    rts
    nop
.Lnormal_grid:
    rts
    mov #0,r0
.Lnatural_grid:
    mov.w .Lgame_mode,r0
    mov.w @(r0,r14),r0
    rts
    and #64,r0
.Lactive_piece: .word 0x035e
.Lbig_piece_bit: .word 0x0200
.Lgame_mode: .word 0x030c

! The two stock BIG progression predicates use TAP normalization only.
! Preserve raw r13 for stock score/combo handling and normalized r10 for
! level/section bookkeeping. No persistent game-mode bits are forged.
big_line_rule:
    sts.l pr,@-r15
    bsr active_big
    nop
    lds.l @r15+,pr
    cmp/pz r0
    bf .Lnatural_lines
    cmp/eq #3,r0
    bf .Lordinary_lines
    rts
    mov #64,r0
.Lordinary_lines:
    rts
    mov #0,r0
.Lnatural_lines:
    mov.w .Lline_mode,r0
    mov.w @(r0,r14),r0
    rts
    and #64,r0
.Lline_mode: .word 0x030c

.global big_line_count
big_line_count:
    sts.l pr,@-r15
    bsr big_line_rule
    nop
    lds.l @r15+,pr
    tst r0,r0
    bt 1f
    extu.b r13,r4
    mov.l 2f,r3
    mov r4,r10
    jump 0x06006efc
1:  jump 0x06006f0c
    .balign 4
2:  .long 0x0603076c

.global big_line_progress
big_line_progress:
    sts.l pr,@-r15
    bsr big_line_rule
    nop
    lds.l @r15+,pr
    mov #1,r12
    extu.b r13,r4
    tst r0,r0
    bt 1f
    jump 0x06006f22
1:  jump 0x06006f72

.macro grid_branch name,big,normal,move_rotation=0
.global \name
\name:
    sts.l pr,@-r15
    bsr big_grid
    nop
    lds.l @r15+,pr
    tst r0,r0
    bt 1f
.if \move_rotation
    mov r12,r7
.endif
    jump \big
1:  jump \normal
.endm
grid_branch big_left,0x0600362c,0x06003640,1
grid_branch big_right,0x06003664,0x06003684,1
grid_branch big_spawn,0x06005c4c,0x06005c54

next_handoff:
    sts.l pr,@-r15
    bsr queued_flags
    nop
    lds.l @r15+,pr
    mov.l r1,@-r15
    config r14
    mov.w .Lbig_flag,r3
    tst r3,r0
    bt .Lrelease_big
    mov.l @(52,r1),r3
    bra .Llatch_big
    nop
.Lrelease_big:
    mov #-1,r3
.Llatch_big:
    ! Only real gameplay owns a parameter record. Avoid writes in attract.
    mov.l .Ldispatcher,r0
    mov.w @r0,r0
    cmp/eq #1,r0
    bf .Lhandoff
    add #64,r1
    mov.l r3,@r1
.Lhandoff:
    mov.l @r15+,r1
    ! Promote the already overridden queued piece. Current piece changes only
    ! on this normal handoff, so its geometry cannot change mid-fall.
    mov.w 3f,r0
    mov.w @(r0,r14),r3
    add #-2,r0
    mov.w r3,@(r0,r14)
    add #34,r0
    mov.b @(r0,r14),r2
    jump 0x06005ac0,r3
3:  .word 0x0360
.Lbig_flag: .word 0x1000
    .balign 4
.Ldispatcher: .long 0x06060022

.global next_generated
next_generated:
    sts.l pr,@-r15
    bsr queued_flags
    nop
    lds.l @r15+,pr
    ! Replay 0x06005bd4..0x06005bde, including the ITEM conditional.
    mov.w 3f,r0
    mov.w @(r0,r14),r2
    extu.w r2,r2
    tst r8,r2
    bt 1f
    mov.w 4f,r0
    jump 0x06005be0,r3
1:  jump 0x06005bea,r3
3:  .word 0x030c
4:  .word 0x0370

! Called after stock queued-piece generation and immediately before handoff.
! Preserve all live registers; modify only queued BIG and mode ITEM bits.
queued_flags:
    sts.l pr,@-r15
    mov.l r1,@-r15
    mov.l r2,@-r15
    mov.l r3,@-r15
    config r14
    mov r0,r2
    mov.w 4f,r1
    tst r1,r2
    bt 1f
    config r14
    mov.l @(52,r1),r3
    mov.w 3f,r0
    bsr set_piece_bit
    nop
1:  mov.w 6f,r1
    tst r1,r2
    bt 2f
    config r14
    mov.l @(56,r1),r3
    mov.w 8f,r0
    bsr set_piece_bit
    nop
2:  mov.l @r15+,r3
    mov.l @r15+,r2
    mov.l @r15+,r1
    lds.l @r15+,pr
    rts
    nop
3:  .word 0x0360
4:  .word 0x1000
6:  .word 0x2000
8:  .word 0x030c

! r0=player offset, r3=boolean. Preserve r2 (configuration flags).
set_piece_bit:
    tst r3,r3
    mov.w @(r0,r14),r3
    bt 1f
    mov.w 5f,r1
    or r1,r3
    bra 2f
    nop
1:  mov.w 6f,r1
    and r1,r3
2:
    mov.w r3,@(r0,r14)
    rts
    nop
5:  .word 0x0200
6:  .word 0xfdff
