"""One-step build: tables -> VWF font -> event scripts -> armips -> patched disc image.

Usage (from the project root):
    python src/injection_tools/build.py [--image PATH] [--no-disc] [--no-port] [--qol[=PATCH,...]]
Output: build/ (intermediates) and dist/ (final patched BIN/CUE)
--image: the original disc image (default: data/discs/Megami Ibunroku Persona - Be Your True Mind (Japan)/...). It
         must be the first release (not Rev 1): see image_check.py.
--qol: separate enhancement build written to dist/Persona-TL-QoL.bin/.cue instead. The patches are picked by
       name from the QOL_PATCHES list below, e.g. `--qol=saves,60fps` (a space instead of `=` works too).
       `--qol` alone selects the combined save UI; `--qol=NAME,...` selects
       only the named patches. `--qol=all` enables every patch and
       `--no-qol=NAME` excludes a named patch. `--qol=list` lists patches.
--no-port: build current translation tables without rerunning PSP extraction/matching or trimming
           worklists. All text/graphics builders, assembly and placement checks still run.
--incremental: reuse explicitly cached preparation steps when inputs and outputs match.
--variants=base;saves;saves,60fps: build each named patch combination after one
           common preparation (quote the argument so the shell keeps semicolons).
"""
import os
import re
import shutil
import subprocess
import sys

import disc_data
import image_check

