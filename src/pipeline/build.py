"""One-step build: tables -> VWF font -> event scripts -> armips -> patched disc image.

Usage (from the project root):
    python src/pipeline/build.py [--image PATH] [--no-disc] [--port] [--mods[=NAME,...]]
Output: build/ (intermediates) and dist/ (final patched BIN/CUE)
--image: the original disc image (default: data/discs/Megami Ibunroku Persona - Be Your True Mind (Japan)/...). It
         must be the first release (not Rev 1): see image_check.py.
--mods: a build with mods, written to dist/Persona-TL-mods.bin/.cue instead. Mods are picked by their
       label (src/mods/*/mod.tsv), e.g. `--mods=unified-save-menu,60-fps` (a space instead of `=` works too).
       `--mods` alone selects the mods marked default; `--mods=LABEL,...` selects
       only the named mods. `--mods=all` enables every mod and
       `--no-mods=LABEL` excludes one. `--mods=list` lists them.
--port: rerun PSP extraction/matching and trim worklists before building. Without it (the
        default) the current translation tables are built; every text/graphics builder,
        assembly and placement check still runs.
--clean: regenerate every cached preparation step. Without it a step is reused
         when its inputs and outputs match the last successful run.
--variants=base;unified-save-menu;unified-save-menu,60-fps: build each named patch combination after one
           common preparation (quote the argument so the shell keeps semicolons).
--mods='english-translation(font=small)': a mod's choices, in parentheses
         after it (its mod.tsv; the first of each group is the default).
         The small font: every tool measures and draws with
         small_serif.png, written to dist/Persona-TL-small.bin (-mods-small
         with mods). `--mods=list` lists every mod and choice.
--no-verify: leave out source QA, the checks that read assembled files back and
         the tests of assembled output (the release's variants: their output
         is compared with their layers instead).
--base-only: the language-neutral base without the Latin alphabet component.
--engine-only: the engine and Latin alphabet without English (the base mod, no English): every tool reads
         build/engine-translation, translation/ with its English emptied
         (engine_translation.py), so each row keeps its Japanese. Mods that
         require english are refused. Written to dist/Persona-engine.bin.
"""
import os
from pathlib import Path
import sys
BASE_ONLY = '--base-only' in sys.argv
ENGINE_ONLY = '--engine-only' in sys.argv or BASE_ONLY
if BASE_ONLY:
    os.environ['PERSONA_BASE_ONLY'] = '1'
    sys.argv.extend(['--no-sf-vwf', '--no-sf-latin'])
if ENGINE_ONLY:   # before any tool reads toolpath.TRANSLATION, here or in the tools it runs
    os.environ['PERSONA_ENGINE_ONLY'] = '1'     # mods.with_needs: English's choices are off
    os.environ['PERSONA_TRANSLATION'] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'build', 'engine-translation')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import re
import time
import shutil
import subprocess

import disc_data
import image_check

