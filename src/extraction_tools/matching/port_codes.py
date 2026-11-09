"""Interpreter translations, applied in place in the PSP-US stream.

No Japanese text, code counts, word offsets or row identities participate.
Layout owns line/page placement; this module only spells runtime controls.
"""
import re

# PSP's variable operand 0x0082 is the inventory count that ADV exposes as
# its dedicated FF12 instruction. Other variable IDs need their own proven
# interpreter implementation, not a substitute selected from a target row.
ADV_VARIABLES = {0x8200: '<FF12>'}
BATTLE_CODES = {
    '<FF02><FF04>': '<FFFB><FFF7>',
    '<FF04>': '<FFFB><FFF7>',
    '<FF03>': '<FFF6>',
    '<FF02>': '<FFFB>',
    '<FF01>': '',  # the battle string writer appends its own terminator
}
BATTLE_PARAMETERS = {'06': 'FE', '0E': 'F1'}


def adv_variable(parameter):
    try:
        return ADV_VARIABLES[parameter]
    except KeyError:
        raise ValueError(f'unsupported PSP variable FF1A/{parameter:04X}') from None


def dialogue(text):
    """Translate parameterized PSP variable instructions at their occurrence."""
    return re.sub(r'<FF1A><([0-9A-Fa-f]{4})>',
                  lambda m: adv_variable(int(m.group(1), 16)), text)


def battle(text, *, message=False):
    """Translate dialogue controls to the battle interpreter, in situ.

    Already-battle controls pass through. The actor's given name has one
    battle counterpart; no Japanese occurrence count limits its translation.
    FF05's timed dialogue beat uses battle's fixed-duration wait instruction.
    """
    text = re.sub(r'<FF07>(?:<[0-9A-Fa-f]{2}>)?', '<FFF9>', text)
    def parameter(m):
        value = m.group(2)
        if len(value) == 4 and value[2:] != '00':
            raise ValueError(f'PSP FF{m.group(1)} operand does not fit the battle interpreter')
        return f'<FF{BATTLE_PARAMETERS[m.group(1)]}><{value[:2]}>'
    text = re.sub(r'<FF(06|0E)><([0-9A-Fa-f]{4}|[0-9A-Fa-f]{2})>', parameter, text)
    if not message:
        text = re.sub(r'<FF05>(?:<[0-9A-Fa-f]{4}>|<[0-9A-Fa-f]{2}><[0-9A-Fa-f]{2}>)?',
                      '<FFFC>', text)
    # BtlOpenMessage owns a terminal PSP wait through its caller's wait flag;
    # msg_script validates that form. Turning it into a HOLD would add a
    # second acknowledgement. Interior waits must reach that validator too.
    mapping = ({'<FF01>': '', '<FF03>': '<FFF6>'} if message else BATTLE_CODES)
    return re.sub('|'.join(re.escape(c) for c in mapping),
                  lambda m: mapping[m.group()], text)
