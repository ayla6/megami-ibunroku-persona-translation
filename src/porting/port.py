"""The port side: PSP-US extraction -> translation/generated.

  python src/porting/port.py

First and foremost it rebuilds the VWF font (make_vwf_font.py): every line
break a porter decides is measured in those advances, so text laid out
against a stale vwf_width.bin wraps wrong in game. Then it runs the
per-family extractors/porters (boot_tables, port_descs, port_affinity, boot_btlmsg, port_btlneg,
boot_s2dnames, port_s2d, port_dng, port_story, port_talk - each still owns
its matching logic) against the per-real-file toolbelt tables. The LAST
step is port_lastresort, scoped to rows no family porter claimed; it is the
last-resort net, not a second owner. This file is the single entry the build calls.
"""
import os
import csv
import subprocess
import sys
import time

# Every porter must see the same set/dict order: a re-run that picks a
# different equal-score candidate is not reproducible.
os.environ['PYTHONHASHSEED'] = '0'

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import toolbelt   # noqa: E402
import etext      # noqa: E402

PY = sys.executable

FAILED = []

# Porters whose PSP-JP matching has a captured, text-free plan. Passing
# --without-psp-jp makes them replay that plan; without a plan they run the
# live two-region match as before.
PLANS = {
    'port_s2d.py': ('s2d_port_plan.tsv',),
    'port_dng.py': ('dng_port_plan.tsv',),
    'port_story.py': ('story_port_plan.tsv',),
    'port_btlevt.py': ('btlevt_port_plan.tsv',),
    'port_answers.py': ('answers_port_plan.tsv',),
    'boot_btlmsg.py': ('eboot_twin_port_plan.tsv', 'reward_notice_port_plan.tsv'),
    'port_btlneg.py': ('eboot_twin_port_plan.tsv',),
    'port_btlbanner.py': ('eboot_twin_port_plan.tsv',),
}


def plan_args(name, args, jp_available=None):
    if jp_available is None:
        jp_available = os.path.exists(os.path.join(
            ROOT, 'data', 'psp_jp', 'PSP_GAME', 'SYSDIR', 'BOOT.BIN'))
    plans = PLANS.get(name)
    if not jp_available and plans and all(os.path.exists(os.path.join(toolbelt.MAPPINGS, p))
                     for p in plans):
        return tuple(args) + ('--without-psp-jp',)
    return args


def run(*cmd, env=None):
    """A step that may legitimately say 'nothing for me'. Its FAILURE is
    never legitimate though: a porter that dies leaves the tables short of
    what the tools can derive, and generated/ is supposed to be complete
    derived data. So a failed step is recorded and fails the port at the
    end."""
    print('+', ' '.join(cmd), flush=True)
    t0 = time.monotonic()
    r = subprocess.run([PY] + list(cmd), check=False, env=env)
    print(f'port: {os.path.basename(cmd[0])} {time.monotonic() - t0:.1f}s', flush=True)
    if r.returncode:
        FAILED.append((os.path.basename(cmd[0]), r.returncode))
        print(f'port: STEP FAILED {os.path.basename(cmd[0])} '
              f'(exit {r.returncode})', flush=True)


def must(*cmd):
    """A step every later one measures by: the port stops when it fails."""
    print('+', ' '.join(cmd), flush=True)
    t0 = time.monotonic()
    subprocess.run([PY] + list(cmd), check=True)
    print(f'port: {os.path.basename(cmd[0])} {time.monotonic() - t0:.1f}s', flush=True)


def port_slps_tables():
    run(toolpath.script('slps.py'), 'dump')
    run(toolpath.script('boot_tables.py'),
        'personas', 'demons', 'items', 'skills', 'nicknames', 'races',
        'banks', 'be')


def clash(a, b):
    """Do two porters' exclusive table dependencies overlap? A set entry is
    a rel or a rel PREFIX ('TALK/' owns every TALK file). A read of a table
    another porter rewrites must also be declared so it cannot race that write."""
    return any(x == y or x.startswith(y) or y.startswith(x)
               for x in a for y in b)


