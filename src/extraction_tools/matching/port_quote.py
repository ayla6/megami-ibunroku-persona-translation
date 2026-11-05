"""Port the opening-movie quote (the Zhuangzi butterfly lines burned into
MV1C.STR) from the PSP-US BOOT.BIN title-quote table.

The quote is burned into the movie, not text the game reads, so it has its
own table (like the subtitles): translation/generated/fmv/opening.tsv,
line | source | text - the line's place in the card, its EBOOT source unit,
the PSP-US wording verbatim. A line filled in translation/manual/fmv/
opening.tsv (same columns) wins. The band layout (pins, alignment) lives in
fmv_layout.py - movie geometry.

  python src/extraction_tools/matching/port_quote.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import toolbelt  # noqa: E402
import boot       # noqa: E402
import port_derive  # noqa: E402  (the PSP's head marks: furniture, never wording)


def main():
    lines = boot.quote_us(boot.us_boot())
    # A PSP-US title line can open with the PSP's own head decoration ('＾'
    # before the attribution, U+FF3E - the JP build spells the same mark). The
    # movie card is ours: it has no such cell and the PSX never had one, so the
    # mark is furniture and does not enter the stored wording (the same rule the
    # textbox pipeline applies to the box head, port_derive.head_marks).
    out = os.path.join(ROOT, 'translation', 'generated', 'fmv', 'opening.tsv')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('line\tsource\ttext\n')
        for i, (off, text) in enumerate(lines):
            f.write(f"{i}\tEBOOT:{off:x}\t{port_derive.head_marks(text, '')}\n")
    print(f'port_quote: {len(lines)} quote lines -> {os.path.relpath(out, ROOT)}')


if __name__ == '__main__':
    main()
