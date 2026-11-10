;; =============================================================
;; QoL (separate enhancement build): the battle debug menu (BTLP.BIN).
;;
;; BtlDebugMenu (references/persona-decomp src/btlp/debugmenu.c) is the
;; fifteen-row debug page. Retail only reaches it through BtlCheatWatch
;; (src/btlp/cheat.c): the party leader's eight-byte battle name must
;; match the kana string しんけたがるべよ, then the second pad has to
;; enter a ten-press sequence, which flips g_btl_debug_hud; only then
;; does BtlOrdersMenu open the page instead of the orders menu while
;; Cancel is held.
;;
;; The translation build's name entry is ABC-only (name/abc_only.asm),
;; so the kana name can never be typed and the retail key is dead on
;; every translated disc. This patch replaces the whole key with a
;; fresh Start press on either pad: the debug page opens straight away,
;; with no name and no Cancel gate, and no dependency on the debug HUD
;; flag (so Start does not also become the round-end key).
;;
;; Addresses are this project's first-pressing BTLP.BIN (data/psx):
;;   BtlDrawFrame     0x80080F14   BtlCheatWatch  0x8008F05C
;;   BtlDebugMenu     0x800A0CF8   g_btl_closing  0x800CF074
;;   g_btl_pad1_edge  0x800F88F0   g_btl_pad2_edge 0x800F88F4
;;
;; BtlCheatWatch's only call is at the top of BtlDrawFrame
;; (0x80080F24); it is nop'd and its body becomes the tail stub. The
;; stub is reached from BtlDrawFrame's epilogue (0x80081358) after
;; BtlPadRead has refreshed the edges and after the frame counter has
;; been flipped. It opens the page only when the battle is not closing,
;; and a busy byte keeps the page's own BtlDrawFrame calls from opening
;; it again. Reaching the stub from the top of the frame would unwind
;; BtlDrawFrame early, which is why the call is removed rather than
;; reused.
;;
;; BtlDebugMenu's own step machine lives in g_btl_step, the same byte
;; the battle's order and command stages use. Retail only reaches the
;; page from a state where that byte is PICK (0), so a Start press at
;; any other point would enter the page halfway through - on DONE (2)
;; it returns before drawing anything, and on ACT (1) it runs a row
;; that was never picked. The stub therefore puts the byte on PICK for
;; the page and hands the battle's value back when the page returns.
;; =============================================================
.definelabel btl_debug_cheat_call, 0x80080F24   ; jal BtlCheatWatch
.definelabel btl_debug_frame_tail, 0x80081358   ; lw ra, 0x1C(sp) in BtlDrawFrame's epilogue
.definelabel btl_debug_menu,       0x800A0CF8   ; BtlDebugMenu
.definelabel btl_debug_closing,    0x800CF074   ; g_btl_closing
.definelabel btl_debug_step,       0x800CF06B   ; g_btl_step (BtlDebugMenu's DEBUG_STEP_*)
.definelabel btl_debug_stub,       0x8008F05C   ; BtlCheatWatch's body
.definelabel btl_debug_busy,       0x8008F130   ; a byte past this stub, inside the dead function
.definelabel PAD_START,            0x0800

.org btl_debug_cheat_call
    nop                                         ; was jal BtlCheatWatch
    nop                                         ; was (and stays) the delay-slot nop

.org btl_debug_frame_tail
    j       btl_debug_stub
    nop                                         ; the epilogue is repeated in the stub

.org btl_debug_stub
.area btl_debug_busy - btl_debug_stub
    la      s0, btl_debug_busy                  ; s0 is restored from the frame below
    lbu     v0, 0(s0)
    nop
    bnez    v0, @@done                          ; a BtlDebugMenu frame: do not open it again
    nop
    lui     v0, 0x800D
    lbu     v0, -0xF8C(v0)                      ; g_btl_closing
    nop
    bnez    v0, @@done
    nop
    lui     v0, 0x8010
    lhu     v1, -0x7710(v0)                     ; g_btl_pad1_edge
    lhu     v0, -0x770C(v0)                     ; g_btl_pad2_edge
    nop
    or      v1, v1, v0
    ori     v0, zero, PAD_START
    and     v1, v1, v0
    beqz    v1, @@done
    nop
    lui     v0, 0x800D
    lbu     v1, -0xF95(v0)                      ; the battle's g_btl_step
    nop
    sb      v1, 1(s0)                           ; keep it while the page owns the byte
    sb      zero, -0xF95(v0)                    ; the page starts on its PICK step
    li      v0, 1
    sb      v0, 0(s0)
    jal     btl_debug_menu
    nop
    lbu     v1, 1(s0)                           ; the page leaves its DONE step behind
    lui     v0, 0x800D
    sb      v1, -0xF95(v0)                      ; give the battle its step back
    sb      zero, 0(s0)
@@done:
    lw      ra, 0x1C(sp)                        ; BtlDrawFrame's epilogue
    lw      s0, 0x18(sp)
    addiu   sp, sp, 0x20
    jr      ra
    nop
.endarea

.org btl_debug_busy
    .byte 0                                     ; "not inside the page" at battle start
