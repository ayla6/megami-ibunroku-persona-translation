# DualShock movement investigation

Deferred at the user’s request.

Requested behavior: left-stick input emulates existing direction buttons after
45-degree compensation for original upper-left navigation. Upper-left stick
maps to Up, upper-right to Right, lower-right to Down and lower-left to Left.
Only active 2D room movement uses it. Menus, dialogue, casino, 3D dungeons and
physical D-pad input keep their existing behavior. Upper-right movement needs
its own compatible compensation. This feature is not implemented.

Local Rev 0 evidence:

- Resident PadInit at 0x800250F0 initializes an active-low button destination
  at 0x800563F0 and calls BIOS B0:15 through 0x80041670. The routine finishes
  with ChangeClearPAD via B0:5B. PadRead is at 0x80025140 and reads that word.
- The pad library veneer at 0x80041428 invokes BIOS B0:16. Western Controls'
  physical casino reader uses the same veneer and unremapped button word.
- The existing button word contains no stick axes. Analog support therefore
  needs an actual raw controller-packet path, preserving normal button polling
  and both ports. Treating the current word as an analog packet is incorrect.
- The local decomp's title setup uses InitPAD with four-byte buffers. That
  setup is not sufficient evidence of persistent analog packet storage during
  gameplay. Buffer ownership and BIOS driver lifecycle must be established
  before introducing a resident analog reader.
- AdvFieldTick calls AdvFieldRun only in FIELD_WALK. The Rev 0 Upper-right
  movement mod identifies its direction-selection sites at 0x8007EB54,
  0x8007EB68, 0x8007EB84 and 0x8007EBA0. The decomp's AdvFieldRun confirms a
  prioritized four-button decision. A movement-local mapping avoids changing
  global menu/controller input. Verify dialogue/input-lock behavior too.

Relevant references are src/main/boot.c, src/main/main.c, src/open/title.c,
src/common/ui/pad.c, src/adv/game/fieldtick.c and src/adv/game/fieldrun.c in the
local persona-decomp tree. The decomp is Rev 1; addresses above were checked
against the local Rev 0 binary, not copied from its symbols.