def waves(porters):
    """The porters in DECLARED ORDER, grouped into waves that may run at
    once: a porter joins a wave only when no exclusive table dependency
    overlaps another step. Deterministic (it walks the declared order), so the same
    inputs give the same tables however many workers exist."""
    out = []
    for step in porters:
        for wave in out:
            if not any(clash(step[2], other[2]) for other in wave):
                wave.append(step)
                break
        else:
            out.append([step])
    return out


def validate_generated(root):
    """Reject diagnostic text in every generated translation column."""
    failures = []
    for path in sorted(root.rglob('*.tsv')):
        with path.open(encoding='utf-8', newline='') as source:
            reader = csv.DictReader(source, delimiter='\t')
            if 'en' not in (reader.fieldnames or ()):
                continue
            for line, row in enumerate(reader, 2):
                if etext.has_missing_placeholder(row.get('en') or ''):
                    failures.append(f'{path}:{line}')
    if failures:
        raise ValueError('unresolved missing-text placeholders: ' + ', '.join(failures))


def port_all():
    # Shared correspondence inputs must exist before any reader/worker starts.
    from mappings import ensure
    ensure()
    # Recreate the PSX source extracts independently of manual worklists.
    must(toolpath.script('extract_text_all.py'), '--no-worklists')
    # the font FIRST: every wrap below measures in its advances
    must(toolpath.script('make_vwf_font.py'))
    must(toolpath.script('smallfont_vwf.py'), 'build')
    # The US extract is the wording source. The Japanese extract is only
    # needed by capture-mode matching; a plan-driven port must not demand it.
    jp_boot = os.path.join(ROOT, 'data', 'psp_jp', 'PSP_GAME', 'SYSDIR', 'BOOT.BIN')
    must(toolpath.script('eboot.py'), *([] if os.path.exists(jp_boot) else ['--us-only']))
    # phase 1: the dumps and shared tables. Each writes its own cache; the
    # porters below all read them, so this whole phase goes first.
    port_slps_tables()
    # the record-insert widths (<FF09>/<FF0A>/<FF0B>/<FF0C>/<FF13>): a
    # ported-name fact, derived once the name rows exist and read by every
    # later layout (vwf_wrap.insert_widths prices an insert token with it).
    must(os.path.join(HERE, 'port_widths.py'))
    run(toolpath.script('s2d.py'), 'dump')
    run(toolpath.script('btlp.py'), 'dump')
    run(toolpath.script('dngpacks.py'), 'dump')
    run(toolpath.script('scriptmsg.py'), 'dump')
    run(toolpath.script('casinoprize.py'), 'dump')
    run(toolpath.script('dngnames.py'), 'dump')
    # These rows require the two-region correspondence proof. With only
    # PSP-US, retain their existing canonical rows instead of guessing.
    if os.path.exists(jp_boot):
        must(toolpath.script('psp_build_sources.py'))
    # phase 2: the family PORTERS. Each derives rows for its own files into
    # its own tables; the last element of each entry says WHICH tables, and
    # that is what the schedule is built from - two porters that write the
    # same table must never run at once. Every porter re-reads its table,
    # derives, and writes it back, so a concurrent writer's rows are simply
    # lost. Sequence owners of the same table; locking only the write does
    # not protect the read/derive/write transaction.
    import concurrent.futures as futures
    porters = [
        ('port_descs.py', ('--apply',), ('SLPS_005.00',)),
        ('port_affinity.py', ('--apply',), ('SLPS_005.00',)),
        # the choice grids: laid out per font edition like any other row
        ('choices.py', ('sync-boot',), ('SLPS_005.00',)),
        # every pass re-derives S2D (--force): a filled row is no source,
        # and the other font edition's pass must lay every row out too
        ('port_s2d.py', ('--apply', '--force'), ('S2D',)),
        # Reward matching reads canonical item rows; do not race an SLPS writer.
        ('boot_btlmsg.py', (), ('BTLP', 'SLPS_005.00')),
        ('port_btlevt.py', ('--apply',), ('BTLP',)),
        ('port_btlneg.py', ('--apply',), ('BTLP',)),
        ('port_btlbanner.py', ('--apply',), ('BTLP',)),
        ('port_dng.py', ('--apply',), ('D0', 'D1')),
        ('port_story.py', ('--bulk', '--apply'), ('ADV/',)),
        ('port_talk.py', (), ('TALK/',)),
        ('port_answers.py', ('--apply',), ('TALK/',)),
        ('port_quote.py', (), ('fmv/',)),
    ]

    # A PORTER'S TABLE IS NEVER THE LEFTOVER NET'S (port_derive.LAST_RESORT_TABLES):
    # each row has one derivation owner. Adding a porter for
    # one of the leftover banks means removing it from that list - this makes
    # the overlap impossible to introduce quietly.
    import port_derive as _pd
    _own = [t for _n, _a, tabs in porters for t in tabs]
    _clash = [t for t in _own if t in _pd.LAST_RESORT_TABLES]
    if _clash:
        raise SystemExit('port: a porter writes ' + ', '.join(_clash) +
                         ', which is also the leftover net\'s table '
                         '(port_derive.LAST_RESORT_TABLES) - one owner per table')

    # porters that lay out every font edition themselves write their own
    # rows: the other edition's scratch rows are never merged into them
    SELF_LAID_OUT = ('port_story.py',)

    def one(step):
        name, args = step[:2]
        env = dict(os.environ)
        if name in SELF_LAID_OUT:
            env.pop('PERSONA_EDITION_ROWS', None)
        run(toolpath.script(name), *plan_args(name, args), env=env)

    def schedule(steps):
        for wave in waves(steps):
            print(f'port: wave ({len(wave)}): '
                  + ', '.join(name for name, _a, _w in wave), flush=True)
            with futures.ThreadPoolExecutor(max_workers=toolbelt.jobs()) as pool:
                list(pool.map(one, wave))

    # THE OTHER FONT EDITIONS FIRST (docs/TEXT_LAYOUT_SPEC.md, "Font
    # editions"): every family porter runs once in each other face, writing
    # into a scratch copy of translation/ - never translation/ itself. Then
    # the real pass runs in ROW_EDITION's face, and its one row write lays
    # the other edition's layout of each row into the same cell
    # (toolbelt.upsert_generated, PERSONA_EDITION_ROWS). port_story lays out
    # every edition itself, so it is not run in the scratch pass.
    import shutil
    import vwf_wrap
    others = [e for e in toolpath.FONT_EDITIONS if e != vwf_wrap.ROW_EDITION]
    if len(others) != 1:
        raise SystemExit('port: font editions are merged two at a time')
    scratch = os.path.join(ROOT, 'build', 'edition-translation', others[0])
    shutil.rmtree(scratch, ignore_errors=True)
    shutil.copytree(toolpath.TRANSLATION, scratch)
    saved = {k: os.environ.get(k) for k in ('PERSONA_FONT', 'PERSONA_TRANSLATION')}
    os.environ.update(PERSONA_FONT=others[0], PERSONA_TRANSLATION=scratch)
    try:
        print(f'port: the {others[0]} edition, into {os.path.relpath(scratch, ROOT)}', flush=True)
        schedule([step for step in porters if step[0] not in SELF_LAID_OUT])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    os.environ['PERSONA_EDITION_ROWS'] = scratch
    try:
        print(f'port: the {vwf_wrap.ROW_EDITION} edition, both layouts in each row', flush=True)
        schedule(porters)
    finally:
        os.environ.pop('PERSONA_EDITION_ROWS', None)
    # LAST, and only for leftovers: every family porter above has already
    # claimed its rows. This phase must never rewrite one of their rows.
    must(os.path.join(HERE, 'port_lastresort.py'), '--apply')
    # the viewer's close calls, weighed once here, never by the viewer
    run(os.path.join(HERE, 'close_calls.py'))


def main():
    port_all()
    if FAILED:
        raise SystemExit(f'port: {len(FAILED)} step(s) failed - generated/ '
                         f'is not complete derived data: '
                         + ', '.join(f'{n} ({c})' for n, c in FAILED))
    from pathlib import Path
    try:
        validate_generated(Path(ROOT) / 'translation' / 'generated')
    except ValueError as error:
        raise SystemExit(f'port: {error}') from error


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
