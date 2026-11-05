"""Adapt physical controller references from paired PSX instructions.

Button symbols / shoulder identifiers followed by 'button(s)' or ボタン,
and lists of multiple face-button symbols, qualify. Descriptive words such
as directional/red/second buttons
are ordinary PSP wording. The two messages must have the same number of
physical-reference groups; each group then takes the PSX control identifiers
in message order. No global circle/cross swap or controller-name dictionary.
"""
import re
import unicodedata

ATOM = r'(?:[○〇×△□]|[LR][12]?)'
SPACE = r'(?:\s|<FF03>|\ue000FF03)*'
SEP = r'(?:[・/＋+&、]|か|,(?:\s*(?:and|or))?|\b(?:and|or)\b)'
BUTTON = re.compile(r'(?<![A-Za-z0-9])(?P<controls>' + ATOM
                    + r'(?:' + SPACE + SEP + SPACE + ATOM + r')*)'
                    + SPACE + r'(?:の各)?(?:ボタン|(?i:buttons?))')
FACE_LIST = re.compile(r'(?P<controls>[○〇×△□](?:' + SPACE + SEP + SPACE
                       + r'[○〇×△□])+)')


def references(text):
    matches = list(BUTTON.finditer(text))
    for m in FACE_LIST.finditer(text):
        if not any(m.start() < b.end() and b.start() < m.end() for b in matches):
            matches.append(m)
    return [(m, tuple(re.findall(ATOM, m['controls'])))
            for m in sorted(matches, key=lambda m: m.start())]


def adapt_buttons(text, ja):
    """Change control identifiers only, before wrapping or writing a row.

    Refuse an unequal reference sequence rather than guessing which action a
    button belongs to. An unchanged group keeps its PSP spelling/separators.
    A PSP single shoulder button may expand to both PSX shoulder buttons.
    """
    source = references(unicodedata.normalize('NFKC', ja or ''))
    target = references(text or '')
    if not source or len(source) != len(target):
        return text
    for (dst, controls), (_src, actual) in reversed(list(zip(target, source))):
        if controls != actual:
            a, b = dst.span('controls')
            text = text[:a] + '・'.join(actual) + text[b:]
    return text


def is_heading(text):
    """Paired captions and marked title-cased lines are structural, not prose."""
    if re.fullmatch(r'\s*(?:【[^【】<>]+】|＞[^＞<>]+＞|＜[^＜＞<>]+＞)\s*', text or ''):
        return True
    # A marked title line, unlike a marked first line of prose, is a run of
    # title-cased words. Learn its structure from casing, never a title list.
    title = re.fullmatch(r'\s*＞\s+([^<>＞]+)\s*', text or '')
    if not title:
        return False
    words = title[1].split()
    return (sum(bool(re.fullmatch(r'[A-Z][A-Za-z\'’-]*', w)) for w in words) >= 2
            and all(re.fullmatch(r'[A-Z][A-Za-z\'’-]*', w)
                    or w in ('a', 'an', 'the', 'of', 'and', 'in', 'on', 'for', 'to')
                    for w in words))
