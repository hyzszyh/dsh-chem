'''The PowerShell entry point has to stay readable by PowerShell 5.1.

Why this exists: install.ps1 was saved as BOM-less UTF-8. Windows PowerShell
5.1 -- the one a newcomer gets by typing `powershell` -- reads a .ps1 without
a byte-order mark as ANSI (cp936 here). Every Chinese string decoded to
garbage and the quote pairing collapsed, so the first command in the README
failed without running a line of it:

    At ...\\install.ps1:57 char:32
    + Note 'python' $true ('{0} ({1} ?? ) ...
    Unexpected token '???' in expression or statement.
    Missing closing '}' in statement block or type definition.

With the BOM the same file exits 0 and prints its five-line summary.

Run:  python test/test_install_script.py
'''
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOM = b'\xef\xbb\xbf'


def scripts():
    '''The scripts a user actually runs: the root and scripts/.

    A recursive sweep would also pick up probe scripts dropped into
    test/out during debugging, and those are not shipped.
    '''
    found = []
    for base in (ROOT, ROOT / 'scripts'):
        if base.is_dir():
            found.extend(sorted(base.glob('*.ps1')))
    return found


class InstallScriptTest(unittest.TestCase):

    def test_there_is_at_least_one_script(self):
        self.assertTrue(scripts(), 'expected install.ps1 in the repository root')

    def test_every_script_carries_a_utf8_bom(self):
        for script in scripts():
            with self.subTest(script=script.name):
                self.assertEqual(
                    script.read_bytes()[:3], BOM,
                    script.name + ' has no UTF-8 BOM; PowerShell 5.1 reads it as ANSI '
                    'and the Chinese text becomes a syntax error')

    def test_every_script_body_is_valid_utf8(self):
        for script in scripts():
            with self.subTest(script=script.name):
                body = script.read_bytes()
                if body.startswith(BOM):
                    body = body[3:]
                body.decode('utf-8')

    def test_install_script_sets_console_encoding(self):
        text = (ROOT / 'install.ps1').read_bytes()[3:].decode('utf-8')
        self.assertIn('OutputEncoding', text)
        self.assertTrue('UTF8' in text or 'utf8' in text,
                        'redirected output would fall back to the ANSI codepage')


if __name__ == '__main__':
    failures = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if failures.wasSuccessful() else 1)