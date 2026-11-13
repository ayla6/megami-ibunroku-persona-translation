;; =============================================================
;; Address definitions and filename constants - single source of truth
;; Naming: OVERLAY_FUNCTION_PURPOSE_ADDR for addresses
;;         OVERLAY_FILENAME / OVERLAY_OUTPUT for binary filenames
;; Suffixes: _LUI_ADDR (pointer load), _WIDTH_ADDR, _COLUMN_ADDR
;; =============================================================

;; PS-X EXE files carry a 0x800-byte header before t_addr.
;; .open base = t_addr - header so file offset 0 lines up.
PSX_EXE_HEADER_SIZE equ 0x800

;; Shared overlay slot. ADV/BTLP/CASINO/DNG/S2D/NAME.BIN all load here;
;; file offset 0 is the overlay ID word. Runtime-confirmed for ADV.BIN
;; (99.6% of words match RAM); assumed identical for the others.
OVERLAY_SLOT_ADDR equ 0x800643C4

;; --- SLPS_005.00 - Main executable (resident), t_addr 0x80010000 ---
SLPS_FILENAME equ "../../data/psx/SLPS_005.00"
SLPS_OUTPUT equ "../../build/SLPS_005.00"
SLPS_ADDR equ 0x80010000 - PSX_EXE_HEADER_SIZE
;; Free space: zero padding at the end of the EXE's data.
; WARNING: NOT free at runtime - 0x80055C34 is the CD-ready flag (hangs the game if overwritten). Do not use.
SLPS_FREE_START equ 0x80055C10
SLPS_FREE_END equ 0x80056000
;; The image does NOT grow past its retail end: t_size stays 0x46000. The
;; game's init WIPES its BSS above the image (0x80056000..0x8005E760+) with
;; a blanket clear at boot, and the BIOS itself keeps live boot state in the
;; last KBs below 0x8005CD74 - a bigger t_size both erased build-time data
;; placed there and froze the boot before the game loaded (both proven on
;; emulated sessions; see the smallfont kit history). NOTHING may be
;; appended to SLPS_005.00.
SLPS_IMAGE_RETAIL_END equ 0x80056000
SLPS_IMAGE_END equ SLPS_IMAGE_RETAIL_END
SLPS_IMAGE_LIMIT equ SLPS_IMAGE_END
;; --- the small-font VWF kit's resident anchor lives in FONT.BIN ---
;; FONT.BIN is loaded once at boot to 0x801E0000 (0x10000 bytes), is never
;; wiped, never overlapped, and stays resident while overlays and EXEs swap.
;; Its atlas has 2048 32-byte cells. The gate, replay and registration
;; addresses below own parts of the unused FONT_SLOT_RUNS; the font allocator
;; subtracts these ranges and checks every other retail atlas cell after build.
;; These are build-time, never-wiped executable bytes:
SF_FONT_GATE_BG equ 0x801ECCE0              ; cell 0x667: load cell, guard-check, jump
SF_FONT_GATE_FAST equ 0x801EDBA0            ; cell 0x6DD: same, fastbg
SF_FONT_REPLAY_BG equ 0x801EFFC4            ; cell 0x7FE: the ENTRY (first instruction); the
SF_FONT_REPLAY_FAST equ 0x801EFFE4          ; guard word sits at entry-4 - cell 0x7FF likewise.
                                            ; (Off-by-one-word here executed the magic as an
                                            ; instruction: ReservedInstruction at 0x801effc0.)
SF_FONT_CELL_BG equ 0x801E1A50              ; cell 0x0D2 lower half: registration cells
SF_FONT_CELL_FAST equ 0x801E1A54            ; (pre-install = the replay addresses; the
                                            ; recorder overwrites them per overlay)
GS_DRAW_OFS_X_ADDR equ 0x8005E63C           ; signed libgs sprite-coordinate offset
GS_DRAW_OFS_Y_ADDR equ 0x8005E640
GSORT_BG_ADDR equ 0x8003235C               ; GsSortBg (retail libgs in SLPS; ADV/S2D/NAME call it)
GSORT_FASTBG_ADDR equ 0x8003F554           ; GsSortFastBg (the map sorter; DNG's two field jal sites
                                            ; land here). NOT 0x800333A4: that is the generic OT
                                            ; append helper (packet, ot, pri, len) every sprite sort
                                            ; calls - hooking it fed it GsBG arguments.
;; The small-font row tables and name scratch are loaded with each overlay;
;; vwf/smallfont_defs.asm defines their sizes, the wrappers own their placement.
;; --- story-battle spill (btlp.py / btlp/btlevt_unpack.asm) ---
;; A battle message whose ENGLISH does not fit its own slot puts 'FF 00 hi lo'
;; in the slot and its text in BTLP's own dead space (BTLEVT_SPILL_ADDR:
;; build-time strings, read only while BTLP is the live overlay), and the
;; string being drawn unpacks into the resident buffer below - RUNTIME
;; scratch in the game's wiped BSS (proven safe while battles draw; the
;; buffer's whole content is rewritten per draw).
BTLEVT_BUF_ADDR equ 0x80057400
BTLEVT_BUF_SIZE equ 1024                    ; the string the unpacker is drawing
;; Runtime scratch in the unused tail of the resident CD path-table cache.
;; build_disc.py checks the disc's complete path-table entry count against the
;; first scratch byte (BTLEVT_BUF_ADDR), so neither buffer can overwrite a
;; live directory record. The CD sector buffer starts at 0x80058018.
;; Each compositor cell is initialized before use.
VWF_DLG_RING_ADDR equ BTLEVT_BUF_ADDR + BTLEVT_BUF_SIZE
VWF_DLG_RING_LIMIT equ 0x80057E00
BTL_SECOND_BUF_ADDR equ VWF_DLG_RING_LIMIT
BTL_SECOND_BUF_SIZE equ 512                ; second battle window, before CD sector buffer
;; the spill strings: dead SLPS fragments (deadfuncs.py 16; the only
;; build-time homes left in the image - the guard in btlp.py fails the
;; build when the wording outgrows them and more fragments must be found)
BTLEVT_SPILL_ADDR equ 0x80018D40            ; fragment 44B (deadfuncs.py)
BTLEVT_SPILL_END equ 0x80018D6C
BTLEVT_SPILL2_ADDR equ 0x8001B2CC           ; fragment 44B
BTLEVT_SPILL2_END equ 0x8001B2F8
BTLEVT_SPILL3_ADDR equ 0x80024E94           ; fragment 44B
BTLEVT_SPILL3_END equ 0x80024EC0
BTLEVT_SPILL4_ADDR equ 0x800269C8           ; fragment 36B
BTLEVT_SPILL4_END equ 0x800269EC
;; --- per-overlay small-font kit data (the overlays swap as wholes; the
;; state is per-overlay and freshly zero at every load) and the per-overlay
;; full-name blocks (tails + copy code, read only while their overlay is
;; the live one) ---
ADV_SF_DATA_ADDR equ 0x800BD240            ; state + advance table + affinity pool, loaded
                                           ; with ADV.BIN (past the sysmsg spill)
;; ADV packs state, widths/pool, names, code, table and scratch under one
;; sector-safe ceiling. DNG/S2D reserve a fixed data window for
;; state/widths/pool; their loaded names, row table and scratch follow it.
;; The window must hold state + advance table + the whole affinity pool; the
;; pool grows with the English wording, so the reservation carries headroom.
;; smallfont.asm asserts the literal ITEM_DATA_ADDRs below keep this width.
SF_DATA_WINDOW equ 0x1000                  ; state + widths + affinity pool
ADV_SF_EXTENSION_END equ 0x800BFBC4       ; largest sector-safe end below work area 0x800C0000
DNG_SF_DATA_ADDR equ 0x800B3000            ; past the dungeon-script glue
DNG_ITEM_DATA_ADDR equ 0x800B4000          ; DNG_SF_DATA_ADDR + SF_DATA_WINDOW
DNG_ITEM_DATA_END equ 0x800C0000
S2D_SF_DATA_ADDR equ 0x800BC200            ; past the extension glue
S2D_ITEM_DATA_ADDR equ 0x800BD200          ; S2D_SF_DATA_ADDR + SF_DATA_WINDOW
S2D_ITEM_DATA_END equ 0x800E0000           ; S2D's work-area bias ceiling

;; --- FONT.BIN (resident at 0x801E0000, loaded once at boot) ---
FONT_FILENAME equ "../../data/psx/FONT.BIN"
FONT_OUTPUT equ "../../build/FONT.BIN"
FONT_GLYPHS_ADDR equ 0x801E0000
FONT_IMAGE_LIMIT equ 0x801F0000

