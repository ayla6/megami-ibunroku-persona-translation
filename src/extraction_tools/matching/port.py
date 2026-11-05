"""The port side: PSP-US extraction -> translation/generated.

  python src/extraction_tools/matching/port.py

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
import subprocess
import sys

# Every porter must see the same set/dict order: a re-run that picks a
# different equal-score candidate is not reproducible.
os.environ['PYTHONHASHSEED'] = '0'

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'injection_tools'))
import toolbelt   # noqa: E402

PY = sys.executable
INJ = os.path.join(HERE, '..', '..', 'injection_tools')
PSP = os.path.join(HERE, '..', 'psp')

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


def plan_args(name, args):
    plans = PLANS.get(name)
    if plans and all(os.path.exists(os.path.join(toolbelt.MAPPINGS, p))
                     for p in plans):
        return tuple(args) + ('--without-psp-jp',)
    return args


def run(*cmd):
    """A step that may legitimately say 'nothing for me'. Its FAILURE is
    never legitimate though: a porter that dies leaves the tables short of
    what the tools can derive, and generated/ is supposed to be complete
    derived data. So a failed step is recorded and fails the port at the
    end."""
    print('+', ' '.join(cmd), flush=True)
    r = subprocess.run([PY] + list(cmd), check=False)
    if r.returncode:
        FAILED.append((os.path.basename(cmd[-1]), r.returncode))
        print(f'port: STEP FAILED {os.path.basename(cmd[-1])} '
              f'(exit {r.returncode})', flush=True)


def must(*cmd):
    """A step every later one measures by: the port stops when it fails."""
    print('+', ' '.join(cmd), flush=True)
    subprocess.run([PY] + list(cmd), check=True)


def port_slps_tables():
    run(os.path.join(INJ, 'slps.py'), 'dump')
    run(os.path.join(PSP, 'boot_tables.py'),
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


def port_all():
    # Shared correspondence inputs must exist before any reader/worker starts.
    from mappings import ensure
    ensure()
    # the font FIRST: every wrap below measures in its advances
    must(os.path.join(INJ, 'make_vwf_font.py'))
    must(os.path.join(INJ, 'smallfont_vwf.py'), 'build')
    # The US extract is the wording source. The Japanese extract is only
    # needed by capture-mode matching; a plan-driven port must not demand it.
    jp_boot = os.path.join(ROOT, 'data', 'psp_jp', 'PSP_GAME', 'SYSDIR', 'BOOT.BIN')
    must(os.path.join(PSP, 'eboot.py'), *([] if os.path.exists(jp_boot) else ['--us-only']))
    # phase 1: the dumps and shared tables. Each writes its own cache; the
    # porters below all read them, so this whole phase goes first.
    port_slps_tables()
    run(os.path.join(INJ, 'choices.py'), 'sync-boot')
    run(os.path.join(INJ, 's2d.py'), 'dump')
    run(os.path.join(INJ, 'btlp.py'), 'dump')
    run(os.path.join(INJ, 'dngpacks.py'), 'dump')
    run(os.path.join(INJ, 'scriptmsg.py'), 'dump')
    run(os.path.join(INJ, 'casinoprize.py'), 'dump')
    run(os.path.join(INJ, 'dngnames.py'), 'dump')
    # These rows require the two-region correspondence proof. With only
    # PSP-US, retain their existing canonical rows instead of guessing.
    if os.path.exists(jp_boot):
        must(os.path.join(INJ, 'psp_build_sources.py'))
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
        ('port_s2d.py', ('--apply',), ('S2D',)),
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

    def one(step):
        name, args = step[:2]
        run(os.path.join(HERE, name), *plan_args(name, args))
    for wave in waves(porters):
        print(f'port: wave ({len(wave)}): '
              + ', '.join(name for name, _a, _w in wave), flush=True)
        with futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            list(pool.map(one, wave))
    # LAST, and only for leftovers: every family porter above has already
    # claimed its rows. This phase must never rewrite one of their rows.
    must(os.path.join(HERE, 'port_lastresort.py'), '--apply')


def main():
    port_all()
    if FAILED:
        raise SystemExit(f'port: {len(FAILED)} step(s) failed - generated/ '
                         f'is not complete derived data: '
                         + ', '.join(f'{n} ({c})' for n, c in FAILED))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
