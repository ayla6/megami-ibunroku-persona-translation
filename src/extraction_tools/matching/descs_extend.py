"""Extend src/extraction_tools/matching/descs_bank.tsv mechanically.

The description slots of SLPS_005.00 and the PSP-US boot description bank
carry the same sentences in two languages, and `descs_bank.tsv` is the
slot -> bank-offset map between them. This extends the verified pairs
WITHOUT typing anything.

How the correspondences are learned (AGENTS.md: never hardcode a name):
every already-verified pair is a bilingual sentence, so the words that
keep company across those pairs ARE the vocabulary. Tokenize both sides by
script run, count which JP token sits with which EN token, and the element
and status names fall out of the data - 火炎/Fire, 『人形』/Puppet, 衡撃波/
Blast - along with the pure structure the tables are built on:

    敵１ / 敵複 / 敵全   <->   (1 foe) / (area) / (all foes)
    味１ / 味全          <->   (1 ally) / (all allies)
    小 / 中 / 大          <->   Light / Medium / Heavy

An unmapped slot is scored against every unmapped bank entry and taken
only when one candidate is clearly ahead of the rest. Ambiguity is
refused: a wrong offset shows one skill's description on another's.

  python src/extraction_tools/matching/descs_extend.py           report
  python src/extraction_tools/matching/descs_extend.py --apply   write
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
import port_descs        # noqa: E402

JP_TOK = re.compile(r'[一-鿿]+|[ァ-ヶ]+|[ぁ-ん]+|[A-Za-z0-9]+')
EN_TOK = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")
CODE = re.compile(r'<[^>]*>|\[[0-9a-fA-F]{4}\]')


def jtoks(s):
    return [t for t in JP_TOK.findall(CODE.sub('', s)) if len(t) >= 1]


def etoks(s):
    return [t for t in EN_TOK.findall(s) if len(t) >= 2]


def learn(pairs):
    """{(jp token, en token): strength} from the verified pairs - how often
    the two sit together in one sentence, discounted by how often each
    appears without the other."""
    joint = collections.Counter()
    ja_n = collections.Counter()
    en_n = collections.Counter()
    for ja, en in pairs:
        a, b = set(jtoks(ja)), set(etoks(en))
        for x in a:
            ja_n[x] += 1
            for y in b:
                joint[(x, y)] += 1
        for y in b:
            en_n[y] += 1
    score = {}
    for (x, y), n in joint.items():
        # how much of x's evidence for y, over how much noise y draws
        score[(x, y)] = n / (ja_n[x] + en_n[y] - n)
    return score


def score(ja, en, table):
    a, b = set(jtoks(ja)), set(etoks(en))
    if not a or not b:
        return -9.0
    tot = 0.0
    for x in a:
        best = max((table.get((x, y), 0.0) for y in b), default=0.0)
        tot += best
    return tot / len(a)


def main():
    apply = '--apply' in sys.argv
    sm = port_descs.slot_map()
    bank = port_descs.bank_map()
    import boot_pairs
    slots = {k: ja for k, _p, ja in boot_pairs.family_slots()['descs']}
    table = learn([(slots[k], bank[o]) for k, o in sm.items()
                   if k in slots and o in bank])
    used = set(sm.values())
    free = {o: t for o, t in bank.items() if o not in used}
    todo = {k: ja for k, ja in slots.items() if k not in sm}

    add, ambiguous, weak = {}, 0, 0
    for k, ja in sorted(todo.items()):
        ranked = sorted(((score(ja, en, table), o) for o, en in free.items()),
                        reverse=True)
        if not ranked:
            continue
        best, second = ranked[0], ranked[1] if len(ranked) > 1 else (0.0, 0)
        # several candidates carrying the SAME string are not ambiguous -
        # any of them yields the identical wording
        same = (len(ranked) > 1 and free.get(best[1]) == free.get(second[1]))
        if best[0] <= 0.15 or (not same and best[0] - second[0] < 0.12):
            if best[0] > 0.15:
                ambiguous += 1
            else:
                weak += 1
            continue
        add[k] = best[1]
        del free[best[1]]

    for k in sorted(add):
        print(f'  #{k:4} {CODE.sub("", todo[k]).strip()[:30]:32} -> {bank[add[k]]}')
    print(f'\ndescs_extend: {len(add)} new, {ambiguous} ambiguous (refused), '
          f'{weak} too weak (refused)  -  {len(sm)} mapped now')
    if apply and add:
        sm.update(add)
        rows = '\n'.join(f'{k}\t{hex(sm[k])}' for k in sorted(sm))
        with open(port_descs.MAP, 'w', encoding='utf-8', newline='\n') as f:
            f.write('psx_idx\tbank_offset\n' + rows + '\n')
        print(f'wrote {os.path.relpath(port_descs.MAP, ROOT)}: {len(sm)} slots')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