# Python randomises str hashes per process: some tools pack strings in set / dict order, so pin the seed
# for every tool started below to make the build byte-for-byte reproducible.
os.environ["PYTHONHASHSEED"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORIGINAL_IMAGE = os.path.join(ROOT, 'data', 'discs', image_check.NAME, image_check.NAME + '.bin')
if "--image" in sys.argv:
    ORIGINAL_IMAGE = os.path.abspath(sys.argv[sys.argv.index("--image") + 1])
# The mods a build can turn on (src/mods/*/mod.tsv, read by mods.py; the
# always-on tiers are always in), by label: each one's define turns its
# assembly in build/main.asm (asm_main.py writes it from the mods that are
# on; the defines let a mod's files ask about another). A build names them by their names' slugs
# (--mods=unified-save-menu), and a mod's choices in parentheses after it
# (--mods=english-translation(font=small)); an always-on mod is named only for
# its choices.
import mods as _mods
MODS = {mod.label: (mod.define, mod.description) for mod in _mods.options()}
MODS_DEFAULT = [mod.label for mod in _mods.options() if mod.default]


def _mod_args(argv):
    """(option, [(name, picked)]) for every --mods / --no-mods argument:
    each named mod with what its parentheses pick (mods.parse_mods)."""
    for i, arg in enumerate(argv):
        option = arg.split('=', 1)[0]
        if option not in ('--mods', '--no-mods'):
            continue
        names = arg.split('=', 1)[1] if '=' in arg else ''
        if not names and i + 1 < len(argv) and not argv[i + 1].startswith('-'):
            names = argv[i + 1]
        try:
            picked = _mods.parse_mods(names)
        except ValueError as error:
            raise SystemExit(f'build.py: {error}')
        if option == '--no-mods' and any(p for _n, p in picked):
            raise SystemExit('build.py: --no-mods takes mod names, not their choices')
        yield option, picked


def selected_options(argv=None):
    """{mod label: frozenset of choice tokens} for every mod with choices:
    what the command line picks in its parentheses, over its defaults."""
    argv = sys.argv[1:] if argv is None else argv
    out = {mod.label: mod.defaults() for mod in _mods.load() if mod.choices or mod.ranges}
    named = _mods.by_name()
    for _option, picked in _mod_args(argv):
        for name, choice in picked:
            if choice and name in named:
                try:
                    out[named[name].label] = named[name].pick(choice)
                except ValueError as error:
                    raise SystemExit(f'build.py: {error}')
    return out


def option_key(label, group, options=None):
    """The KEY a mod's GROUP is at in this build."""
    for token in (OPTIONS if options is None else options).get(label, ()):
        if token.startswith(group + '='):
            return token.split('=', 1)[1]
    raise KeyError(f'{label} has no {group} group')


OPTIONS = selected_options()
# The dialogue font is the English mod's `font` group (large / small): every
# tool this build runs measures and draws with that face.
FONT = option_key('english-translation', 'font')
os.environ['PERSONA_FONT'] = FONT

ORIGINAL_DIR = os.path.join(ROOT, 'data', 'psx')
ASM_ROOT = os.path.join(ROOT, 'src', 'mods', 'base', 'asm')
ARMIPS = next((p for p in (os.path.join(ROOT, "external_tools", "armips", "armips.exe"),
                            os.path.join(ROOT, "external_tools", "armips", "armips"))
               if os.path.exists(p)), None) or shutil.which("armips")


def by_name(cmd):
    """A command whose script is given by name (`btlp.py`) runs that tool,
    wherever its folder is (toolpath.script)."""
    if len(cmd) > 1 and isinstance(cmd[1], str) and cmd[1].endswith('.py') \
            and not os.path.isabs(cmd[1]) and os.sep not in cmd[1]:
        cmd = (cmd[0], toolpath.script(cmd[1]), *cmd[2:])
    return cmd


def run(*cmd):
    cmd = by_name(cmd)
    print("+", " ".join(os.path.relpath(c, ROOT) if os.path.isabs(c) else c for c in cmd))
    timed(cmd, ROOT)


def run_all(*cmds):
    """Run independent commands at once (read-only checks of the same build
    tree); each one's output is printed whole, in the order given, and the
    first failure raises after all have finished."""
    procs = []
    for cmd in cmds:
        cmd = by_name(cmd)
        procs.append((cmd, subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)))
    failed = None
    start = time.monotonic()
    io = disk_io()
    for cmd, proc in procs:
        out, _ = proc.communicate()
        print("+", " ".join(os.path.relpath(c, ROOT) if os.path.isabs(c) else c for c in cmd))
        sys.stdout.write(out.decode('utf-8', 'replace'))
        if proc.returncode and failed is None:
            failed = subprocess.CalledProcessError(proc.returncode, cmd)
    print(f"= {time.monotonic() - start:6.1f} s  {len(procs)} checks at once{io_note(io)}",
          flush=True)
    if failed:
        raise failed


def run_from(cwd, *cmd):
    print("+", " ".join(os.path.relpath(c, ROOT) if os.path.isabs(c) else c for c in cmd))
    timed(cmd, cwd)


