"""Regression cases for the retained hardware-specific DT overlay fix."""
import ast
from pathlib import Path
import os
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
ROM = Path(os.environ.get('ONYX_ROM_ROOT', '/nonexistent')) / 'vendor/lineage/build/tools/merge_dtbs.py'

class OverlayMatch(unittest.TestCase):
    @unittest.skipUnless(ROM.is_file(), 'requires the synced vendor tree')
    def test_same_soc_does_not_override_conflicting_board_or_extra_id(self):
        tree = ast.parse(ROM.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'find_symbol')
        scope = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROM), 'exec'), scope)
        def info(soc, board, extras=None):
            return types.SimpleNamespace(plat_id={soc}, board_id={board}, pmic_id=None, extra_ids=extras or {})
        records = [({'label'}, set(), 'wrong'), ({'label'}, set(), 'right')]
        infos = {'consumer': info(1, 2), 'wrong': info(1, 3), 'right': info(1, 2)}
        self.assertEqual(scope['find_symbol'](records, 'label', infos, 'consumer'), 'right')
        infos['consumer'].extra_ids = {'sku': {1}}
        infos['right'].extra_ids = {'sku': {2}}
        self.assertIsNone(scope['find_symbol'](records, 'label', infos, 'consumer'))

if __name__ == '__main__':
    unittest.main()
