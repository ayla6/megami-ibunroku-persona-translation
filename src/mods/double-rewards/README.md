# Double rewards (`--mods=double-rewards`)

Doubles the EXP, Persona points and money you get after battles. Like everything else in this section, this is an option. In this case, if you want an easier game. This is not the intended original experience of the game!

- EXP, Persona points (P.P.) and money after a battle x2 (x << 1; was x1.5 until 2026-10-10): `mods/double-rewards/btlp.asm`, three
  hooks at 0x800F8900 (behind the BTLP image, inside its last loaded sector). The totals
  0x800F746C (EXP), 0x800F70F0 (P.P.) and 0x800F83A4 (money) are multiplied when the end-of-battle code
  first reads them (0x80097A38, 0x80097A88, 0x800AAD70), so the split between members, the results screen
  and the wallet all see the new values. Bosses get x2 as well.
- Verified live with the old x1.5 (same battle twice): money 5460 -> 8190, EXP total 1783 -> 2674, P.P. per member
  224 / 326 / 282 / 236 / 118 -> 336 / 489 / 424 / 354 / 178. The encounter changes are verified by
  disassembly only; the user tests them in a new game.
- 2026-10-10: rewards raised to x2 (`sll a0, a0, 1`); disc rebuilt 13:09 and checked on user slot 5 (dungeon
  battle, AUTO Replay): hooks present at 0x800F8900, results screen paid out. AUTO Normal can stall on a last
  enemy (everyone DEF); Replay finishes the battle.