# Python randomises str hashes per process: some tools pack strings in set / dict order, so pin the seed
# for every tool started below to make the build byte-for-byte reproducible.
os.environ["PYTHONHASHSEED"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORIGINAL_IMAGE = os.path.join(ROOT, 'data', 'discs', 'Megami Ibunroku Persona - Be Your True Mind (Japan)',
                              'Megami Ibunroku Persona - Be Your True Mind (Japan).bin')
if "--image" in sys.argv:
    ORIGINAL_IMAGE = os.path.abspath(sys.argv[sys.argv.index("--image") + 1])
QOL = any(a in ('--qol', '--no-qol') or a.startswith(('--qol=', '--no-qol=')) for a in sys.argv)
# The QoL patches, by name. Each is a qol/*.asm include behind its own define in main.asm; the descriptions
# are what `--qol=list` prints. Order here is the order the README documents them in.
QOL_PATCHES = {
    'saves':       ('QOL_SAVES',       'save / load screen: matching bottom-aligned panel and hh:mm clock, '
                                       'no memory card selection screen, 14 slots (7 + 7 across both cards), '
                                       'newest save preselected when loading'),
    '60fps':       ('QOL_60FPS',       '60 fps 3D dungeons and overworld (interpolated; wants an emulator '
                                       'CPU overclock to actually reach 60)'),
    'encounters':  ('QOL_ENCOUNTERS',  'half the random encounter rate'),
    'rewards':     ('QOL_REWARDS',     'EXP, Persona points and money after a battle x2'),
    'battlespeed': ('QOL_BATTLESPEED', 'summons and skill effects at double speed'),
    'debug':       ('QOL_DEBUG',       'battle debug menu: drop the party-leader name gate, so the hidden '
                                       'sequence works on controller 2 (Up Up Down Down Left Right Left Right '
                                       'Cross Circle in a battle) and holding Cancel in the command phase opens '
                                       'the debug page. The translation build types Latin names only, so the '
                                       'retail kana name the gate wants cannot be entered'),
    'mark':        ('QOL_MARK',        'Mark wears the Revelations design: headshot, battle sheet and '
                                       'overworld walk sheet swapped for the art in src/assets/mark/black '
                                       '(edit those PNGs to change it)'),
}
QOL_DEFAULT = ['saves']
PATCHED_IMAGE = os.path.join(ROOT, 'dist', 'Persona-TL-QoL.bin' if QOL else 'Persona-TL.bin')
ORIGINAL_DIR = os.path.join(ROOT, 'data', 'psx')
ASM_ROOT = os.path.join(ROOT, 'src', 'asm')
ARMIPS = next((p for p in (os.path.join(ROOT, "external_tools", "armips", "armips.exe"),
                            os.path.join(ROOT, "external_tools", "armips", "armips"))
               if os.path.exists(p)), None) or shutil.which("armips")


def run(*cmd):
    if len(cmd) > 1 and isinstance(cmd[1], str) and cmd[1].startswith(("injection_tools" + os.sep,
                                                                       "extraction_tools" + os.sep)):
        cmd = (cmd[0], os.path.join("src", cmd[1]), *cmd[2:])
    print("+", " ".join(os.path.relpath(c, ROOT) if os.path.isabs(c) else c for c in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def run_from(cwd, *cmd):
    print("+", " ".join(os.path.relpath(c, ROOT) if os.path.isabs(c) else c for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def qol_patches(argv=None):
    """Resolve explicit selections (or bare --qol defaults), then exclusions."""
    argv = sys.argv[1:] if argv is None else argv
    enabled, disabled = set(), set()
    for i, arg in enumerate(argv):
        option = arg.split('=', 1)[0]
        if option not in ('--qol', '--no-qol'):
            continue
        names = arg.split('=', 1)[1] if '=' in arg else ''
        if not names and i + 1 < len(argv) and not argv[i + 1].startswith('-'):
            names = argv[i + 1]
        picked = [n for n in re.split(r'[,\s]+', names) if n]
        if picked == ['list'] and option == '--qol':
            for name, (_, description) in QOL_PATCHES.items():
                print(f"{name}{' (default)' if name in QOL_DEFAULT else ''}: {description}")
            raise SystemExit(0)
        unknown = [n for n in picked if n not in QOL_PATCHES and n != 'all']
        if unknown:
            raise SystemExit(f"build.py: unknown QoL patch {', '.join(unknown)}\n"
                             f"  available: {', '.join(QOL_PATCHES)}, all")
        if option == '--no-qol' and not picked:
            raise SystemExit('build.py: --no-qol requires patch names (or all)')
        if option == '--qol' and not picked:
            picked = QOL_DEFAULT
        target = disabled if option == '--no-qol' else enabled
        target.update(QOL_PATCHES if 'all' in picked else picked)
    return [name for name in QOL_PATCHES if name in enabled and name not in disabled]


def prepare_tables(py, incremental=False):
    """Generate assembler character tables from their declared sources."""
    import build_step_cache
    src = os.path.join(ROOT, 'src')
    build_step_cache.run(
        'character tables', [os.path.join(src, 'injection_tools')],
        [os.path.join(src, 'asm', 'common', name) for name in ('persona.tbl', 'persona_vwf.tbl')],
        lambda: run(py, os.path.join('injection_tools', 'make_tbl.py')),
        os.path.join(ROOT, 'build', '.step-cache', 'character-tables.tsv'), reuse=incremental)


def prepare_vwf_font(py, incremental=False):
    """Generate the dialogue font; cache only its explicitly owned outputs."""
    import build_step_cache
    src = os.path.join(ROOT, 'src')
    font = os.path.join(src, 'asm', 'font')
    build_step_cache.run(
        'dialogue font', [os.path.join(src, 'injection_tools', 'make_vwf_font.py'),
                          os.path.join(src, 'injection_tools', 'build.py'),
                          os.path.join(src, 'injection_tools', 'build_step_cache.py'),
                          os.path.join(font, 'sheet.png'),
                          os.path.join(src, 'asm', 'vwf', 'vwf_dialog.asm'),
                          os.path.join(src, 'asm', 'common', 'addresses.inc'),
                          os.path.join(ROOT, 'translation', 'generated'),
                          os.path.join(ROOT, 'translation', 'manual')],
        [os.path.join(font, name) for name in
         ('vwf_font.bin', 'vwf_width.bin', 'vwf_index.bin', 'vwf_glyphs.asm')],
        lambda: run(py, os.path.join('injection_tools', 'make_vwf_font.py')),
        os.path.join(ROOT, 'build', '.step-cache', 'dialogue-font.tsv'), reuse=incremental)


def prepare_fmv_data(py, incremental=False):
    """Generate subtitle assets, or reuse byte-verified unchanged outputs."""
    command = lambda: run(py, os.path.join('injection_tools', 'fmv_subgen.py'), 'data')
    from importlib.metadata import version
    from PIL import features as pil_features
    import build_step_cache
    # Conservative inputs: a source or translation edit costs a rebuild
    # rather than risking a stale subtitle asset.
    build_step_cache.run(
        'FMV subtitle data', [os.path.join(ROOT, 'src'), os.path.join(ROOT, 'translation')],
        [os.path.join(ROOT, 'build', f'movie_subs{suffix}.bin') for suffix in
         ('_data', '_open_data', '_tex', '_open_tex', '_zoom', '_open_zoom')],
        command, os.path.join(ROOT, 'build', '.step-cache', 'fmv-data.tsv'),
        context=(version('Pillow'), pil_features.version_module('freetype2')),
        reuse=incremental)


def build_variants(argv):
    """[(patches, disc path)] for one build or a named batch of combinations."""
    if '--variants' in argv:
        raise SystemExit('build.py: use --variants=base;saves (quote the argument)')
    args = [a for a in argv if a.startswith('--variants=')]
    if not args:
        return [(qol_patches(argv), PATCHED_IMAGE)]
    if len(args) != 1:
        raise SystemExit('build.py: provide exactly one --variants=... option')
    if any(a in ('--qol', '--no-qol') or a.startswith(('--qol=', '--no-qol=')) for a in argv):
        raise SystemExit('build.py: --variants cannot be combined with --qol or --no-qol')
    if '--no-disc' in argv:
        raise SystemExit('build.py: --variants creates discs and cannot be combined with --no-disc')
    choices = args[0].split('=', 1)[1].split(';')
    if not choices or any(not c.strip() for c in choices):
        raise SystemExit('build.py: --variants needs semicolon-separated combinations')
    variants, seen = [], set()
    for choice in choices:
        patches = [] if choice.strip() == 'base' else qol_patches(['--qol=' + choice.strip()])
        key = tuple(patches)
        if key in seen:
            raise SystemExit('build.py: duplicate patch combination in --variants')
        seen.add(key)
        label = '-'.join(patches) if patches else 'base'
        variants.append((patches, os.path.join(ROOT, 'dist', f'Persona-TL-{label}.bin')))
    return variants


def assemble_variant(py, patches, disc_path, make_disc=True, mark_builder=None,
                     source_image=None):
    """Assemble and verify one patch set, then publish its separate disc.

    `source_image` is the image the variant is written onto. It defaults to
    the retail disc, but a release may pass an already-built less-patched
    variant: build_disc then rewrites only the files this variant changes,
    and the filesystem shares the rest of the clone's extents."""
    print(f"build.py: QoL patches: {', '.join(patches) or 'none'} -> {os.path.relpath(disc_path, ROOT)}")
    # Clear the previous variant before assembly; assembly recreates MES.BIN.
    run(py, os.path.join('injection_tools', 'mark.py'), 'retail')
    qol = [x for name in patches for x in ('-definelabel', QOL_PATCHES[name][0], '1')]
    listing = os.path.join(ROOT, 'build', 'armips-main.lst')
    run_from(ASM_ROOT, ARMIPS, 'main.asm', '-sym2', os.path.join(ROOT, 'build', 'persona.sym'),
             '-temp', listing, *qol)
    run(py, os.path.join('injection_tools', 'write_guard.py'), 'check', '--listing', listing)
    run(py, os.path.join('injection_tools', 'make_vwf_font.py'), 'verify')
    import features
    if features.on('SF_VWF'):
        run(py, os.path.join('injection_tools', 'smallfont_vwf.py'), 'verify')
        run(py, os.path.join('injection_tools', 'btlfont.py'), 'verify')
    for name in ('dngspill', 'btlp', 'btlcmd', 'btlui', 'dngnames', 'sysmsg'):
        run(py, os.path.join('injection_tools', name + '.py'), 'verify')
    run(py, os.path.join('injection_tools', 'casinoprize.py'))
    # Assembly recreates MES.BIN from the original, so apply the optional
    # sprite patch only after all other generators have finished. A builder
    # callback supplies artwork it has already verified (a release caches it
    # once per run); without one, build and verify it here.
    if 'mark' in patches:
        if mark_builder is None:
            run(py, os.path.join('injection_tools', 'mark.py'), 'build')
            run(py, os.path.join('injection_tools', 'mark.py'), 'verify')
        else:
            mark_builder(py)
    if make_disc:
        os.makedirs(os.path.dirname(disc_path), exist_ok=True)
        run(py, os.path.join('injection_tools', 'build_disc.py'),
            source_image or ORIGINAL_IMAGE, disc_path, 'build',
            disc_path + '.placement.tsv')


def main(variants_override=None, after_variant=None, mark_builder=None,
         source_image_for=None):
    global ORIGINAL_IMAGE
    py = sys.executable
    variants = (build_variants(sys.argv[1:]) if variants_override is None
                else variants_override)  # reject invalid combinations before regenerating assets
    if not ARMIPS:
        sys.exit("armips not found: run `python src/setup_external_tools.py` or put armips on PATH")
    # Feature gates first: build/features.inc is what main.asm reads, and every
    # later step can ask features.on() instead of assuming. See features.py.
    import features
    gates = features.write(features.from_argv(sys.argv))
    print(f"build.py: features: {features.describe(gates)}")
    # An explicit --image wins. Otherwise the default path is used when it
    # exists, else data/discs/ is searched for a Rev 0 image. A complete
    # extraction is reused; a missing or incomplete one is redone.
    need_image = "--no-disc" not in sys.argv or not disc_data.psx_complete(ORIGINAL_DIR)
    if need_image and "--image" not in sys.argv:
        ORIGINAL_IMAGE = disc_data.resolve_psx(ORIGINAL_IMAGE)
    if need_image:
        image_check.require(ORIGINAL_IMAGE)
    if not disc_data.psx_complete(ORIGINAL_DIR):
        disc_data.extract_psx(ORIGINAL_IMAGE, ORIGINAL_DIR)
    # UI/assembly iteration uses the current tables, not another extraction
    # and matching pass. This still rebuilds all assets from those tables.
    port = '--no-port' not in sys.argv
    if port:
        # Porting reads the PSP-US tree; discover and extract it the same way
        # when the contributor left a PSP image in data/discs/.
        disc_data.ensure_psp('us')
        sys.path.insert(0, os.path.join(ROOT, "src", "extraction_tools", "matching"))
        from mappings import ensure
        ensure()
    incremental = '--incremental' in sys.argv
    prepare_tables(py, incremental=incremental)
    # Family porters own generated wording and its manual gap queue.
    if port:
        run(py, os.path.join("extraction_tools", "matching", "port.py"))
    prepare_vwf_font(py, incremental=incremental)
    # the small-font sheet: glyph bitmaps, pen advances, the engine copies AND
    # the affinity POOL (affinity_pool.bin). A chart record's 25-cell slot is
    # the head of its line; the pool carries the tail and the recorder appends
    # it, so the English is split across two homes. The pool is inside the disc
    # by .incbin - so a stale pool is wrong text in game, not a stale file.
    # Gated: with SF_VWF off nothing includes its output, so skip the work
    # (and the stale-output trap) entirely.
    if gates["SF_VWF"]:
        run(py, os.path.join("injection_tools", "smallfont_vwf.py"), "build")
    # trim the manual worklists to rows still needing human text
    # (auto-covered rows drop out; human fills are kept)
    if port:
        run(py, os.path.join("injection_tools", "etext.py"), "dump")
        run(py, os.path.join("injection_tools", "talk.py"), "dump")
    os.makedirs(os.path.join(ROOT, "build", "ADV"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "build", "previews"), exist_ok=True)
    run(py, os.path.join("injection_tools", "tstatus.py"), "qa")
    run(py, os.path.join("injection_tools", "tstatus.py"), "status")
    run(py, os.path.join("injection_tools", "etext.py"), "build")
    run(py, os.path.join("injection_tools", "title_gfx.py"))
    run(py, os.path.join("injection_tools", "menu_gfx.py"))
    # run(py, os.path.join("injection_tools", "smallfont_pages.py"))
    run(py, os.path.join("injection_tools", "name_grid.py"))
    run(py, os.path.join("injection_tools", "name_gfx.py"))
    run(py, os.path.join("injection_tools", "s2d.py"), "build")
    run(py, os.path.join("injection_tools", "giftmsg.py"))
    run(py, os.path.join("injection_tools", "sysmsg.py"), "build")
    run(py, os.path.join("injection_tools", "slps.py"), "build")
    run(py, os.path.join("injection_tools", "partynames.py"))
    run(py, os.path.join("injection_tools", "btlfont.py"))
    run(py, os.path.join("injection_tools", "btlstat.py"))
    run(py, os.path.join("injection_tools", "scriptmsg.py"))
    run(py, os.path.join("injection_tools", "menutext.py"))
    run(py, os.path.join("injection_tools", "descs.py"), "build")
    run(py, os.path.join("injection_tools", "demons.py"), "build")
    run(py, os.path.join("injection_tools", "name_tails.py"), "build")
    run(py, os.path.join("injection_tools", "affinity.py"), "build")
    run(py, os.path.join("injection_tools", "fusionmsg.py"))
    run(py, os.path.join("injection_tools", "statmsg.py"))
    run(py, os.path.join("injection_tools", "cfgtext.py"))
    run(py, os.path.join("injection_tools", "dngnames.py"))
    # canonical dng builder: boxes (the dngtext scan) + name fields from the
    # toolbelt rows - replaces the ja-keyed dngtext.py/dngmsg.py builders
    run(py, os.path.join("injection_tools", "dngpacks.py"), "build")
    run(py, os.path.join("injection_tools", "dngspill.py"))
    run(py, os.path.join("injection_tools", "personas.py"), "build")
    run(py, os.path.join("injection_tools", "btlp.py"), "build")
    run(py, os.path.join("injection_tools", "btlui.py"))
    run(py, os.path.join("injection_tools", "btlcmd.py"))
    run(py, os.path.join("injection_tools", "opentext.py"))
    run(py, os.path.join("injection_tools", "choices.py"), "build")
    # The page this build ships (the sheet, or the disc's own page with SF_VWF
    # off) goes into every copy of it LAST: the D0x builders above write their
    # packs from data/psx, and this step edits only the page bytes of whatever
    # copy is current (build/, else the original), so neither side erases the
    # other. It also runs with the gate off, so a build that turns the kit off
    # puts the retail page back where an earlier, gated build left the sheet.
    run(py, os.path.join("injection_tools", "smallfont_pages.py"))
    if gates["SF_VWF"]:
        # THE POOL ENCODES TEXT THIS BUILD JUST REGENERATED. smallfont_vwf
        # build also runs early (it owns the widths and the recorder copies,
        # which the text steps do not touch), but affinity_pool.bin is the
        # small-font spelling of the affinity chart lines - and those are
        # rewritten by affinity.py further down this same build. Rebuild the
        # pool here, after its wording inputs are final.
        run(py, os.path.join("injection_tools", "smallfont_vwf.py"), "build")
    os.makedirs(os.path.join(ROOT, "build", "TALK"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "build", "EXE"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "build", "ADV"), exist_ok=True)
    # In-engine FMV subtitles: data blobs (full for MOVIE.EXE, quote-only for
    # OPEN.EXE), then the renderer code (its own armips pass at 0x80160000),
    # then pack each into build/movie_subs*.bin
    prepare_fmv_data(py, incremental='--incremental' in sys.argv)
    subs_listing = os.path.join(ROOT, "build", "armips-subs.lst")
    run_from(ASM_ROOT, ARMIPS, os.path.join("movie_exe", "subs_code.asm"),
             "-sym2", os.path.join(ROOT, "build", "movie_subs.sym"),
             "-temp", subs_listing)
    run(py, os.path.join("injection_tools", "write_guard.py"), "check", "--listing", subs_listing)
    run(py, os.path.join("injection_tools", "fmv_subgen.py"), "pack")
    # Variant-independent outputs: shared by every assembled patch set, so
    # generate and check them once instead of once per variant. `save_ui` is
    # armips input (main.asm includes its generated asm unconditionally); the
    # TALK/ending builders and their unit tests read only the translation and
    # retail data. Nothing here depends on a QoL choice.
    run(py, os.path.join("injection_tools", "save_ui.py"))
    run(py, os.path.join("injection_tools", "talktl.py"), "qa")
    run(py, os.path.join("injection_tools", "talk.py"), "build")
    run(py, os.path.join("injection_tools", "etctalk.py"), "build")
    run(py, os.path.join("injection_tools", "endtext.py"))
    run(py, "-m", "unittest", "discover", "-s", "tools/tests", "-p", "test_giftmsg_inventory.py")
    run(py, "-m", "unittest", "discover", "-s", "tools/tests", "-p", "test_qol_saves.py")
    for patches, disc_path in variants:
        options = {'make_disc': '--no-disc' not in sys.argv}
        if mark_builder is not None:
            options['mark_builder'] = mark_builder
        if source_image_for is not None:
            options['source_image'] = source_image_for(patches)
        assemble_variant(py, patches, disc_path, **options)
        if after_variant is not None:
            after_variant(patches, disc_path)


if __name__ == "__main__":
    main()
