;; =============================================================
;; FONT.BIN - the small-font VWF kit's resident anchor.
;;
;; FONT.BIN is loaded once at boot to 0x801E0000 and NEVER wiped or
;; overlapped - the only build-time, never-cleared, executable bytes the
;; project has. This file places the kit's sort gate into the atlas's
;; unused cells (tools/make_vwf_font.py FONT_SLOT_RUNS; run 2's last two
;; cells are reserved by that tool for the replays):
;;
;;   cell 0x667 (SF_FONT_GATE_BG)    the bg gate: load the registration
;;   cell 0x6DD (SF_FONT_GATE_FAST)  cell, check the renderer's guard
;;                                   word, jump - or fall to the replay
;;   cell 0x7FE (SF_FONT_REPLAY_BG)   [guard word][GsSortBg prologue
;;   cell 0x7FF (SF_FONT_REPLAY_FAST) replay, then the retail body]
;;   cell 0x0D2 lower half:           the two registration cells. Their
;;                                    build-time content names the
;;                                    replays, so the kit is INERT until
;;                                    an overlay's recorder rewrites them
;;                                    - and a registration SURVIVES no
;;                                    wipe, because there is no wipe
;;                                    here. OPEN.EXE and every EXE in
;;                                    EXE/ load at 0x80080000 straight
;;                                    over the overlays WITHOUT the
;;                                    game's overlay loader, so a stale
;;                                    registration names EXE bytes: the
;;                                    guard word the build places right
;;                                    before every renderer breaks the
;;                                    match and the call falls through
;;                                    to the retail replay.
;;
;; The stubs (vwf/sf_stubs.asm, in SLPS) replace the libgs sorters'
;; prologues with a jump here carrying the guard magic in t4; the replay
;; re-executes the displaced prologue and enters the retail body, so a
;; gate fail is byte-exact retail behavior.
;;
;; The kit's runtime scratch (state, row table, name scratch, battle
;; unpack buffer) lives in the game's wiped BSS (SF_*_ADDR in
;; addresses.inc): guaranteed zero at boot, re-written every frame - the
;; same clear that erases build-time data is what makes it safe for
;; runtime data.
;; =============================================================
.psx

.org SF_FONT_CELL_BG
    .word   SF_FONT_REPLAY_BG               ; pre-install: the retail replay
    .word   SF_FONT_REPLAY_FAST

;; --- the bg gate (cell 0x667, 8 words) ---
.org SF_FONT_GATE_BG
    lw      t3, -4(t0)                      ; stub supplies the registered entry
    nop                                     ; R3000 load delay before guard comparison
    bne     t3, t4, SF_FONT_REPLAY_BG            ; not kit code any more: retail path
    nop
    jr      t0
    nop

;; --- the fastbg gate (cell 0x6DD, 8 words) ---
.org SF_FONT_GATE_FAST
    lw      t3, -4(t0)
    nop
    bne     t3, t4, SF_FONT_REPLAY_FAST
    nop
    jr      t0
    nop

;; --- the replays: guard word, then the displaced sorter prologue, then
;; the retail body. The prologue's last store doubles as the jump's delay
;; slot, so the block is exactly one 32-byte atlas cell. ---
.org SF_FONT_REPLAY_BG - 4
    .word   SF_REG_MAGIC                    ; the gate's guard check reads entry-4
.org SF_FONT_REPLAY_BG
    addiu   sp, sp, -0xA8
    move    t7, a0
    sw      ra, 0xA4(sp)
    sw      s8, 0xA0(sp)
    sw      s7, 0x9C(sp)
    j       GSORT_BG_ADDR + 0x18
    sw      s6, 0x98(sp)

.org SF_FONT_REPLAY_FAST - 4
    .word   SF_REG_MAGIC
.org SF_FONT_REPLAY_FAST
    addiu   sp, sp, -0xE8                   ; GsSortFastBg's own prologue, in its order
    sw      s5, 0xD4(sp)
    move    s5, a0
    sw      ra, 0xE4(sp)
    sw      fp, 0xE0(sp)
    j       GSORT_FASTBG_ADDR + 0x18
    sw      s7, 0xDC(sp)
