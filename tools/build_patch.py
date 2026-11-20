"""Build one configured mod layer, without rebuilding the release.

Example: python tools/build_patch.py 'softer-menu-sounds(level=75)'
The result belongs to the chosen language tier and discrete choices.
Declared numeric settings remain adjustable when the patch is applied. It is
written separately from the complete release, which is never modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import toolpath
import mods
import modpack
import build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mod', help='one mod slug, optionally followed by (choices)')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/single-patches')
    parser.add_argument('--tier', choices=('base', 'alphabet', 'english'), default='english')
    args = parser.parse_args()
    picked = mods.parse_mods(args.mod)
    if len(picked) != 1:
        parser.error('choose exactly one mod')
    slug, choices = picked[0]
    by_slug = {m.slug: m for m in mods.load()}
    if slug not in by_slug or by_slug[slug].always or by_slug[slug].marker:
        parser.error('choose an optional mod; foundation layers need a full release build')
    mod = by_slug[slug]
    tokens = mod.pick(choices)
    build_tokens = sorted(t for t in tokens if t.split('=')[0] not in {r.key for r in mod.ranges})
    build_tokens += [f'{r.key}={r.default}' for r in mod.ranges]
    configured = mod.slug + ('(' + ','.join(build_tokens) + ')' if build_tokens else '')
    requires = [label for label in mod.requires if mods.by_label()[label].release]
    tier = {'base': 'base', 'alphabet': 'latin-alphabet', 'english': 'english-translation'}[args.tier]
    if tier not in requires:
        requires.append(tier)
    baseline = [by_slug_label.slug for label in requires
                if not (by_slug_label := mods.by_label()[label]).always
                and not by_slug_label.marker]
    flags = {'base': ['--base-only'], 'alphabet': ['--engine-only'], 'english': []}[args.tier]
    command = [sys.executable, str(ROOT / 'src/pipeline/build.py'), '--no-disc', *flags]
    source = modpack.Source(build.ORIGINAL_IMAGE)
    try:
        subprocess.run([*command, '--no-verify', *(['--mods=' + ','.join(baseline)] if baseline else [])], cwd=ROOT, check=True)
        before = {p: Path(local).read_bytes() for p, local in modpack.tree(str(ROOT / 'build'), source).items()}
        subprocess.run([*command, '--mods=' + ','.join([*baseline, configured])], cwd=ROOT, check=True)
        after = {p: Path(local).read_bytes() for p, local in modpack.tree(str(ROOT / 'build'), source).items()}
        delta = modpack.layer_from(mod.label, source, before, after, check_source=True)
        pack = modpack.Pack(mod.label, [modpack.Part('', delta.files)],
                            mod.name + (" (" + ", ".join(sorted(tokens)) + ")" if tokens and not mod.ranges else ""), mod.description,
                            requires=requires)
        base = modpack.layer_from('baseline', source, {}, before, check_source=True)
        result, _clashes = modpack.merge(source, [base, delta], strict=False, track_clashes=False)
        for path in set(before) | set(after):
            raw = path.endswith('.STR')
            expected = after.get(path, source.read(path, raw))
            actual = bytes(result[path]) if path in result else source.read(path, raw)
            if raw:
                expected, actual = modpack.build_disc.raw_body(expected), modpack.build_disc.raw_body(actual)
            if actual != expected:
                raise RuntimeError(f'{path}: single layer does not reproduce its build')
        # Serialization is independently read back before the output is accepted.
        args.output.mkdir(parents=True, exist_ok=True)
        target = args.output / (mod.slug + '.p1mod')
        if mod.ranges:
            from dataclasses import replace
            modpack.bind_ranges(pack, mod)
            selected_values = dict(t.split('=', 1) for t in tokens if '=' in t)
            pack.ranges = [replace(r, default=r.validate(selected_values[r.key])) for r in pack.ranges]
        modpack.save(str(target), pack)
        if modpack.read_layer(str(target)) != pack:
            raise RuntimeError('serialized layer differs from verified edits')
        print(f'Single configured patch: {target}; tier={args.tier}; choices={",".join(sorted(tokens))}')
    finally:
        source.close()


if __name__ == '__main__':
    main()
