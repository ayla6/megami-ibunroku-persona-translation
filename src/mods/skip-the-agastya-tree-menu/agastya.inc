;; Shared by mods/skip-the-agastya-tree-menu/adv.asm and src/injection/field/sysmsg.py.
;; Retail code retired by --mods=skip-the-agastya-tree-menu: the SAVE / GAME END selector's
;; sprite setup and input code. Message relocation must not rewrite its old references
;; when the patch is on (sysmsg.py reads these declarations).
.definelabel MOD_AGASTYA_RETIRED_SELECTOR_START, 0x8009A728
.definelabel MOD_AGASTYA_RETIRED_SELECTOR_END, 0x8009A820
;; and the selector's input code in SaveTopStep (nothing else enters it)
.definelabel MOD_AGASTYA_RETIRED_TOPSEL_START, 0x8009A868
.definelabel MOD_AGASTYA_RETIRED_TOPSEL_END, 0x8009AAD0
.definelabel MOD_CARD_READY_FRAMES, 30