def disk_io():
    """(bytes read, bytes written) on disk by every finished child so far -
    the kernel's block counts (512 bytes each); what came from the page
    cache is not a disk read and is not counted."""
    import resource
    used = resource.getrusage(resource.RUSAGE_CHILDREN)
    return used.ru_inblock * 512, used.ru_oublock * 512


def io_note(before):
    """`  read 12 MB, wrote 3 MB` since `before` (disk_io), or '' when the
    step barely touched the disk."""
    read, wrote = (now - then for now, then in zip(disk_io(), before))
    if read + wrote < 1 << 20:
        return ''
    return f'  (disk: read {read >> 20} MB, wrote {wrote >> 20} MB)'


def timed(cmd, cwd):
    """Run one step; its time and its disk traffic are printed, so the slow
    or heavy steps show in the log (`grep '^= '`)."""
    start = time.monotonic()
    io = disk_io()
    subprocess.run(cmd, cwd=cwd, check=True)
    name = next((os.path.relpath(c, ROOT) for c in cmd[1:] if isinstance(c, str)
                 and c.endswith(('.py', '.asm'))), os.path.basename(cmd[0]))
    print(f"= {time.monotonic() - start:6.1f} s  {name}{io_note(io)}", flush=True)


def selected_mods(argv=None):
    """The labels of the mods a command line turns on, in apply order:
    explicit names (or a bare --mods: the defaults), then exclusions. Names
    are the mods' slugs; an always-on mod is only named for its choices
    (`english-translation(font=small)`), which turns nothing on."""
    argv = sys.argv[1:] if argv is None else argv
    named = _mods.by_name()
    enabled, disabled = set(), set()
    for option, picked in _mod_args(argv):
        names = [name for name, _choice in picked]
        if names == ['list'] and option == '--mods':
            for mod in _mods.load():
                if mod.label in MODS and not mod.marker:
                    print(f"{mod.slug}{' (default)' if mod.label in MODS_DEFAULT else ''}: {mod.description}")
                for setting in mod.ranges:
                    print(f"  {mod.slug}({setting.key}=VALUE): {setting.name}; "
                          f"{setting.minimum}..{setting.maximum}, step {setting.step}, default {setting.default}")
                for group, options in mod.groups().items():
                    for o in options:
                        first = ' (default)' if o is options[0] else ''
                        print(f"  {mod.slug}({o.token}){first}: {o.description}")
                for o in mod.choices:
                    if not o.group:
                        print(f"  {mod.slug}({o.token}): {o.description}")
            raise SystemExit(0)
        unknown = [n for n in names if n != 'all' and n not in named]
        if unknown:
            raise SystemExit(f"build.py: unknown mod {', '.join(unknown)}\n"
                             f"  available: {', '.join(n for n, m in named.items() if (m.label in MODS or m.choices) and not m.marker)}, all"
                             "\n  (`--mods=list` explains each)")
        markers = [n for n in names if n in named and named[n].marker]
        if markers:
            raise SystemExit(f"build.py: {', '.join(markers)} is a dependency, never picked:"
                             " it is on when a mod or a choice requires it")
        always = [n for n, choice in picked if n in named and named[n].label not in MODS
                  and not choice]
        if always:
            raise SystemExit(f"build.py: {', '.join(always)} is always on (name it only"
                             " with its choices in parentheses)")
        if option == '--no-mods' and not names:
            raise SystemExit('build.py: --no-mods requires mod names (or all)')
        mods_named = [named[n].label for n in names if n != 'all' and named[n].label in MODS]
        only_choices = [n for n in names if n != 'all' and named[n].label not in MODS]
        if option == '--mods' and not mods_named and 'all' not in names and not only_choices:
            mods_named = MODS_DEFAULT
        target = disabled if option == '--no-mods' else enabled
        target.update([m.label for m in _mods.pickable()] if 'all' in names else mods_named)
    return [name for name in MODS if name in enabled and name not in disabled]


