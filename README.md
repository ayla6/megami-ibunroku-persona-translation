# Megami Ibunroku Persona translated!

This is a port of the PSP translation of *Persona 1* to the PS1. It ports
everything it reasonably can from the PSP translation: the script, menus, names,
items, skills, and the small text the PS1 original never had room for.

This translation was entirely coded with AI, yes. I'm sorry if you don't like
that, and I really hope [Tom's translation](https://x.com/RetroTranslator) comes
out so you can play that instead, and so that everyone has like two takes on the
translation of the same game.

The main script is automatically ported from the PSP game, but there were
a tiny few amount of lines that are missing from the PSP version,
those were machine translated.
You can find out what was or wasn't translated with an
LLM in [translation/manual](translation/manual),
or better yet, by going [here](https://github.com/search?q=repo%3Aayla6%2Fmegami-ibunroku-persona-translation+machine-translated+language%3ATSV&type=code&l=TSV).

This is a hard fork of [Redeted/megami-ibunroku-persona-ps1-translation](https://github.com/Redeted/megami-ibunroku-persona-ps1-translation).

## Play it

You need an original Japanese copy of *Megami Ibunroku Persona* (SLPS-00500),
Revision 0 or Revision 1, as a single-track `.bin`. No game data is
included in this repository.

You can just use the webpatcher at [ayla6.github.io/megami-ibunroku-persona-translation](https://ayla6.github.io/megami-ibunroku-persona-translation)

You can also download it from releases and do it by hand with xdelta3:

```sh
# Rev 1 only; skip for a Rev 0 disc.
xdelta3 -d -s "Megami Ibunroku Persona (Japan) (Rev 1).bin" \
    rev1-to-rev0.xdelta persona-rev0.bin
# Base translation, then each option you want, in this order.
xdelta3 -d -s persona-rev0.bin rev0-to-base.xdelta persona-base.bin
xdelta3 -n -d -s persona-base.bin add-mark.xdelta persona-mark.bin
xdelta3 -n -d -s persona-mark.bin add-battlespeed.xdelta persona-mark-battlespeed.bin
xdelta3 -n -d -s persona-mark-battlespeed.bin add-rewards.xdelta persona-mark-battlespeed-rewards.bin
xdelta3 -n -d -s persona-mark-battlespeed-rewards.bin add-encounters.xdelta persona-mark-battlespeed-rewards-encounters.bin
xdelta3 -n -d -s persona-mark-battlespeed-rewards-encounters.bin add-run.xdelta persona-mark-battlespeed-rewards-encounters-run.bin
xdelta3 -n -d -s persona-mark-battlespeed-rewards-encounters-run.bin add-saves.xdelta persona-mark-battlespeed-rewards-encounters-run-saves.bin
xdelta3 -n -d -s persona-mark-battlespeed-rewards-encounters-run-saves.bin add-60fps-saves.xdelta persona-mark-battlespeed-rewards-encounters-run-saves-60fps.bin
```

If xdelta3 reports a checksum mismatch on an `add-` patch, retry with `-n`
and compare your result's `sha256sum` with the `target_sha256` of the
matching row in `manifest.tsv` (the release has verified that exact
combination at build time). The webpatcher does all of this
automatically.

## Extra patches

| Patch | What it does |
| --- | --- |
| Save menu | Merges the slot 1 and slot 2 menus into one, so that you don't have to worry about which one to select. Requires "speed up on memory card access" to not feel like a slog. |
| Black Mark | Makes Masao Inaba black. Uses a custom sprite so that he's both black and still wears his original outfit. Doesn't change the script. |
| Battle speedup | Doubles the speed of summons and skill effects in battle. |
| 60 FPS | Interpolates frames to get the dungeons to 60fps and the map to 30fps. Only does it when you're actively moving around. Needs overclocking. |
| Double rewards | Doubles the EXP, Persona points and money you get after battles. |
| Half encounters | Halves the rate of random encounters. |
| Run in dungeons | Hold Cross to walk and turn at double speed in the 3D dungeons. The controller page lists it as RUN/CANCEL on Cross in both control schemes. |
| Upper-right movement | Forces Upward Movement Orientation to Upper Right: pressing Up walks to the upper right in the 2D rooms instead of the retail upper left. |

On Black Mark: I edited it myself, since I don't like his outfit in Revelations,
much less the fact that his overworld sprite is red instead of, y'know, black.
The script isn't changed at all tho. If you know how to improve his sprite,
please do! I'm not great with this kind of edit, or really any graphical edits at all.

## What's in the translation

- A nice custom font (that's mine :D I hope you like it). It kind of forces
  quite a lot of text to go 3 lines + a scroll, but I didn't want to have a tiny
  font. Doesn't really fit the game, and like, the textbox.
- Almost all of the text coming from the PSP version.
- A tiny tiny minority having had to be machine translated, if you don't
  like some of the machine-translated lines, please report them with why,
  preferably with a suggestion. I don't speak Japanese, I'm sorry.
  (You can find out which ones at [translation/manual](translation/manual))
- Variable width text (from upstream).
- Variable width small text (that's ours), made capable of getting so, so thin
  for the sake of not having to cut characters while still not overflowing.
- Almost everything is allowed its full-length text (almost).
- FMV subtitles and the opening quote / ending poem overlays, rendered in-engine
  rather than by re-encoding the videos. It can slightly drop the fps in some
  frames, and the moon fading definitely will, so I recommend running it
  with an overclock, alongside the 60fps patch so that it doesn't make
  some areas run faster than they should (or without it so you can have it
  running faster lol).

## Why and how?

You might remember when someone released a translation for this very same game,
but it was completely AI generated, including the translation. And everyone went
like, why didn't they just port the PSP translation? Yeah, [that project](https://github.com/Redeted/megami-ibunroku-persona-ps1-translation).
I was also a bit baffled, and so I decided to do just that. So I forked that
project, and thank them for their work, but I didn't see a point in using that
translation. This repository has been scrapped of the previous commits, because
they were full of committed stuff that gives nothing useful to you.

(Btw, after I started this project, they did their own PSP patch, but it's not
very good. It does translate the script, but almost everything else falls back to
the machine translation. It has no small VWF font, so items still aren't able to
be named properly, stuff like that).

And I thought, how do I do this? Well, very simply, I just need the PS1 game,
the PSP game in English, and the PSP game in Japanese, so I can bridge all of
those differences. It was more complicated than that, matching everything was
very annoying at parts, and some stuff had to, as I said, actually translated
because the PSP version didn't have it, basically this and then a loooooong
time polishing everything, allowing for longer texts in some areas and stuff
like that.

## Building

If you want to build it from zero you will need the three discs. If you want to
use the already generated translations, you only need revision 0 of *Megami
Ibunroku Persona*. Put the images anywhere under `data/discs/` (any file name);
the build recognizes them by their contents and extracts what it needs, or run
`python tools/prepare_data.py` to extract everything ahead of time.
[DEVELOPMENT.md](DEVELOPMENT.md) has the build commands, the required files and
the pipeline; [docs/](docs/README.md) is the map to the rest of the
documentation. Or just throw a robot at it.

```sh
python -m pip install -r requirements.txt
python src/setup_external_tools.py            # armips
python tools/prepare_data.py                  # optional: extract the discs first
python src/injection_tools/build.py           # patched disc in dist/
python src/injection_tools/build.py --qol=... # separate QoL image
```

## Credits and license

- The American Persona 1 PSP Release: the source of the English wording.
- [Redeted](https://github.com/Redeted/megami-ibunroku-persona-ps1-translation):
  the project this was forked from, and the origin of the variable-width
  text, the 60fps and easy-mode patches.
- The [web patcher](webpatcher/CREDITS.md) runs the real xdelta3 compiled to
  WebAssembly; its licenses and provenance are there.

The code in this repository is MIT (see [LICENSE](LICENSE)). The game, its
translation and its assets belong to their respective owners.