;; --- VWF engine home: unreferenced SLPS_005.00 functions (tools/deadfuncs.py) ---
;; Verified: no jal/j, address word or lui pair to them on the disc, and no
;; hits from execution breakpoints in title, event, name entry, field and
;; hospital save states.
VWF_CODE_A_ADDR equ 0x8002E7BC           ; 0x8002E7BC + 0x8002E7FC
VWF_CODE_A_SIZE equ 0x8002EAA8 - VWF_CODE_A_ADDR
VWF_CODE_B_ADDR equ 0x800121B0           ; 4 functions
SF_TAB_HELPER_ADDR equ 0x80011C40         ; resident tab-stop helper, formerly choice spill
SF_TAB_HELPER_END equ 0x80011CA0
VWF_CODE_B_SIZE equ 0x80012484 - VWF_CODE_B_ADDR
VWF_DATA_ADDR equ 0x80021848             ; 2 functions
VWF_DATA_SIZE equ 0x138                  ; 0x80021980 - VWF_DATA_ADDR: stops before the party/name-owner code
VWF_TABLE_ADDR equ 0x8001D8D4            ; 2 functions
VWF_TABLE_SIZE equ 0x8001DAA4 - VWF_TABLE_ADDR
VWF_BTLP_CODE_ADDR equ 0x800124B4        ; 1 dead function (328 bytes)
VWF_BTLP_CODE_SIZE equ 0x800125FC - VWF_BTLP_CODE_ADDR
VWF_BTLP_CODE2_ADDR equ 0x8001EE84       ; dead fragment (284 bytes)
VWF_BTLP_CODE2_SIZE equ 0x8001EFA0 - VWF_BTLP_CODE2_ADDR
;; Party full names (src/injection_tools/partynames.py): 18 slots of 10 bytes -
;; the company, the protagonist's placeholder, then eight family / given pairs.
;; The name-insertion path must tell this table's DIALOGUE text apart from the
;; small-font cells of every other insert, so vwf_glyph_map's entry is a jump
;; to the wrapper below (it tests the insert pointer against this range).
PARTY_NAMES_ADDR equ 0x80049040
PARTY_NAMES_SIZE equ 0xB4                 ; 18 * 10
PARTY_NAME_VWF_ADDR equ 0x80021980        ; unreferenced SLPS function (tools/deadfuncs.py, unclaimed)
PARTY_NAME_VWF_SIZE equ 0x80021AB8 - PARTY_NAME_VWF_ADDR
VWF_STATE_ADDR equ 0x800155E4             ; spare tail of the dead vwf_name_map run: vwf_dlg_state
VWF_NAME_CODE_ADDR equ 0x80015510        ; dead function (252 bytes): vwf_name_map (typed names -> narrow English)
VWF_NAME_CODE_SIZE equ 0x8001560C - VWF_NAME_CODE_ADDR
;; small-font VWF kit (adv/dng/s2d/smallfont.asm, engine vwf/smallfont.asm)
;; - placement rules. Nothing may sit where the game writes: the SLPS
;; "free space" at 0x80055C10 is the CD-system's (g_cd_busy, overwrite
;; it and the game hangs), the appended SLPS region below the verified
;; span must stay ZERO (the Psy-Q CD subsystem's globals and directory
;; cache - see the SLPS section above), and the overlay images carry
;; live state of their own (ADV's image-upload queue is at 0x800BC714,
;; its CD-buffer table at the file's end). So: the recorder, the
;; renderer AND this overlay's config go in dead functions per overlay
;; (tools/deadfuncs.py - no call, no pointer word and no lui/addiu pair
;; on the disc names them; the config is the renderer run's first 0x20
;; bytes), the per-frame packet buffers in the decomp-verified gap
;; between g_menu_cells and bg_map0 (ADV/DNG 0x800E6400, S2D
;; 0x80106400). Never wiped: FONT.BIN's reserved cells hold the
;; registration words, the sort gate and the retail replays
;; (vwf/sf_font.asm); SLPS holds the two sorter entry jumps
;; (vwf/sf_stubs.asm). State, row tables and name scratch belong to each
;; overlay's loaded extension and are zero at load. ADV also packs its
;; recorder/renderer there; DNG/S2D retain their verified code slots.

;; --- ADV.BIN - Overlay #7: field / events ---
ADV_FILENAME equ "../../data/psx/ADV.BIN"
ADV_OUTPUT equ "../../build/ADV.BIN"
ADV_ADDR equ OVERLAY_SLOT_ADDR
ADV_IMAGE_LIMIT equ ADV_SF_EXTENSION_END
ADV_EOF_ADDR equ ADV_ADDR + 0x58D04          ; end of the retail overlay image (past the live CD-buffer table)
;; dialogue text interpreter (0x800669AC) - runtime-verified
ADV_TEXT_STATE equ 0x800E1E4C              ; +0xA u16 pos (cell 0-59), +0xC read ptr
;; MsgStep pacing (vwf/msg_pace.asm): the prologue run it reuses, the clut
;; RECT and slot table that run handled, the step labels and the three glyph
;; tails. Glyphs per call = the frame's vsyncs (ADV and S2D 30 fps: 2).
ADV_MSG_TOP equ 0x800669C8
ADV_MSG_TOP_END equ 0x80066A20
ADV_MSG_RECT equ 0x800643C8
ADV_MSG_SLOTS equ 0x800EB14C
ADV_MSG_NEXT equ 0x80066C50
ADV_MSG_DONE equ 0x800678C8
ADV_MSG_TEXT_TAIL equ 0x8006786C
ADV_MSG_SUB_TAIL equ 0x8006788C
ADV_MSG_INSERT_TAIL equ 0x80066E30
ADV_MSG_PACE equ 2
ADV_CELL_ACTIVATE equ 0x80067908           ; void(u16 pos)
ADV_UPLOAD_COUNT equ 0x800BC714            ; LoadImage queue count
ADV_UPLOAD_QUEUE equ 0x800BC748            ; LoadImage queue entries
ADV_FLUSH_UPLOADS equ 0x80068414           ; FlushImageUploads (imagequeue.c)
;; --- ADV.BIN extension partition -------------------------------------------
;; sysmsg's overflow strings, then the small-font kit's own data block
;; (state, advance table, affinity pool - *_SF_DATA_ADDR) and the
;; full-name block (*_ITEM_DATA_ADDR). The game's work area (GsSetWorkBase
;; 0x800C0000, OT tags 0x800D6000/0x800D9000) is live above it, so
;; 0x800C0000 is the ceiling; BTLP's fx code occupies 0x800BD330+ only
;; while BTLP is resident, and the spill strings are ADV's own extension.
ADV_EXT_BASE equ 0x800BD100                ; past the live CD-buffer table at 0x800BD0C8; gdb (menu open): file bytes survive from here
ADV_SYSMSG_SPILL_ADDR equ 0x800BD100       ; sysmsg.py overflow strings (build/sysmsg.asm)
ADV_SYSMSG_SPILL_END equ 0x800BD224        ; above the bar's advance hook (0x800BD1F4..0x800BD224,
                                           ; adv/bar.asm): sysmsg keeps 49 bytes of growth room
                                           ; below the hook. The 28-byte gap 0x800BD224..0x800BD240
                                           ; after the spill end now holds ADV_BAR_LIST.
ADV_SYSMSG_SPILL_SIZE equ ADV_SYSMSG_SPILL_END - ADV_SYSMSG_SPILL_ADDR
;; small-font VWF line (adv/smallfont.asm: recorder + renderer; vwf/sf_font.asm: the resident gate)
ADV_SF_HOOK_ADDR equ 0x80067C00            ; TileMapWriteRow loop entry: la t0,cfg / j sf_record
ADV_SF_MAP_BASE equ 0x800E3E4C             ; the text map's cell base (CellsInit atlas)
;; DrawSpellName (adv/draw_spell.asm): the spell-list row reads the full
;; skill name from the kit's scratch instead of the ten-glyph record head.
ADV_DRAW_SPELL_NAME equ 0x8007BA94         ; rewritten in place (0xBC bytes avail)
ADV_TILEMAP_FILLRECT equ 0x80067CEC        ; TileMapFillRect(dst, value, w, h, [sp]=stride)
ADV_SPELL_RULE_GLYPHS equ 0x800B2F74       ; the eight-glyph rule under an empty slot
ADV_SF_CENTER_ADDR equ 0x800AADE8          ; unreferenced ADV function (deadovl.py)
ADV_SF_CENTER_END equ 0x800AAE5C
;; --- persona status/fusion bottom bar: VWF sprite cells (adv/bar.asm) ---
;; The bar is one slot whose cel list names TWO rows, retail's layout: the
;; arcana block (10 cells, dx=0, dy=0) and a new-line name block (16 cells,
;; dx=0x58, dy=4 - the retail name entry's own dx/dy, which put the name on
;; a second line right of the arcana). adv/cells_row.asm rewrites
;; CellsWriteRow in place so every cell also carries its glyph's advance in
;; the +3 byte (the cba high byte, which the slot renderer never reads), and
;; sf_cell_adv - hung on the slot renderer's per-cell pen advance in ADV only -
;; applies it while the entry's unread pad halfword marks the row. Persona
;; names are persona_name_copy'd straight into the name cells, so the writer
;; reads the full name in place; the retail 10-byte record head never reaches
;; the bar.
;;
;; The rows keep retail's own homes: the arcana block at 0x800B20B4 and the
;; name header at 0x800B210C, whose cells grow from ten to sixteen over the
;; retail cel list at 0x800B2164 (the list moves to the sysmsg gap at
;; ADV_BAR_LIST) and over the 1x1 slot-0x20 block at 0x800B2188 (moved to the
;; image tail after the small-font extension, adv/bar.asm). g_fm_mark_pos at 0x800B209C - the status
;; screen's five member-marker positions - is retail data read by every
;; marker site and is never written by the bar.
SF_BAR_MARK        equ 0x5342              ; the cel-entry pad halfword that marks a VWF row
;; The list lives in the 28-byte gap between the advance hook and sf_state_adv.
ADV_BAR_LIST       equ 0x800BD224          ; two entries {block, dx, dy, z, mark} + FF (0x1C),
                                           ; the retail list retargeted here (its old home is
                                           ; covered by the grown name cells)