MODDED = bool(selected_mods())
PATCHED_IMAGE = os.path.join(ROOT, 'dist', ('Persona-engine' if ENGINE_ONLY
                                           else 'Persona-TL-mods' if MODDED else 'Persona-TL')
                             + ('' if FONT == toolpath.FONT_EDITIONS[0] else '-' + FONT) + '.bin')






def prepare_tables(py: str, incremental: bool = False) -> None:
    import alphabet_preparation
    alphabet_preparation.prepare_tables(py, incremental, run=run)


def prepare_vwf_font(py: str, incremental: bool = False) -> None:
    import alphabet_preparation
    alphabet_preparation.prepare_vwf_font(py, incremental, run=run)






def fmv_parts() -> list[str]:
    import translation_preparation
    return translation_preparation.fmv_parts(option_key('english-translation', 'subtitles'))


def prepare_fmv_data(py: str, incremental: bool = False) -> None:
    import translation_preparation
    translation_preparation.prepare_fmv_data(
        py, incremental, subtitles=option_key('english-translation', 'subtitles'), run=run)


def build_variants(argv):
    """[(patches, disc path)] for one build or a named batch of combinations."""
    if '--variants' in argv:
        raise SystemExit('build.py: use --variants=base;unified-save-menu (quote the argument)')
    args = [a for a in argv if a.startswith('--variants=')]
    if not args:
        return [(selected_mods(argv), PATCHED_IMAGE)]
    if len(args) != 1:
        raise SystemExit('build.py: provide exactly one --variants=... option')
    if any(a in ('--mods', '--no-mods') or a.startswith(('--mods=', '--no-mods=')) for a in argv):
        raise SystemExit('build.py: --variants cannot be combined with --mods or --no-mods')
    if '--no-disc' in argv:
        raise SystemExit('build.py: --variants creates discs and cannot be combined with --no-disc')
    choices = args[0].split('=', 1)[1].split(';')
    if not choices or any(not c.strip() for c in choices):
        raise SystemExit('build.py: --variants needs semicolon-separated combinations')
    variants, seen = [], set()
    for choice in choices:
        patches = [] if choice.strip() == 'base' else selected_mods(['--mods=' + choice.strip()])
        key = tuple(patches)
        if key in seen:
            raise SystemExit('build.py: duplicate patch combination in --variants')
        seen.add(key)
        label = '-'.join(patches) if patches else 'base'
        variants.append((patches, os.path.join(ROOT, 'dist', f'Persona-TL-{label}.bin')))
    return variants


