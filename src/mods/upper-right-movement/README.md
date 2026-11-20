# Upper-right movement (`--mods=upper-right-movement`)

Up now moves to the upper right instead of the upper left.

## Upper Right movement in the 2D rooms (`--mods=upper-right-movement`)

`mods/upper-right-movement/adv.asm`. The isometric room view has four walking directions and `AdvFieldRun`
maps the d-pad to them. Retail is the PSP's **Upper Left** scheme: Up walks to the upper left, Right
to the upper right, Down to the lower right, Left to the lower left. The patch keeps the same
clockwise order but starts it at the upper right: Up walks to the upper right, Right to the lower
right, Down to the lower left, Left to the upper left - the PSP's **Upper Right** setting. The disc
has no setting row for this, so the patch is the choice.

Only the four direction constants change, in place (`0x8007EB54`, `0x8007EB68`, `0x8007EB84`,
`0x8007EBA0`). The branch order, and so which button wins when two are held, stays retail, and the
scripted walk directions, triggers, exits and facing are untouched. `src/mods/upper-right-movement/test_mod_upright.py`
runs `AdvFieldRun`'s direction selection for each d-pad button and checks the stored walk direction,
plus the bytes that changed.
