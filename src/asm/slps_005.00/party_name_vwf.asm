;; =============================================================
;; vwf_glyph_map wrapper: the party-name table is dialogue text
;;
;; The name-insertion path (message codes 7 / 15 / 16 - a member's surname and
;; first name) prints through the engine's NAME stub, so every byte is looked
;; up in vwf_small_map first, whose tables hold 8x12 SMALL-FONT cells: there
;; 0xA9 is 'D' and 0xC9 is '9'. The party-name table holds DIALOGUE text
;; instead (ASCII + 0x68, like every dialogue string and like retail, whose
;; slots hold 82 4b = 南条), so while the insert pointer is inside it the byte
;; already IS a VWF character and must pass through without small-font mapping.
;; src/injection_tools/partynames.py keeps the source's case.
;;
;; Every other insert keeps the map (Persona / demon / item / arcana names and
;; the nickname are small-font cells, <FF08>/<FF09>/<FF0A>/<FF0B>/<FF0C>/
;; <FF13>). The test is the POINTER the engine is printing from - the caller's
;; s2, saved by vwf_dialog_emit at 0x18(sp) - never a mode a previous opcode
;; could leave set: the name-entry scene prints a member's surname, first name
;; and the nickname in one message (data/extracted_text/... D00), so a sticky
;; flag would corrupt the nickname behind it.
;; =============================================================
.org PARTY_NAME_VWF_ADDR
.area PARTY_NAME_VWF_SIZE

vwf_glyph_map_party:
    beqz    a1, @@other                 ; the text path: no map at all
    lw      t2, 0x18(sp)                ; vwf_dialog_emit's saved caller s2 = the pointer
    lui     t3, hi(PARTY_NAMES_ADDR)
    addiu   t3, t3, lo(PARTY_NAMES_ADDR)
    subu    t4, t2, t3
    sltiu   t4, t4, PARTY_NAMES_SIZE    ; inside the party-name table?
    bnez    t4, @@party
    nop
    j       vwf_glyph_map_small         ; one shared implementation of the map
    nop
@@party:
    jr      ra
    move    v0, a0                      ; dialogue text: the byte is the VWF character
@@other:
    j       vwf_name_map
    nop

.if SF_VWF
.include "vwf/btl_name_owner.asm"
;; The item writer invalidates ownership before copying and commits only after
;; all rows are complete. The alternate skill writer sharing this buffer clears it.
btl_item_owner_begin:
    la      at, btl_item_owner
    sb      zero, 0(at)
    j       0x800ACF14
    lui     t1, 0x800E
btl_item_owner_clear:
    la      at, btl_item_owner
    sb      zero, 0(at)
    j       0x800AD424
    addiu   t4, t4, lo(BTLP_ITEM_FULL_ADDR)
.endif
.endarea
