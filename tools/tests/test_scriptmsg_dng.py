"""The DNG.BIN FF55 messages are text, and their name-insert ids are not."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import etext      # noqa: E402
import scriptmsg  # noqa: E402
import toolbelt   # noqa: E402


class DngScriptMessages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = open(os.path.join(ROOT, 'data', 'psx', 'DNG.BIN'), 'rb').read()

    def test_scan_decodes_the_two_messages_without_their_ids(self):
        got = scriptmsg.messages(self.data, scriptmsg.NAME_PARAMS)
        self.assertEqual([off for off, _ja in got], [0x35DC8, 0x35DF0])
        self.assertEqual(
            [ja for _off, ja in got],
            ['<FF09><12><00>の効果がきれた<FF02><FF01>',
             '<FF0A><73>の効果がきれた<FF02><FF01>'])

    def test_ids_are_arguments_only_where_the_caller_says_they_are(self):
        # The event codec does not know FF09/FF0A: without the DNG table the
        # id bytes decode as kana. With it they are the code's argument.
        seg = self.data[0x35DC8:0x35DC8 + 17]
        self.assertTrue(etext.decode(seg).startswith('<FF09>つ'))
        self.assertTrue(etext.decode(seg, scriptmsg.NAME_PARAMS)
                        .startswith('<FF09><12><00>'))

    def test_row_tokens_encode_the_source_head_verbatim(self):
        # The row carries the source's insert head as literal tokens
        # (`<FF09><12><00>`), placed wherever the English puts the name.
        # etext prices FF09's two parameter bytes as arguments, so the
        # encoded message keeps the binary's exact head bytes mid-sentence.
        head = self.data[0x35DC8:0x35DC8 + 4]
        b = scriptmsg._assemble("The <FF09><12><00>'s effect has worn "
                                "off.<FF02><FF01>")
        self.assertEqual(b[:4], etext.encode('The ', end=b''))
        self.assertIn(head, b)
        self.assertEqual(scriptmsg.head_ids(
            "The <FF09><12><00>'s effect."), [(0x09, 0x12)])
        self.assertEqual(scriptmsg.head_ids('x<FF0A><73>y.'), [(0x0A, 0x73)])

    def test_wrong_parameter_count_is_refused(self):
        with self.assertRaises(SystemExit):
            scriptmsg.head_ids('x<FF09><12>y.')       # FF09 takes two bytes
        with self.assertRaises(SystemExit):
            scriptmsg.head_ids('x<FF0A><73><00>y.')   # FF0A takes one

    def test_dng_cave_is_the_declared_extension_window(self):
        base, size = scriptmsg._cave('DNG', self.data)
        self.assertEqual(base, toolbelt.asm_equ('DNG_SCRIPTMSG_ADDR') - scriptmsg.B)
        self.assertEqual(size, (toolbelt.asm_equ('DNG_SCRIPTMSG_LIMIT')
                                - toolbelt.asm_equ('DNG_SCRIPTMSG_ADDR')))
        self.assertGreater(base, len(self.data))   # past the retail image


if __name__ == '__main__':
    unittest.main()
