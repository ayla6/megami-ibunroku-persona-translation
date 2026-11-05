"""Port proved PSP boot-table wording into the canonical per-file TSVs."""
import struct

import btlcmd
import btlmsg
import partynames
import personality_source
import tables
import toolbelt


def psp_positions(blob, table, count):
    start, _end = btlcmd.data_segment(blob)
    return [start + rel for rel in struct.unpack_from(f'<{count}I', blob, table)]


def capture():
    psx = btlmsg.data()
    jp, us = tables.jp_boot(), tables.us_boot()
    commands = btlcmd.source_commands(psx, jp, us)
    personalities = personality_source.prove(psx, jp, us)
    names = partynames.psp_full_rows((partynames.SLOTS - partynames.FIRST_PAIR) // 2)
    command_us = psp_positions(us, btlcmd.US_TABLE, btlcmd.COUNT)
    personality_us = psp_positions(us, personality_source.US_TABLE, personality_source.COUNT)
    personality_psx = personality_source.words(
        psx, personality_source.PSX_LABEL_TABLE - btlmsg.B, personality_source.COUNT)
    battle = [{'pos': hex(addr - btlmsg.B), 'psp': f'EBOOT:{source:x}', 'en': text}
              for (addr, text), source in zip(commands, command_us)]
    battle += [{'pos': hex(addr - btlmsg.B), 'psp': f'EBOOT:{source:x}', 'en': text}
               for addr, source, text in zip(personality_psx, personality_us, personalities)]
    party = []
    for i, (source, name) in enumerate(names):
        given, family = name.split(' ', 1)
        slot = partynames.FIRST_PAIR + 2 * i
        for offset, text in enumerate((family, given)):
            party.append({'pos': hex(partynames.BASE + (slot + offset) * partynames.SLOT
                                     - partynames.SLPS_BASE),
                          'psp': f'EBOOT:{source:x}', 'en': text})
    toolbelt.upsert_generated('BTLP', battle)
    toolbelt.upsert_generated(partynames.REL, party)
    print(f'psp boot tables: {len(battle)} battle labels, {len(party)} party-name slots')


if __name__ == '__main__':
    capture()
