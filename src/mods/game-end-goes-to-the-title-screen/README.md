# GAME END goes to the title screen (`--mods=game-end-goes-to-the-title-screen`)

Choosing GAME END at an Agastya tree takes you straight back to the title screen. Without it the game tells you to turn off the power and goes back to the game.

## GAME END to the title screen (`--mods=game-end-goes-to-the-title-screen`, on by default)

`mods/game-end-goes-to-the-title-screen/adv.asm`. Retail GAME END at an Agastya tree asks "Quitting the
game. Proceed?", then shows "Please turn off the power" and returns to the game
on any button. With `gameend`, Yes sets the two bytes the suspend save uses to
end the game (0x800BC320 and 0x800BCB40), where the notice would have opened, so
the event overlay leaves for the ATLUS logo and title at once: no notice, no
wait. The release patcher ticks it until the player unticks it
(`default yes` in its mod.tsv), and a bare `--mods` includes it.
