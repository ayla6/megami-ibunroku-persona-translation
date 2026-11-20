# In-game checks owed

These checks are for the user to run later. Code/CPU/disc-byte QA does not mark
an in-game item complete. Record the tested build and what happened beside an
item when it has actually been played. Use normal gameplay, not save states.

## Current test build

`dist/Persona-TL-mods.cue` / `.bin` contains the preferred eight mods,
large font and default 2× running. It includes the relocated battle typing
hook and the CONTACT margin correction. Build and audit logs are
`/tmp/persona-contact-uniform-margin-build.log` and `/tmp/persona-contact-uniform-margin-audit.log`. Western Controls, Softer Menu Sounds
and DualShock analog movement are not included in this particular build.

## Current control and mod changes

- [ ] Controller settings: icons and action labels remain correct after
  switching TYPE 1/TYPE 2, leaving the page and reopening it.

## When DualShock movement is implemented

- [ ] With original upper-left navigation, analog upper-left sends D-pad Up;
  the other stick diagonals follow their corresponding screen directions.
- [ ] Rotated analog emulation activates only during active 2D room movement.
  Physical D-pad, menus, dialogue, casino and 3D dungeon controls stay intact.
- [ ] Deadzone, release-to-neutral and interaction with Upper-right movement.

The user confirmed battle typing speed. Other items require the checks above.
