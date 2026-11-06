;; =============================================================
;; Message inserts print the FULL name (ADV/DNG MsgStep cases 9-12)
;;
;; Retail points the insert at the record's ten-glyph head and sets
;; left = 10, so every English name longer than the head is cut. Each case
;; reaches the insert loop with its name base in a0 and the record id (or
;; id*stride) in a register; the patches below divert the case to a stub
;; that copies the complete, FF-terminated name into the overlay's SF_NAME_BYTES
;; scratch with the same copy helpers DrawItemName uses, then enters the
;; retail insert loop with left = 0xFF so the terminator ends the insert.
;;
;; The stubs are tail calls: they never return to the case, they jump to the
;; loop. Nothing after the case's diverted pair runs, so the displaced
;; instructions (base load, left = 10) stay dead. The insert loop reloads
;; v0/v1, so only the flags word at 0(s1) matters and the tail re-reads it.
;; `skill_name_copy`/`persona_name_copy` are resident; the item/demon copies
;; are the overlay's own (name_tails.py).
;; =============================================================

.macro sf_msg_name_stubs, item, skill, demon, persona, tail, item_copy, demon_copy, scratch, loop
;; These are tail calls: the case reached us with `j`, so ra holds nothing we
;; need, and we never return to it. The copy helper's `jal` overwrites ra and
;; MsgStep's own return address already sits in its frame, so no save is due.

;; a1 = item id (the case's jump delay slot); writes item head + tail + FF
item:
    la      a0, scratch
    jal     item_copy
    nop
    b       tail
    nop

;; a1 = skill id (delay slot); resident helper writes head + tail + FF
skill:
    la      a0, scratch
    jal     skill_name_copy
    nop
    b       tail
    nop

;; a1 = demon id (delay slot); overlay helper writes head + tail + FF
demon:
    la      a0, scratch
    jal     demon_copy
    nop
    b       tail
    nop

;; a1 = Persona id (delay slot). persona_name_copy pads to 16 glyphs with
;; zero bytes, but a space is glyph 0 too: "Cu Chulainn" must keep its inner
;; space. Strip the TRAILING pads only (the end of the last nonzero run), so
;; the FF lands after the real name; a full 16-glyph name puts it at +16.
persona:
    la      a0, scratch
    jal     persona_name_copy
    nop
    la      t0, scratch                ; scan cursor
    move    t3, t0                     ; end of the last nonzero run
    addiu   t2, t0, 16                 ; the helper's fixed field end
@@strip:
    beq     t0, t2, @@end
    lbu     v0, 0(t0)
    addiu   t0, t0, 1
    beqz    v0, @@strip
    nop
    move    t3, t0
    b       @@strip
    nop
@@end:
    li      t1, 0xFF
    sb      t1, 0(t3)
    b       tail
    nop

;; s2 = the resolved name, left = 0xFF, then the retail flags update and loop
tail:
    la      s2, scratch
    li      t0, 0xFF
    sb      t0, 0x35(s1)
    lw      v1, 0(s1)
    nop
    ori     v1, v1, 0x4001
    j       loop
    sw      v1, 0(s1)
.endmacro

;; Each case's diverted pair: the jump carries the id to a1 in its delay slot.
.macro sf_msg_name_patches, item, skill, demon, persona, p_item, p_skill, p_demon, p_persona
.org p_item
    j       item
    move    a1, v0
.org p_skill
    j       skill
    move    a1, a0
.org p_demon
    j       demon
    move    a1, a0
.org p_persona
    j       persona
    move    a1, v1
.endmacro
