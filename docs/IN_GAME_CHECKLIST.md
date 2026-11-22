# In-game checks owed

These checks are for the user to run later. Code/CPU/disc-byte QA does not mark
an in-game item complete. Record the tested build and what happened beside an
item when it has actually been played. Use normal gameplay, not save states.

## Current test build

`dist/Persona-TL.cue` / `.bin` contains the preferred eight mods,
large font and default 2× running. It includes the relocated battle typing
hook and the CONTACT margin correction. Build and audit logs are
`/tmp/persona-contact-uniform-margin-build.log` and `/tmp/persona-contact-uniform-margin-audit.log`. Western Controls, Softer Menu Sounds
and DualShock analog movement are not included in this particular build.

## Current control and mod changes

- [ ] Controller settings: icons and action labels remain correct after
  switching TYPE 1/TYPE 2, leaving the page and reopening it.
- [ ] PSP confirm prompts (docs/TEXT_ARCHITECTURE.md): at Brown's join
  (E0/50), "Let them join" asks Nanjo's "...you want to bring Hidehiko
  along?" and "Don't let them join" asks "...you don't want to...". Answering
  No asks Mark's choice again, and Yes takes the chosen answer. Repeat for
  Elly (E0/51), Ayase (E0/55) and one Kei/Eriko help prompt (E1), where No
  turns the help down.
- [x] Mai's questions (E0/118): a wrong answer makes Maki ask "...Is that
  really what you meant to say to Mai?", and "On second thought..." asks all
  three again. Confirmed in game by the user (2026-11-22, card 2 `2:S5`, a
  Lv 42 save moved into Mai's room with her flags cleared).
- [ ] Other choice menus still draw their options with the moved choice
  table: a shop, the Agastya Tree, a dungeon yes/no.

## When DualShock movement is implemented

- [ ] With original upper-left navigation, analog upper-left sends D-pad Up;
  the other stick diagonals follow their corresponding screen directions.
- [ ] Rotated analog emulation activates only during active 2D room movement.
  Physical D-pad, menus, dialogue, casino and 3D dungeon controls stay intact.
- [ ] Deadzone, release-to-neutral and interaction with Upper-right movement.

The user confirmed battle typing speed. Other items require the checks above.