def assemble_variant(py, patches, disc_path, make_disc=True, source_image=None):
    """Assemble and verify one patch set, then publish its separate disc.

    `source_image` is the image the variant is written onto. It defaults to
    the retail disc, but a release may pass an already-built less-patched
    variant: build_disc then rewrites only the files this variant changes,
    and the filesystem shares the rest of the clone's extents."""
    print(f"build.py: mods: {', '.join(patches) or 'none'} -> {os.path.relpath(disc_path, ROOT)}")
    # Clear the previous variant before assembly; assembly recreates MES.BIN.
    import image_replacements
    import mod_build
    mod_build.restore(enabled=frozenset(patches))
    # Assembly recreates MES; ending preparation resets its portrait. Keep
    # those existing files available for the unchanged-output comparison.
    image_replacements.restore()
    # END.BIN and build/end_roll.asm (armips input): the dub's English voice
    # cast page only with the dub
    import preparation_cache
    ending_args = mod_build.arguments([_mods.by_label()[name] for name in patches],
                                      'ending', option_key)
    preparation_cache.ending(
        lambda: run(py, 'endtext.py', *ending_args),
        FONT, ending_args, '--clean' not in sys.argv)
    mod = [x for name in patches for x in ('-definelabel', MODS[name][0], '1')]
    mod += ['-definelabel', 'BASE_NEGOTIATION_INSET',
            '1' if option_key('base', 'negotiation-inset') == 'on' else '0']
    if FONT != 'large':
        mod += ['-definelabel', 'FONT_' + FONT.upper(), '1']
    listing = os.path.join(ROOT, 'build', 'armips-main.lst')
    # -erroronwarning: every armips warning (load delay, branch delay slot,
    # ...) is a real runtime bug in this codebase. Never ship an image whose
    # hooks assembled with a warning - fail the build instead.
    # build/main.asm is written from the mods that are on (asm_main.py: each
    # mod's asm.tsv); armips runs from ASM_ROOT, which its paths are relative to.
    import asm_main
    import armips_products
    with armips_products.memory_outputs(armips_products.main_products(Path(ROOT)),
                                        Path(ROOT) / 'build') as outputs:
        asm_main.write(list(patches), outputs=outputs)
        run_from(ASM_ROOT, ARMIPS, '-erroronwarning', os.path.relpath(asm_main.OUT, ASM_ROOT),
                 '-sym2', os.path.join(ROOT, 'build', 'persona.sym'),
                 '-temp', listing, *mod)
    # The checks below only read the assembled tree: run them together.
    # --no-verify (the release's variants: what matters there is the output
    # each one builds, compared with its layers) leaves them all out.
    verify = '--no-verify' not in sys.argv
    checks = [(py, 'write_guard.py', 'check', '--listing', listing),
              (py, 'scratch_map.py', 'verify')]
    if not BASE_ONLY:
        checks.append((py, 'make_vwf_font.py', 'verify'))
    import features
    if features.on('SF_VWF'):
        checks += [(py, 'smallfont_vwf.py', 'verify'),
                   (py, 'btlfont.py', 'verify')]
    checks += [(py, name + '.py', 'verify')
               for name in (('btlp', 'btlcmd', 'btlui', 'sysmsg') if BASE_ONLY else
                            ('dngspill', 'btlp', 'btlcmd', 'btlui', 'dngnames', 'sysmsg'))]
    if verify:
        run_all(*checks)
        if BASE_ONLY:
            # No alphabet-owned name-entry code may leak into the base.
            for name in ('NAME.BIN', 'NAMEDT.BIN'):
                if open(os.path.join(ROOT, 'build', name), 'rb').read() != open(
                        os.path.join(ORIGINAL_DIR, name), 'rb').read():
                    raise SystemExit(f'base tier: {name} differs from retail')
            import title_gfx
            import tim
            for name, offset, _rect, _fill, _ink, text in title_gfx.EDITS:
                if text:
                    continue
                original = open(os.path.join(ORIGINAL_DIR, name), 'rb').read()
                built = open(os.path.join(ROOT, 'build', name), 'rb').read()
                texture = tim.parse(original, offset)
                start = texture['at']
                end = start + texture['w'] * 2 * texture['h']
                if built[start:end] != original[start:end]:
                    raise SystemExit(f'base tier: untranslated title art in {name} changed')

    if not verify and ENGINE_ONLY:
        run(py, 'write_guard.py', 'check', '--listing', listing)
    run(py, 'casinoprize.py')
    # Declarative image mods share one compiler and verify their generated art.
    for label in patches:
        if Path(_mods.by_label()[label].folder, 'images.tsv').is_file():
            run(py, 'image_replacements.py', 'build', label)
            if verify:
                run(py, 'image_replacements.py', 'verify', label)
    for label in patches:
        for command in mod_build.commands(_mods.by_label()[label], verify, option_key):
            run(py, *command)
        import range_parameters
        range_parameters.apply_files(
            Path(ROOT), Path(ROOT) / 'build', _mods.by_label()[label].ranges,
            lambda key: option_key(label, key))
    if make_disc:
        os.makedirs(os.path.dirname(disc_path), exist_ok=True)
        run(py, 'build_disc.py',
            source_image or ORIGINAL_IMAGE, disc_path, 'build',
            disc_path + '.placement.tsv')


