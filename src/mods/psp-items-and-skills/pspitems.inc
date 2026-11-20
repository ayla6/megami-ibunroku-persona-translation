;; =============================================================
;; PSP items and skills (--mods=psp-items-and-skills): constants shared by the SLPS,
;; ADV, BTLP, DNG, S2D and OPEN.EXE parts (mod/pspitems_*.asm). Plain
;; equates, included in every build: armips takes no equ inside .ifdef.
;;
;; Clean Salt (PSP item 384) and Emergency Exit (PSP item 385) take the
;; unused item records 110 and 111 (the never-given "last" pies); Estoma
;; (PSP skill 243) takes the unused skill record 0x70 (Trafuri: no
;; Persona, demon or item uses it). Their names and descriptions come
;; from the PSP like every other row (src/extraction/psp/
;; boot_tables.py PSP_SLOTS, matching/descs_bank.tsv).
;; =============================================================

PSP_ES_ITEM     equ 110                 ; Clean Salt (0-based; the menus pass id + 1)
PSP_TR_ITEM     equ 111                 ; Emergency Exit
PSP_ES_SKILL    equ 0x70                ; Estoma (was Trafuri)
PSP_TR_SKILL    equ 0x71                ; Traesto
PSP_ITEM_NAMES  equ 0x8004442C          ; + id * 0x20 = item record name (flags word at name - 4)
PSP_SKILLS      equ 0x80047D44          ; + id * 0x14 = skill record
PSP_PERSONAS    equ 0x8004B0CC          ; + n * 0x2C = Persona record, skills at +0x20..+0x25

;; The resident state: one FONT.BIN cell (addresses.inc FONT_STATE_PSPITEMS),
;; so it survives the overlay swaps (DNG is reloaded after every battle)
;; and is shared by the dungeon and the overworld.
PSP_STATE       equ FONT_STATE_PSPITEMS
TRV_VALID       equ 0                   ; an entrance is recorded
TRV_FRESH       equ 1                   ; DNG entered: 1 from the overworld, 2 from an event / another file
TRV_PENDING     equ 2                   ; a Traesto / Emergency Exit warp is queued
TRV_FLOOR       equ 3
TRV_MAP         equ 4                   ; u16
TRV_X           equ 6
TRV_Y           equ 7
TRV_DIR         equ 8                   ; transfer-record facing (0x801F5355)
TRV_ES_TIMER    equ 9                   ; Clean Salt / Estoma: moon phases left
TRV_ES_DONE     equ 10                  ; Clean Salt: show "wore off" next
TRV_LAST        equ 11                  ; last dungeon map seen by the field handler + 1 (0 = none)
TRV_LOADED      equ 12                  ; set by Continue on a dungeon save (mods/psp-items-and-skills/open.asm)
TRV_SAVED       equ 12                  ; bytes 0..11 go into memory-card saves
TR_SAVE_MAGIC   equ 0x54                ; location sector + 0x18: an entrance record follows

ES_PHASES       equ 16                  ; moon phases (16 steps each): Liftoma's duration
ES_FORMATIONS   equ 0x168               ; battle formations (src/mods/psp-items-and-skills/estoma.py)
ES_PARTY        equ 0x801F256C          ; party list (member index, 0xFF = empty)
ES_MEMBERS      equ 0x801F1BCC          ; battle structs, 0x60 bytes
ES_LEVEL        equ 0x4B

;; the dungeon (mods/psp-items-and-skills/dng.asm)
TR_STATE_PTR    equ 0x800A0D70          ; -> dungeon state (0x801F0000): +0x15A0 map, +0x15A2 floor, +0x15A4 x, +0x15A6 y, +0x15A7 facing
TR_MAP_KAMA     equ 0x0F                ; Kama Palace
TR_MAP_MANA     equ 0x12                ; Mana Castle
ES_CORE_SHIELD  equ 0x12

;; the overworld (mods/psp-items-and-skills/s2d.asm)
S2D_ZONE_PTR    equ 0x800B0A84          ; -> the zone record: 30 u16 formation ids
S2D_PENDING     equ 0x800B9C18          ; "battle pending"

;; a Persona's skill slot (1-6), mods/psp-items-and-skills/slps.asm
.macro psp_persona_skill, persona, slot, skill
.org PSP_PERSONAS + persona * 0x2C + 0x20 + slot - 1
    .byte skill
.endmacro