ADV_BAR_ARCANA_BLOCK equ 0x800B20B4        ; retail header: cols 10, rows 1, w 8, h 12
ADV_BAR_CELLS      equ 0x800B20BC          ; retail: the 10 arcana cells (ends 0x800B210C)
ADV_BAR_NAME_BLOCK equ 0x800B210C          ; retail name header, rewritten to cols 16
ADV_BAR_NAME_CELLS equ 0x800B2114          ; the 16 name cells (ends 0x800B2194)
ADV_MENU_TOP_LIST  equ 0x800B2198          ; slot 0x20's cel list (retail home); its block word
                                           ; is repointed at the image tail (adv/bar.asm)
ADV_BAR_HOOK       equ 0x800BD1F4          ; sf_cell_adv, 48 bytes (sysmsg's ceiling moved for it)
ADV_BAR_HOOK_END   equ 0x800BD224
ADV_CELLS_ROW      equ 0x8008F730          ; CellsWriteRow, rewritten in place (cells_row.asm)
ADV_CELLS_CLEAR    equ 0x8008F5B4          ; CellsClear (retail, unchanged)
ADV_KIND_LABELS    equ 0x800B24A4          ; g_kind_labels: 22 FF-padded 10-byte entries
ADV_BAR_SLOT_INIT  equ 0x8006FB04          ; the status layout's list pointer (lui/addiu pair)
ADV_BAR_ADV_SITE   equ 0x80065C64          ; SlotsRenderAll's per-cell pen advance (jal + nop)
ADV_STATUS_NAMES   equ 0x80070144          ; StatusPersonaNames, rewritten in place (0xC0 bytes)
ADV_FUSE_CLEAR1    equ 0x8009F900          ; fusion draw helper: kind/name clears
ADV_FUSE_SITE_A    equ 0x8009FB40          ; name+kind write, built-def path (s3 = def)
ADV_FUSE_SITE_B    equ 0x8009FE38          ; name+kind write, built-persona path (s4 = Persona)
;; --- ADV's card page (adv/pdata.asm): the Velvet Room card list's race+name bar ---
;; The page's two retail blocks are fixed at ten cells (name) and six (race);
;; the name block sits immediately before the page's cel list, so it cannot
;; grow in place. The name row instead reuses the status bar's sixteen-cell
;; block (adv/bar.asm); the race block and the cel list stay where retail put
;; them, and the page's old ten-cell block becomes the name-row helper. The
;; page and the status screen are separate layouts (slot 0x1E points at each
;; screen's own list), so the shared block is always rewritten by the draw
;; that uses it before the slot renderer reads it.
ADV_PDATA_RACE_BLOCK equ 0x800BA080        ; retail header: cols 6, rows 1 (kept)
ADV_PDATA_RACE_CELLS equ 0x800BA088        ; the 6 race cells (kept)
ADV_PDATA_CEL_LIST  equ 0x800BA110         ; retail's two-entry cel list (28 bytes)
ADV_PDATA_NAME_BLOCK equ ADV_BAR_NAME_BLOCK ; the shared 16-cell name block
ADV_PDATA_NAME_CELLS equ ADV_BAR_NAME_CELLS
ADV_PDATA_NAME_COLS equ 16
ADV_PDATA_BAR       equ 0x800BA0B8         ; pdata_bar_adv: the full name row (old 10-cell block)
ADV_PDATA_BAR_END   equ 0x800BA110
ADV_PDATA_RACE_TABLE equ 0x800B23C0        ; 26 six-byte race labels (1-based)
ADV_PDATA_TAIL      equ 0x80099014         ; PersonaDataDraw's bar tail (0x70 bytes)
ADV_PDATA_TAIL_END  equ 0x80099084

;; --- the same bar in DNG.BIN (dng/bar.asm): one status screen, no fusion ---
;; DNG's hint table (0x8009AB90, twenty bytes) is read from SEVENTEEN sites,
;; so it stays put and the bar's rows move out to the image tail instead; the
;; old span's blocks and list are dead bytes. The layout below the image end
;; rides the same grow-by-sectors rule as the DNG extension.
DNG_BAR_LIST       equ 0x800B5610          ; two entries {block, dx, dy, z, mark} + FF (0x1C),
                                           ; after the hook; 0x54D0..0x54E8 is the name scratch
DNG_BAR_ARCANA_BLOCK equ 0x800B5500        ; header: cols 10, rows 1, w 8, h 12
DNG_BAR_CELLS      equ 0x800B5508          ; the 10 arcana cells (ends 0x800B5558)
DNG_BAR_NAME_BLOCK equ 0x800B5558          ; header: cols 16, rows 1
DNG_BAR_NAME_CELLS equ 0x800B5560          ; the 16 name cells (ends 0x800B55E0)
DNG_BAR_HOOK       equ 0x800B55E0          ; sf_cell_adv_dng, 48 bytes
DNG_BAR_HOOK_END   equ 0x800B5610
DNG_CELLS_ROW      equ 0x8009392C          ; DNG CellsWriteRow, rewritten in place
DNG_CELLS_CLEAR    equ 0x800937B0          ; DNG CellsClear (retail, unchanged)
DNG_KIND_LABELS    equ 0x8009AF94          ; g_kind_labels (same records as ADV)
DNG_BAR_SLOT_INIT  equ 0x8007EE34          ; the status layout's list pointer (lui/addiu pair)
DNG_BAR_ADV_SITE   equ 0x80075B54          ; SlotsRenderAll's per-cell pen advance (jal + nop)
DNG_STATUS_NAMES   equ 0x8007F464          ; DNG StatusPersonaNames, rewritten in place (0xC0 bytes)
;; --- the dungeon menu's Persona Data page (dng/pdata.asm) ---
;; The page's skill rows and its race+demon-name bar are sprite/tilemap rows
;; that retail drew with fixed ten-cell fields. DrawSpellName is rewritten in
;; place to hand the recorder the full skill name; the bar's two cel-list
;; entries are marked for the same advance hook as the status bar and its
;; name block grows to twenty cells in the image extension (the retail
;; ten-cell block sits in front of the list and cannot grow). The block
;; follows the status bar's list at the current image end; the helper code
;; follows it, still below the sector-safe extension ceiling.
DNG_PDATA_RACE_BLOCK equ 0x8009D300        ; retail header: cols 6, rows 1 (kept)
DNG_PDATA_RACE_CELLS equ 0x8009D308        ; the 6 race cells (kept)
DNG_PDATA_CEL_LIST equ 0x8009D390          ; the page's two-entry cel list (retail dx/dy kept)
DNG_PDATA_NAME_BLOCK equ 0x800B562C        ; header: cols 20, rows 1
DNG_PDATA_NAME_CELLS equ 0x800B5634        ; the 20 name cells (ends 0x800B56D4)
DNG_PDATA_NAME_COLS equ 20
DNG_PDATA_BAR      equ 0x800B56E0          ; dng_pdata_bar: both VWF rows
DNG_PDATA_BAR_END  equ 0x800B5800
DNG_PDATA_EXT_LIMIT equ 0x800B5BC4         ; the last sector's safe end (grow-by-sectors)
DNG_PDATA_RACE_TABLE equ 0x8009AEB0        ; 26 six-byte race names
DNG_PDATA_TAIL     equ 0x800998F8          ; PersonaDataDraw's bar tail (0x70 bytes)
DNG_PDATA_TAIL_END equ 0x80099968
DNG_DRAW_SPELL_NAME equ 0x8008A8A4         ; DNG DrawSpellName, rewritten in place (0xC0)
DNG_TILEMAP_FILLRECT equ 0x80077918        ; TileMapFillRect(dst, value, w, h, [sp]=stride)
DNG_SPELL_RULE_GLYPHS equ 0x8009BA64       ; the eight-glyph rule under an empty slot
;; --- the same bar in S2D.BIN (s2d/bar.asm): the overworld menu's status page ---
;; S2D holds its own compiled copy of the status bar (that copy is what the
;; overworld save's status page used, so it still drew retail fixed-width
;; cells). Mirror the DNG layout: the retail list points at the two old
;; 10-cell blocks at 0x8009D734/0x8009D78C; the new pair + hook ride the
;; image extension past every generated block (0x800BE800, well below the
;; 0x800E0000 work-area ceiling and inside the last image sector).
S2D_BAR_LIST       equ 0x800BE800          ; two entries {block, dx, dy, z, mark} + FF (0x1C)
S2D_BAR_ARCANA_BLOCK equ 0x800BE820        ; header: cols 10, rows 1, w 8, h 12
S2D_BAR_CELLS      equ 0x800BE828          ; the 10 arcana cells (ends 0x800BE878)
S2D_BAR_NAME_BLOCK equ 0x800BE878          ; header: cols 16, rows 1
S2D_BAR_NAME_CELLS equ 0x800BE880          ; the 16 name cells (ends 0x800BE900)
S2D_BAR_HOOK       equ 0x800BE900          ; sf_cell_adv_s2d, 48 bytes
S2D_BAR_HOOK_END   equ 0x800BE930
S2D_CELLS_ROW      equ 0x80083A64          ; S2D CellsWriteRow, rewritten in place (0xC0)
S2D_CELLS_CLEAR    equ 0x800838E8          ; S2D CellsClear (retail, unchanged)
S2D_KIND_LABELS    equ 0x8009DB24          ; g_kind_labels (same records as ADV/DNG)
S2D_BAR_SLOT_INIT  equ 0x8006EC2C          ; status preview's slot 0x1E list pointer
S2D_BAR_ADV_SITE   equ 0x80065744          ; SlotsRenderAll's per-cell pen advance
S2D_STATUS_NAMES   equ 0x8006F26C          ; S2D StatusPersonaNames, rewritten in place (0xC0)
;; --- the Persona Data page's race + demon-name bar (s2d/pdata.asm) ---
;; The overworld menu's PersonaDataDraw copy keeps retail's six-cell race
;; block and two-entry cel list. Retail's ten-cell name block
;; (0x8009FEC8..0x8009FF20) becomes the name-row helper; the list's name
;; entry points at the shared sixteen-cell status block instead.
S2D_PDATA_RACE_BLOCK equ 0x8009FE90        ; retail header: cols 6, rows 1 (kept)
S2D_PDATA_RACE_CELLS equ 0x8009FE98        ; the 6 race cells (kept)
S2D_PDATA_CEL_LIST  equ 0x8009FF20         ; retail's two-entry cel list (28 bytes)
S2D_PDATA_NAME_BLOCK equ S2D_BAR_NAME_BLOCK ; the shared 16-cell name block
S2D_PDATA_NAME_CELLS equ S2D_BAR_NAME_CELLS
S2D_PDATA_NAME_COLS equ 16
S2D_PDATA_BAR       equ 0x8009FEC8         ; pdata_bar_s2d: the full name row (old 10-cell block)
S2D_PDATA_BAR_END   equ 0x8009FF20
S2D_PDATA_RACE_TABLE equ 0x8009DA40        ; 26 six-byte race labels (1-based)
S2D_PDATA_TAIL      equ 0x800899F4         ; PersonaDataDraw's bar tail (0x70 bytes)
S2D_PDATA_TAIL_END  equ 0x80089A64
;; ADV code/table positions follow the actual data/name sizes; see adv/smallfont.asm.
ADV_SF_BUFS_ADDR equ 0x800E624C            ; 2 x 0x1200-byte buffers, after g_menu_cells
ADV_SF_BUFS_LIMIT equ 0x800E864C           ; bg_map0's cell table starts here
                                           ; g_font_blank (0x800E864C, FontCellsInit)
ADV_NAME_EMIT_JAL_ADDR equ 0x80066DA0      ; jal glyph renderer (name chars)
ADV_NAME_ACTIVATE_JAL_ADDR equ 0x80066DAC  ; jal cell activate
ADV_NAME_POS_INC_ADDR equ 0x80066DC0       ; addiu v0,v0,1 (pos++)
ADV_TEXT_CLASSIFY_ADDR equ 0x800677BC      ; sltiu v0,a2,0x80 / beqz v0 (3 words)
ADV_TEXT_TWO_BYTE_ADDR equ 0x800677F8      ; two-byte glyph decode path
ADV_TEXT_WIDE_ARG_ADDR equ 0x8006783C      ; move a2,s0 (two-byte glyph arg)
ADV_TEXT_EMIT_JAL_ADDR equ 0x80067840      ; jal glyph renderer (text)
ADV_TEXT_ACTIVATE_JAL_ADDR equ 0x8006784C  ; jal cell activate
ADV_TEXT_POS_INC_ADDR equ 0x80067860       ; addiu v0,v0,1 (pos++)

;; --- BTLP.BIN - Overlay #5: battle ---
BTLP_FILENAME equ "../../data/psx/BTLP.BIN"
BTLP_OUTPUT equ "../../build/BTLP.BIN"
BTLP_ADDR equ OVERLAY_SLOT_ADDR
;; text interpreter 0x8007C9E0 calls the glyph function 0x8007C754(struct, ptr) -> ptr here
BTLP_TEXT_EMIT_JAL_ADDR equ 0x8007CCD4
BTLP_TEXT_EMIT2_JAL_ADDR equ 0x8007CF80
;; negotiation choice box (btlp/choice_answer_bound.asm): the two instructions
;; that build the retail 0x801CFFFF answer-pointer limit; replaced with the
;; loaded file's own answer-pool end (header word 2) so translated answers that
;; sit past 64 KB are not all replaced by directory entry 0.
BTLP_CHOICE_BOUND_LOAD equ 0x8007E2D4       ; lui v1,0x801c
BTLP_CHOICE_BOUND_ADD equ 0x8007E300        ; ori v1,v1,0xffff
;; demon reaction lines (btlp/demonline_bound.asm): the same 64 KB assumption,
;; here a window test on the resolved script; replaced with the loaded pack's
;; own text length (header word 2, 0x801C0008).
BTLP_DEMONLINE_BOUND_LUI  equ 0x800686DC    ; lui v0,0x7fe4
BTLP_DEMONLINE_BOUND_LOAD equ 0x800686E0    ; addu v0,s0,v0
BTLP_DEMONLINE_BOUND_SUB  equ 0x800686E4    ; ori v1,zero,0xffff
BTLP_DEMONLINE_BOUND_SLTU equ 0x800686E8    ; sltu v0,v1,v0
BTLP_DEMONLINE_BOUND_BEQ  equ 0x800686EC    ; beqz v0,0x800686FC
;; battle skill menu (btlp/skill_menu.asm): 7 small-font text descriptors per set (x, y, ptr, count ...),
;; filled by three copy loops; English names use the SKILL_MENU_STRIDE buffer in SLPS (SKILL_MENU_BUF)
BTLP_SF_WIDTH_ADDR equ 0x800F8960      ; after QOL_REWARDS, inside the last loaded BTLP sector
BTLP_SF_CODE_ADDR equ 0x800F8A60       ; immediately after the existing 256-byte SF width table
BTLP_SF_END_ADDR equ 0x800F8BC4        ; end of that retail loaded sector
BTLP_NAME_DATA_ADDR equ 0x800F8BC4    ; immutable data after the sprite bridge
BTLP_NAME_DATA_END equ 0x800F9148     ; first sound-work buffer (entry.c)
BTLP_IMAGE_LIMIT equ BTLP_NAME_DATA_END
;; The battle-board ownership directory is allocated by battle_board_text.py
;; in reclaimed, immutable source text, never the live stock-number array
;; at 0x800F7ED8..0x800F7FF8.
;; Board 23 (R1 enemy-kind list, btlp/board23_names.asm): the arcana label
;; table is drawn in place, and the three full-name rows reuse the retail
;; name pool (two rows) and arcana pool (third row).
BTLP_BOARD23_TAG_TABLE equ 0x800E2060  ; 8-byte label slots, FF-terminated
BTLP_BOARD23_TAG_TABLE_END equ 0x800E2140
BTLP_BOARD23_NAMES_ADDR equ 0x800F7200 ; retail name pool, now two 16-cell rows
BTLP_BOARD23_NAMES_END equ 0x800F7220
BTLP_BOARD23_NAME_ROW_2 equ 0x800F7CA4 ; retail arcana pool, now the third row
BTLP_BOARD23_NAME_END_2 equ 0x800F7CB4
BTLP_BOARD23_NAME_STRIDE equ 16        ; ten head glyphs + up to five tail + FF
BTLP_OFFER_NAME_BASE equ 0x800EB26D  ; first BtlOffer.name; three records
DEMON_NAME_COUNT equ 194
;; CONTACT offer personality bank is 64 bytes at 0x800C87EC (btlui.py). The
;; stock-list names get their own 21-byte slots in resident battle scratch:
;; the dialogue unpack buffer is free while the stock menu is open (both
;; callers run BtlSeqClear immediately before BtlTalkStockMenu). The offer
;; gate owns the personality bank and this bank as two VWF ranges.
BTLP_PERSONALITY_BANK equ 0x800C87EC
BTLP_PERSONALITY_BANK_END equ 0x800C882C ; eight [glyphs][0xFF] labels
BTLP_STOCK_FULL_ADDR equ 0x80057400      ; == BTLEVT_BUF_ADDR; tools read it literally
BTLP_STOCK_FULL_STRIDE equ 21
BTLP_STOCK_ROWS equ 12
BTLP_STOCK_FULL_SIZE equ 252             ; 12 * 21
BTLP_STOCK_FULL_END equ 0x800574FC
.if BTLP_STOCK_FULL_ADDR != BTLEVT_BUF_ADDR
    .error "stock name bank must start at the free dialogue buffer"
.endif
.if BTLP_STOCK_FULL_END != BTLP_STOCK_FULL_ADDR + BTLP_STOCK_FULL_SIZE
    .error "stock name bank extent disagrees with its size"
.endif
BTLP_ENEMY_NAME_BASE equ 0x8005DB53  ; first enemy BtlActor.c.name; nine records
BTLP_SKILL_DESC_A equ 0x800DD788       ; 7 x 12 bytes, ptr at +4, glyph count at +8
BTLP_SKILL_DESC_B equ 0x800DDD68       ; second set, same buffer

;; --- full-length skill names (tools/skills.py, slps_005.00/skill_names.asm) ---
SKILL_RECORDS_ADDR equ 0x80047D44      ; + id*0x14 (id 1-based)
SKILL_COUNT equ 242                    ; physical skill records after reserved ID 0
SKILL_FIELD equ 10
SKILL_SPARE equ 0x11                   ; unreferenced record bytes +0x11..+0x13
SKILL_MAXLEN equ 23                    ; menu slot: 23 glyphs + terminator (SKILL_MENU_STRIDE 24)
SKILL_CODE_ADDR equ 0x80011FBC         ; unreferenced function (taken from tools/choices.py FREE)
SKILL_CODE_END equ 0x800120A4
SKILL_CODE_SIZE equ SKILL_CODE_END - SKILL_CODE_ADDR
SKILL_VWF_FLAGS_ADDR equ 0x80012080     ; 31-byte bitmap: English ownership by skill ID
SKILL_VWF_SLOTS_ADDR equ 0x800120A0     ; u16: ownership bits (Persona 0..2, skill slot i at 3+i)
SKILL_TAILS_ADDR equ 0x8004CE6F         ; affinity records 63-95 (unused 'リザーブ' slots, tools/affinity.py FREE)
SKILL_TAILS_SIZE equ 0x91               ; ends at AFF_FREE2_ADDR; the offset byte is not an ownership bound
AFF_FREE2_ADDR equ 0x8004CF00            ; rest of the free affinity records: slps_005.00/aff_free.asm
AFF_FREE_END equ 0x8004D1A8              ; record 96 starts here
VWF_SMALL_MAP_LEN equ 0xD0
;; The two battle name banks are separate ranges of one ownership bitmap
;; (vwf/btl_name_owner.asm): each range reports its own slot index and adds its
;; own bit offset. They must stay separate - the dead run in SLPS that holds the
;; skill slots ends at the live function 0x8002C2F0 (BTLP calls it 8 times), so
;; only 168 bytes are free there.
PERSONA_HDR_STRIDE equ 16              ; Persona names are 16 glyphs
PERSONA_HDR_BUF equ 0x8002BC84          ; dead SLPS function (tools/deadfuncs.py), 4 x 16 bytes
PERSONA_HDR_BUF_END equ 0x8002BCC4      ; PERSONA_HDR_BUF + 4 * PERSONA_HDR_STRIDE
PERSONA_HDR_LIMIT equ 0x8002BD60        ; end of that dead run (asserted in asm)
PERSONA_BIT_OFFSET equ 0               ; ownership bits 0..2
BATTLE_LABEL_BUF equ 0x8002BCB4        ; PERSONA_HDR_BUF + 3 * PERSONA_HDR_STRIDE: static "Cost" label string (fixed-width, unowned)
;; The command-stage member boards cannot use the four header slots (the skill
;; header and PRS-CHG rewrite those); they get five 16-glyph buffers in the
;; status board's own spare zero run in BTLP.  btlp/status_persona.asm writes
;; them with persona_name_copy and points the five fixed descriptors at them.
BTLP_STATUS_PERSONA_BUF equ 0x800F7F80
BTLP_STATUS_PERSONA_END equ 0x800F7FD0
SKILL_MENU_STRIDE equ 24               ; 23 glyphs + terminator; 7 slots fill the run exactly
SKILL_MENU_BUF equ 0x8002C248          ; dead code run before the live function 0x8002C2F0
SKILL_MENU_BUF_END equ 0x8002C2F0      ; = the live function entry (asserted in asm)
SKILL_BIT_OFFSET equ 3                 ; ownership bits 3..9
BATTLE_NAME_BITS equ 10                ; ownership halfword: Persona 0..2, skill slot i at 3+i
BANNER_SPILL_ADDR equ 0x8002C374        ; first banner spill fragment after the battle name bank
BTLP_ITEM_NAMES_ADDR equ 0x800F81CC     ; 12 retail 10-byte names, two columns
BTLP_ITEM_FULL_ADDR equ 0x80057E00      ; 12 x 21 bytes, path-cache tail after dialogue ring
BTLP_ITEM_FULL_STRIDE equ 21
BTLP_ITEM_FULL_END equ BTLP_ITEM_FULL_ADDR + BTLP_ITEM_ROWS * BTLP_ITEM_FULL_STRIDE
BTLP_ITEM_IDS_ADDR equ 0x800F8088       ; current packed inventory IDs, 12 x u16
BTLP_ITEM_DESC equ 0x800DD828           ; 12 name descriptors; counts at +0x90
BTLP_ITEM_COUNT_ADDR equ 0x800F7D64     ; separate 12 x 3-byte count rows
BTLP_ITEM_ID_COUNT equ 0x56            ; source producer rejects IDs at/above this
BTLP_ITEM_ROWS equ 12
BTLP_ITEM_FIELD equ 10

;; --- CASINO.BIN - Overlay #8: casino ---
CASINO_FILENAME equ "../../data/psx/CASINO.BIN"
CASINO_OUTPUT equ "../../build/CASINO.BIN"
CASINO_ADDR equ OVERLAY_SLOT_ADDR

;; --- DNG.BIN - Overlay #4: dungeon ---
DNG_FILENAME equ "../../data/psx/DNG.BIN"
DNG_OUTPUT equ "../../build/DNG.BIN"
DNG_ADDR equ OVERLAY_SLOT_ADDR
DNG_IMAGE_LIMIT equ DNG_ITEM_DATA_END
;; dialogue text interpreter: copy of ADV's (main path at ADV+0xFC2C).
;; Statically derived (jal targets consistent with base) - not yet run.
DNG_GLUE_ADDR equ 0x800A1200           ; extension of DNG.BIN behind the image (dng/vwf_script.asm)
DNG_SCRIPTMSG_ADDR equ 0x800A1C00       ; relocated FF55 script messages (above glue and optional FPS glue)
DNG_SCRIPTMSG_LIMIT equ 0x800A2000
DNG_SPILL_ADDR equ 0x800A2000          ; spill table, text, and redirect code; beyond optional FPS glue
DNG_SPILL_LIMIT equ 0x800B0000         ; below the held-pause title renderer
DNG_FIELD_TITLE_ADDR equ 0x800B0000     ; held-pause VWF renderer + 160x16 scratch
DNG_FIELD_TITLE_LIMIT equ 0x800B0C00    ; below the shared title index/blob
DNG_FIELD_TITLE_ENTRY equ 0x8006E700     ; FieldLoadWallCluts entry
DNG_FIELD_TITLE_WIDTH equ 160            ; ten 16px cells in the held-pause strip
DNG_TEXT_STATE equ 0x800E1E4C
;; MsgStep pacing (vwf/msg_pace.asm); the dungeon frame is 3 vsyncs (20 fps)
DNG_MSG_TOP equ 0x8007683C
DNG_MSG_TOP_END equ 0x80076894
DNG_MSG_RECT equ 0x8006459C
DNG_MSG_SLOTS equ 0x800EB14C
DNG_MSG_NEXT equ 0x80076AB0
DNG_MSG_DONE equ 0x800774F4
DNG_MSG_TEXT_TAIL equ 0x80077498
DNG_MSG_SUB_TAIL equ 0x800774B8
DNG_MSG_INSERT_TAIL equ 0x80076C60
DNG_MSG_PACE equ 3
DNG_CELL_ACTIVATE equ 0x80077534
DNG_UPLOAD_COUNT equ 0x800A072C
DNG_UPLOAD_QUEUE equ 0x800A0760
DNG_FLUSH_UPLOADS equ 0x80077B74
;; small-font VWF line (dng/smallfont.asm)
DNG_SF_HOOK_ADDR equ 0x8007782C            ; TileMapWriteRow loop entry: la t0,cfg / j sf_record
DNG_SF_MAP_BASE equ 0x800E3E4C             ; same work area as ADV (WORK_BIAS 0)
DNG_SF_ROW_ADDR equ 0x800939EC             ; DNG.BIN +0x2F628: a dead function (tools/deadfuncs.py)
DNG_SF_ROW_SIZE equ 2420                   ; ... its span up to the next function
DNG_SF_CFG_ADDR equ DNG_SF_ROW_ADDR        ; the config block: the run's first 0x20 bytes
DNG_SF_HELP_ADDR equ 0x80080A54            ; DNG.BIN +0x1C690: a dead function (tools/deadfuncs.py)
DNG_SF_HELP_SIZE equ 2012
DNG_SF_BUFS_ADDR equ 0x800E624C            ; same decomp-verified gap as ADV
DNG_SF_BUFS_LIMIT equ 0x800E864C
DNG_NAME_EMIT_JAL_ADDR equ 0x80076BD0
DNG_NAME_ACTIVATE_JAL_ADDR equ 0x80076BDC
DNG_NAME_POS_INC_ADDR equ 0x80076BF0
;; map titles (dng/map_title.asm): the JA-match table + EN blob
;; (build/dng_titles.asm) sits in front of the hook, and its budget is the
;; room between the two. dngnames.py reads these two and places
;; the table; nothing else may move them.
DNG_TITLE_TABLE_ADDR equ 0x800B0C00
DNG_TITLE_HOOK_ADDR equ 0x800B2400
DNG_TEXT_CLASSIFY_ADDR equ 0x800773E8
DNG_TEXT_TWO_BYTE_ADDR equ 0x80077424
DNG_TEXT_WIDE_ARG_ADDR equ 0x80077468
DNG_TEXT_EMIT_JAL_ADDR equ 0x8007746C
DNG_TEXT_ACTIVATE_JAL_ADDR equ 0x80077478
DNG_TEXT_POS_INC_ADDR equ 0x8007748C
;; --- the dungeon run action (qol/run_dng.asm) ---
;; The run action is the controller page's own twentieth action, not a settings
;; row: its name and the page's action-name table live in the image extension
;; after the Persona Data bar (build/runtext_dng.asm, generated by runtext.py),
;; then the walk hook. Every byte stays below the sector-safe end the base image
;; already loads. The retail PadDrawLayout reads the 19-pointer name table that
;; sits directly in front of the layout table, so the copy here adds the run
;; pointer and the page's table base load is repointed at it.
DNG_RUN_NAME       equ 0x800B5800          ; build/runtext_dng.asm: the run action's name row
DNG_RUN_NAME_ROOM  equ 16
DNG_RUN_PAD_NAMES  equ 0x800B5810          ; g_pad_action_names[0..19], the run pointer last
DNG_RUN_ADDR       equ 0x800B5860          ; the walk hook and turn frame wrapper
DNG_RUN_LIMIT      equ DNG_PDATA_EXT_LIMIT ; the base image's last loaded sector
DNG_TURN_FRAME     equ 0x80069084          ; FieldTurn's loop: jal FieldFrame
DNG_PAD_NAMES      equ 0x8009CACC          ; retail g_pad_action_names, 19 pointers
DNG_PAD_NAME_COUNT equ 19
DNG_PAD_RUN_INDEX  equ 19                  ; the run action's index in that table
DNG_PAD_LAYOUTS    equ 0x8009CB18          ; g_pad_layout_actions: four layouts x 20 buttons
DNG_PAD_LAYOUT_ENTRIES equ 20              ; entries per layout (3D column 0..9, 2D column 10..19)
DNG_PAD_CIRCLE     equ 0                   ; the 3D column's buttons run circle, cross, triangle, square...
DNG_PAD_CROSS      equ 1
DNG_PAD_DRAW_ADDR  equ 0x80090650          ; PadDrawLayout
DNG_PAD_DRAW_LUI   equ 0x800906FC          ; lui at,0x800A - the name table's high half
DNG_PAD_DRAW_ADDIU equ 0x80090700          ; addiu at,at,-0x3534 - its low half
;; --- QoL western controls (qol/western_pad.asm, qol/western_layout.asm) ---
WESTERN_PAD_READ_NOR equ 0x8002515C        ; PadRead: nor v0,zero,v0 (the held buttons, active high)
WESTERN_PAD_CODE   equ 0x80028F2C          ; dead libgte function (tools/deadfuncs.py with transitive deadness: only the
WESTERN_PAD_CODE_END equ 0x80028F8C        ; dead 0x800316DC called it; 1000 bytes to 0x80029314): 96 bytes taken
BTLP_INDICATOR_ICON equ 0x800E2408   ; MES blob: choice-menu corner icon (frame 1 = the cancel key)
BTLP_CONTROLS_ICONS equ 0x800DE7E0      ; the Controls page's TYPE 1 icon descriptors: eight, 8 bytes each
PAD_TYPE_ADDR      equ 0x801F2AC7          ; the saved controller type: 0 = TYPE 1, 1 = TYPE 2
ADV_PAD_LAYOUTS    equ 0x800B983C          ; g_pad_layout_actions in each overlay that carries the page
S2D_PAD_LAYOUTS    equ 0x8009F6A8

;; --- S2D.BIN - Overlay #6: 2D map ---
S2D_FILENAME equ "../../data/psx/S2D.BIN"
S2D_OUTPUT equ "../../build/S2D.BIN"
S2D_ADDR equ OVERLAY_SLOT_ADDR
S2D_IMAGE_LIMIT equ S2D_ITEM_DATA_END
;; dialogue text interpreter: copy of ADV's (main path at ADV-0x820).
;; Statically derived (jal targets consistent with base) - not yet run.
S2D_TEXT_STATE equ 0x80101E4C
;; MsgStep pacing (vwf/msg_pace.asm)
S2D_MSG_TOP equ 0x800663DC
S2D_MSG_TOP_END equ 0x80066434
S2D_MSG_RECT equ 0x800643C8
S2D_MSG_SLOTS equ 0x8010B14C
S2D_MSG_NEXT equ 0x80066664
S2D_MSG_DONE equ 0x800670A8
S2D_MSG_TEXT_TAIL equ 0x8006704C
S2D_MSG_SUB_TAIL equ 0x8006706C
S2D_MSG_INSERT_TAIL equ 0x80066814
S2D_MSG_PACE equ 2
;; extension of S2D.BIN behind its last sector (RAM 0x800BA3C4..): English overworld boxes (tools/s2dscript.py SPILL = ..0x800BB200), then VWF glue code
S2D_GLUE_ADDR equ 0x800BB200
S2D_GLUE_SIZE equ 0x800BB8E8 - S2D_GLUE_ADDR
S2D_CELL_ACTIVATE equ 0x800670E8
S2D_UPLOAD_COUNT equ 0x800B92C8
S2D_UPLOAD_QUEUE equ 0x800B92FC
S2D_FLUSH_UPLOADS equ 0x80067B9C
;; small-font VWF line (s2d/smallfont.asm)
S2D_SF_HOOK_ADDR equ 0x800673E0            ; TileMapWriteRow loop entry: la t0,cfg / j sf_record
S2D_SF_MAP_BASE equ 0x80103E4C             ; the text map's cell base (+0x20000 bias)
;; DrawSpellName (s2d/draw_spell.asm), same rule as ADV's copy.
S2D_DRAW_SPELL_NAME equ 0x8007A908         ; rewritten in place (0xBC bytes avail)
S2D_TILEMAP_FILLRECT equ 0x800674CC        ; TileMapFillRect(dst, value, w, h, [sp]=stride)
S2D_SPELL_RULE_GLYPHS equ 0x8009E5F4       ; the eight-glyph rule under an empty slot
S2D_SF_ROW_ADDR equ 0x80083B24             ; S2D.BIN +0x1F760: a dead function (tools/deadfuncs.py)
S2D_SF_ROW_SIZE equ 2420                   ; ... its span up to the next function
S2D_SF_CFG_ADDR equ S2D_SF_ROW_ADDR        ; the config block: the run's first 0x20 bytes
S2D_SF_HELP_ADDR equ 0x800708F4            ; S2D.BIN +0xC530: a dead function (tools/deadfuncs.py)
S2D_SF_HELP_SIZE equ 2012
S2D_SF_BUFS_ADDR equ 0x8010624C            ; the same gap + S2D's 0x20000 work-area bias
S2D_SF_BUFS_LIMIT equ 0x8010864C           ; g_font_blank / bg_map0
S2D_NAME_EMIT_JAL_ADDR equ 0x80066784
S2D_NAME_ACTIVATE_JAL_ADDR equ 0x80066790
S2D_NAME_POS_INC_ADDR equ 0x800667A4
S2D_TEXT_CLASSIFY_ADDR equ 0x80066F9C
S2D_TEXT_TWO_BYTE_ADDR equ 0x80066FD8
S2D_TEXT_WIDE_ARG_ADDR equ 0x8006701C
S2D_TEXT_EMIT_JAL_ADDR equ 0x80067020
S2D_TEXT_ACTIVATE_JAL_ADDR equ 0x8006702C
S2D_TEXT_POS_INC_ADDR equ 0x80067040

;; --- NAME.BIN - Overlay #9: name entry ---
NAME_FILENAME equ "../../data/psx/NAME.BIN"
NAME_OUTPUT equ "../../build/NAME.BIN"
NAME_ADDR equ OVERLAY_SLOT_ADDR
NAME_INIT_JAL_TARGET equ 0x80067318      ; first init callee, NAME.BIN +0x14 (name/latin_start.asm)
NAME_TAB_STUB_ADDR equ 0x80024744        ; dead SLPS function (tools/deadfuncs.py, unclaimed)
NAME_RING_STUB_ADDR equ 0x800316DC       ; dead SLPS function, taken from tools/choices.py FREE (name/ring.asm)
NAME_RING_STUB_END equ 0x80031744
;; The rest of that dead function: the ANALYZE "race: name" gap (btlp/offer_name.asm),
;; resident but only entered from BTLP.
ANALYZE_RACE_GAP_ADDR equ 0x80031744
ANALYZE_RACE_GAP_END equ 0x80031770
;; The entry screen's family / given cells (u16 glyph codes) and the 10-byte
;; save slots the compact writer fills (name/long_names.asm).
NAME_FAMILY_TEXT_ADDR equ 0x800682A0     ; g_name_text[0][0]
NAME_GIVEN_TEXT_ADDR equ 0x800682B0      ; g_name_text[1][0]
NAME_SAVE_FAMILY_ADDR equ 0x801F298C     ; SAVE_NAME0
NAME_SAVE_GIVEN_ADDR equ 0x801F2996      ; SAVE_NAME1

;; --- OPEN.BIN - Title/opening data archive (seen resident at 0x80180000) ---
OPEN_FILENAME equ "../../data/psx/OPEN.BIN"
OPEN_OUTPUT equ "../../build/OPEN.BIN"
OPEN_ADDR equ 0x80180000
OPEN_IMAGE_LIMIT equ 0x801E0000          ; FONT.BIN is loaded here

;; --- EXE/ATLUS.EXE - Atlus logo EXE, t_addr 0x80080000 ---
ATLUS_EXE_FILENAME equ "../../data/psx/EXE/ATLUS.EXE"
ATLUS_EXE_OUTPUT equ "../../build/EXE/ATLUS.EXE"
ATLUS_EXE_ADDR equ 0x80080000 - PSX_EXE_HEADER_SIZE

;; --- EXE/OPEN.EXE - Opening/title EXE, t_addr 0x80080000 ---
OPEN_EXE_FILENAME equ "../../data/psx/EXE/OPEN.EXE"
OPEN_EXE_OUTPUT equ "../../build/EXE/OPEN.EXE"
OPEN_EXE_ADDR equ 0x80080000 - PSX_EXE_HEADER_SIZE
OPEN_EXE_IMAGE_LIMIT equ 0x80180000      ; OPEN.BIN is loaded here

;; --- EXE/MOVIE.EXE - Movie player EXE, t_addr 0x80080000 ---
MOVIE_EXE_FILENAME equ "../../data/psx/EXE/MOVIE.EXE"
MOVIE_EXE_OUTPUT equ "../../build/EXE/MOVIE.EXE"
MOVIE_EXE_ADDR equ 0x80080000 - PSX_EXE_HEADER_SIZE
MOVIE_EXE_IMAGE_LIMIT equ 0x801E0000     ; FONT.BIN is loaded here
;; Separate armips pass for the in-engine subtitle renderer; it is copied
;; to this window by the movie player (movie_exe/subs_boot.asm).
MOVIE_SUBS_CODE_OUTPUT equ "../../build/movie_subs_code.bin"
MOVIE_SUBS_CODE_ADDR equ 0x80160000
MOVIE_SUBS_CODE_IMAGE_LIMIT equ 0x80180000

;; --- EXE/END.EXE - Ending EXE, t_addr 0x80080000 ---
END_EXE_FILENAME equ "../../data/psx/EXE/END.EXE"
END_EXE_OUTPUT equ "../../build/EXE/END.EXE"
END_EXE_ADDR equ 0x80080000 - PSX_EXE_HEADER_SIZE

;; =============================================================
;; Text data files (addresses are file offsets)
;; =============================================================

;; --- ADV/MES.BIN - Event script text (13 MB) - file offsets ---
MES_FILENAME equ "../../data/psx/ADV/MES.BIN"
MES_OUTPUT equ "../../build/ADV/MES.BIN"
MES_ADDR equ 0

;; --- NAMEDT.BIN - Name data - file offsets ---
NAMEDT_FILENAME equ "../../data/psx/NAMEDT.BIN"
NAMEDT_OUTPUT equ "../../build/NAMEDT.BIN"
NAMEDT_ADDR equ 0

;; --- Battle small-font page: patched in /B/BF.BIN by tools/btlfont.py. ---
;; BTLP uploads the page to VRAM 960,256 from compressed battle data.
BTLP_PAGE_LOAD_JAL_ADDR equ 0x80081E80  ; jal LoadImage (0x8002B810) in the BTLP TIM loader
GPU_LOAD_IMAGE equ 0x8002B810           ; LoadImage(rect, src)
GPU_DRAW_SYNC  equ 0x8002B5E8           ; DrawSync(int)
GPU_MOVE_IMAGE equ 0x8002B8D8           ; MoveImage(rect, x, y)
NAME_COUNT_ADDR equ 0x8001A4A8           ; 2 unreferenced SLPS functions (tools/deadfuncs.py):
NAME_COUNT_SIZE equ 0x8001A510 - NAME_COUNT_ADDR
                                         ; name_count_store, the resident name-insert count glue

;; --- battle banner names (tools/banner.py): pointer table 0x800D92F4 (347 words), pool 0x800D835C-0x800D92F4;
;; overflow strings in dead SLPS functions 0x8002C2B8-0x8002C2F0, 0x80026A10-0x80026A54, 0x80018B50-0x80018B88

;; --- full-length Persona names (tools/personas.py, slps_005.00/persona_names.asm) ---
PERSONA_RECORDS_ADDR equ 0x8004B0CC     ; record base; name field at +8 + key*0x2C (key 0 unused)
PERSONA_NAME equ 8
PERSONA_FIELD equ 10
PERSONA_SPARE equ 0x29                  ; unreferenced record bytes +0x29..+0x2B
PERSONA_MAXLEN equ 16
PERSONA_CODE_ADDR equ 0x80031878        ; 2 unreferenced functions (taken from tools/s2dnames.py SPILL)
PERSONA_CODE_SIZE equ 0x8003191C - PERSONA_CODE_ADDR
PERSONA_TAILS_ADDR equ 0x8001EA10       ; unreferenced function
PERSONA_TAILS_SIZE equ 0x8001EA4C - PERSONA_TAILS_ADDR
PERSONA_VWF_CODE_ADDR equ 0x80012484    ; freed Persona scratch, 48 bytes, bounded by VWF_BTLP_CODE_ADDR
;; battle skill menu header descriptors (x, y, ptr, count): Persona name, "Cost" label, summon cost value
BTLP_HDR_NAME_DESC equ 0x800DD74C
BTLP_HDR_LABEL_DESC equ 0x800DD80C      ; -> label string BATTLE_LABEL_BUF (しょうかんSP retail string stays unused)
BTLP_HDR_VALUE_DESC equ 0x800DD764

;; --- ANALYZE status board: translated producer buffers ---
;; The board's rows are runtime-generated and sit outside every producer
;; ownership range (Persona/skill/item banks), so vwf_slps.asm registers the
;; buffers their translated producers write as always-owned spans. A row
;; pointer inside one is VWF; untranslated rows (ailments, full-width rank and
;; kind labels, the shared kana label bank) stay retail. The span ends are the
;; buffers' own bounds, not the row descriptor addresses; the board list is
;; checked against these spans by tools/tests/test_btlp_analyze_ownership.py.
;; The stat labels (STR..LUK, the two magic stats, traits) are an owned span
;; too, so they share the VWF of the other boards; the shared kana label bank
;; (Lv / HP / SP / St.) does not.
ANALYZE_NAME_BUF equ 0x800F6FB4         ; "race: name" header (enemystatus.c producer)
ANALYZE_NAME_CODE_SIZE equ 56           ; btlp/offer_name.asm: the ANALYZE full name, allocated by btlp.py
ANALYZE_NAME_END equ 0x800F6FCC
;; The labels (rows 28-35, btlui.py) are packed back to back in the retail
;; label block, each row's count its exact length (no terminators), so the
;; longer English fits the same 44 bytes.
ANALYZE_LABEL_BUF equ 0x800DEA18
ANALYZE_LABEL_END equ 0x800DEA44        ; = the board's row list
;; Six full-name spell rows (btlp/analyze_spells.asm), right after the trait
;; line in the same exclusive dialogue scratch and below the VWF ring; the
;; rows are byte-addressed, and touching the trait line lets battle_board_text
;; merge the two into one ownership directory entry.
ANALYZE_SPELL_STRIDE equ 24             ; SKILL_MAXLEN glyphs + FF
ANALYZE_SPELL_PX equ 92                 ; the spell column's room before the frame; wider rows use tier 1
;; BTLP's retail 16 px string renderer at 0x8007BF44 is a jump to btlp_str16;
;; its dead body holds the bridge's width lookup and the tier-1 id list
;; (btlp/analyze_metric.asm). Nothing enters the body.
ANALYZE_METRIC_ADDR equ 0x8007BF4C
ANALYZE_METRIC_END equ 0x8007C068
ANALYZE_SPELL_BUF equ 0x8005772F        ; = ANALYZE_TRAIT_END: one ownership entry
ANALYZE_SPELL_END equ 0x800577BF        ; ANALYZE_SPELL_BUF + 6 * ANALYZE_SPELL_STRIDE
;; The rank and kind rows (PHYSICAL / WEAKBOSON ...) follow, so the retail
;; label text they copy is VWF and shares the same ownership entry.
ANALYZE_RANK_BUF equ 0x800577BF         ; ten cells + end, retail 0x800F8248
ANALYZE_RANK_END equ 0x800577CB
ANALYZE_KIND_BUF equ 0x800577CB         ; ten cells + end, retail 0x800F8300
ANALYZE_KIND_END equ 0x800577D7
;; The affinity line is the record's 25-cell head plus the pool tail that
;; completes it (smallfont_vwf.write_pool): the retail 28-byte slot ends at
;; g_btl_slot_owner. The main ANALYZE board and story-dialogue unpacking are
;; exclusive; reuse the upper part of the resident dialogue buffer, outside
;; the CONTACT stock-name range and all name-owner ranges.
ANALYZE_TRAIT_BUF equ 0x80057700
ANALYZE_TRAIT_END equ 0x8005772F        ; 47 cells
.if ANALYZE_SPELL_END != ANALYZE_SPELL_BUF + 6 * ANALYZE_SPELL_STRIDE || ANALYZE_SPELL_BUF < ANALYZE_TRAIT_END || ANALYZE_RANK_BUF != ANALYZE_SPELL_END || ANALYZE_KIND_BUF != ANALYZE_RANK_END || ANALYZE_KIND_END > VWF_DLG_RING_ADDR
    .error "ANALYZE rows overlap the trait line or the VWF ring"
.endif
;; Trait code/pool addresses are allocated by btlp.py from reclaimed strings.

;; --- full-length item/demon names (tools/slps.py + items.py/demons.py,
;;     slps_005.00/item_names.asm) ---
;; The 10-byte record field carries the head; a name over 10 glyphs
;; continues in an overlay-owned [length][glyphs] tail bank, indexed by
;; a has-tail bitmap. item_name_copy/demon_name_copy share the traversal
;; and append the tail to that overlay's scratch. Same contract as
;; skill_name_copy: clobbers v0,v1,a0,a1,a2,at only.
ITEM_NAME_BASE equ 0x8004440C          ; + id*0x20 (id 1-based): the name field
ITEM_NAME_FIELD equ 10
ITEM_NAME_STRIDE equ 0x20                ; one g_item_defs record (items.py STRIDE)
ITEM_RECORDS equ 382                     ; ids 0..381 (items.py COUNT)
ITEM_NAME_MAXLEN equ 20
ITEM_NAME_ROW_PX equ 80                ; the name row's ten 8-px cells
DEMON_NAME_BASE equ 0x800417A0         ; + id*0x38 (id 1-based)
DEMON_NAME_FIELD equ 10
DEMON_NAME_STRIDE equ 0x38              ; one demon record (demons.py STRIDE)
DEMON_RECORDS equ 194                    ; ids 1..194 (demons.py COUNT)
DEMON_NAME_MAXLEN equ 20
;; DrawItemName's tail-jump stubs (dead functions per overlay): the row
;; draws the full name from name_scratch instead of the 10-glyph field
ADV_ITEM_NAME_STUB equ 0x800662D4    ; dead ADV function (80 B)
DNG_ITEM_NAME_STUB equ 0x800761C4    ; dead DNG function (80 B)
S2D_ITEM_NAME_STUB equ 0x80083A00    ; dead S2D function (100 B)

;; --- party full-name inserts (src/injection_tools/partynames.py): the
;; name-insert opcodes print 5 glyphs; a resident helper (NAME_COUNT_ADDR)
;; counts a compact English slot up to its FF terminator and keeps retail's
;; 5 for a legacy all-glyph slot (no terminator). One dead function per overlay
;; holds the 8-byte stub, and it must NOT be an *_ITEM_NAME_STUB site: two features,
;; one .org, last include wins - that overwrite is what killed the status
;; page's item rows (commit 43b3312). partynames.py reads these three with
;; toolbelt.asm_equ(), so the addresses exist exactly once.
ADV_PARTY_COUNT_FIX_ADDR equ 0x800824C0   ; dead ADV function (tools/deadovl.py)
DNG_PARTY_COUNT_FIX_ADDR equ 0x8008FF8C   ; dead DNG function
S2D_PARTY_COUNT_FIX_ADDR equ 0x80065DB4   ; dead S2D function
;; DNG's field-script name print (jal 0x80075428 with a1 = 5) goes through a
;; proxy in the rest of the same dead function: it scans the slot, sets the
;; count and tail-jumps to FieldMsgPrint (src/injection_tools/partynames.py).
DNG_NAME_PRINT_ADDR equ 0x8008FF94        ; dead DNG function 0x8008FF8C + 8 (72 bytes total)
DNG_NAME_PRINT_END equ 0x8008FFD4         ; end of that dead function
DNG_FIELD_MSG_PRINT_ADDR equ 0x80075428   ; FieldMsgPrint(a0 = string, a1 = glyph count)

;; --- story-battle dialogue (tools/btlevt.py, btlp/btlevt_unpack.asm): BPE-packed strings + unpacker in their zone ---
BTLEVT_ZONE_START equ 0x800CFA14
BTLEVT_ZONE_END equ 0x800D0AE4
BTLEVT_UNPACK_ADDR equ (BTLEVT_ZONE_END - 0x370)  ; both window fronts + unpacker + pairs
;; The string being drawn and the strings that outgrew their slots are in the
;; RESIDENT spill bank (BTLEVT_SPILL_ADDR / BTLEVT_BUF_ADDR above): this zone
;; has no room left, and a slot that only has to hold 'FF 00 hi lo' needs none.
BTLEVT_MARK equ 0xFF00                      ; 'FF 00' + big-endian address of the real string
;; PRS-CHG window (btlp/prschg_names.asm): NOW / SUB / SUB Persona names, 16 glyphs each, in the header buffer area
PRSCHG_BUF equ PERSONA_HDR_BUF          ; +0 NOW, +16 SUB, +32 SUB (+48: the static "Cost" label, 64 bytes)
BTLP_PRSCHG_DESC equ 0x800DDD44         ; 3 descriptors x 12 bytes (x -96, y -4/8/20)
;; battle text name copy (btlp/name_lowercase.asm): unreferenced BTLP function (tools/deadovl.py)
BTLP_NAME_COPY_ADDR equ 0x800BD360
BTLP_NAME_COPY_SIZE equ (0x800BD3F8 - BTLP_NAME_COPY_ADDR)