def main(variants_override=None, after_variant=None, source_image_for=None, before_variant=None):
    global ORIGINAL_IMAGE
    py = sys.executable
    variants = (build_variants(sys.argv[1:]) if variants_override is None
                else variants_override)  # reject invalid combinations before regenerating assets
    # the markers each variant's mods and picked choices require come along
    variants = [(_mods.with_needs(list(patches), OPTIONS), disc) for patches, disc in variants]
    # the font edition build/ is assembled in, for whatever checks build/
    # later (tools/run_tests.py measures in it: toolpath.built_edition)
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    with open(toolpath.BUILT_EDITION_FILE, 'w', encoding='utf-8') as f:
        f.write(FONT + '\n')
    if ENGINE_ONLY:
        needs = sorted({label for patches, _disc in variants for label in patches
                        if set(_mods.by_label()[label].requires) &
                        ({'english-translation', 'latin-alphabet'} if BASE_ONLY else {'english-translation'})})
        if needs:
            sys.exit(f"build.py: this tier omits a required component for: {', '.join(needs)}")
        import engine_translation
        print(f"build.py: engine only: {os.path.relpath(engine_translation.make(), ROOT)}")
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
    port = '--port' in sys.argv     # porting is opt-in; --no-port is the default (and still accepted)
    if port:
        # Porting reads the PSP-US tree; discover and extract it the same way
        # when the contributor left a PSP image in data/discs/.
        disc_data.ensure_psp('us')
        from mappings import ensure
        ensure()
    incremental = '--clean' not in sys.argv
    import translation_preparation
    def prepare():
        translation_preparation.prepare(
            Path(ROOT), py, run, port=port, gates=gates,
            verify='--no-verify' not in sys.argv,
            tables=lambda: prepare_tables(py, incremental=incremental),
            font=lambda: prepare_vwf_font(py, incremental=incremental))
    import preparation_cache
    if port:
        prepare()
    else:
        preparation_cache.prepare(prepare, FONT, gates, incremental,
                                  '--no-verify' not in sys.argv)

    def prepare_movies():
        # In-engine FMV subtitles: data blobs (full for MOVIE.EXE, quote-only for
        # OPEN.EXE), then the renderer code (its own armips pass at 0x80160000),
        # then pack each into build/movie_subs*.bin
        # Only when a variant has the renderer on (the fmv marker: English's movie
        # subtitles or movie text require it).
        if any('fmv-translation' in patches for patches, _disc in variants):
            prepare_fmv_data(py, incremental='--clean' not in sys.argv)
            subs_listing = os.path.join(ROOT, "build", "armips-subs.lst")
            run_from(ASM_ROOT, ARMIPS, '-erroronwarning', os.path.join("..", "..", "fmv-translation", "subs_code.asm"),
                     "-sym2", os.path.join(ROOT, "build", "movie_subs.sym"),
                     "-temp", subs_listing)
            run(py, "write_guard.py", "check", "--listing", subs_listing)
            run(py, "fmv_subgen.py", "pack")
    if any('fmv-translation' in patches for patches, _disc in variants):
        preparation_cache.movies(prepare_movies, FONT, incremental)
    assembled_tests_run = False
    for patches, disc_path in variants:
        if before_variant is not None and not before_variant(patches, disc_path):
            continue  # The caller consumed a hash-checked native snapshot.
        options = {'make_disc': '--no-disc' not in sys.argv}
        if source_image_for is not None:
            options['source_image'] = source_image_for(patches)
        assemble_variant(py, patches, disc_path, **options)
        if not assembled_tests_run and '--no-verify' not in sys.argv:
            # These tests execute assembled outputs (ADV.BIN, SLPS_005.00,
            # OPEN.EXE, the symbol file), so they need a variant on disk. A
            # clean build/ has none before the first assembly. One variant is
            # enough: every patch set carries the same translation code they
            # exercise, and a mod that broke it would fail here.
            run(py, 'run_tests.py', 'test_giftmsg_inventory.py', 'test_overlay_clones.py',
                'test_title_load_vwf.py',
                *([] if BASE_ONLY else ['test_mod_saves.py', 'test_msg_name_inserts.py']))
            assembled_tests_run = True
        if after_variant is not None:
            after_variant(patches, disc_path)


if __name__ == "__main__":
    main()
