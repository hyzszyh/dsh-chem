"""Unit tests for the v2 task surface that need no running application."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.v2 import geometry, route, tasks  # noqa: E402

PAGE = ('<CDXML><page><fragment>'
        '<n id="2" p="10 10"/><n id="3" p="24 10"/><n id="4" p="24 24"/>'
        '<b id="5" B="2" E="3"/><b id="6" B="3" E="4"/>'
        '</fragment></page></CDXML>')


class Geometry(unittest.TestCase):
    def test_parses_atoms_and_bonds(self):
        shape = geometry.parse_cdxml(PAGE)
        self.assertEqual(len(shape['atoms']), 3)
        self.assertEqual(len(shape['bonds']), 2)

    def test_bond_lengths_ignore_unknown_atoms(self):
        shape = {'atoms': {'2': (0.0, 0.0), '3': (10.0, 0.0)},
                 'bonds': [('2', '3'), ('3', '9')]}
        self.assertEqual(geometry.bond_lengths(shape), [10.0])

    def test_measure_reports_pixels(self):
        stats = geometry.measure(geometry.parse_cdxml(PAGE), 85.0, 300)
        self.assertGreater(stats['median_px'], 0)
        self.assertEqual(stats['bonds'], 2)

    def test_suggest_width_widens_a_crowded_page(self):
        # Two 2-pt bonds spread over 400 pt: at 20 mm the median bond is ~1 px.
        crowded = {'atoms': {'1': (0.0, 0.0), '2': (2.0, 0.0),
                             '3': (4.0, 0.0), '4': (400.0, 0.0)},
                   'bonds': [('1', '2'), ('2', '3')]}
        wide = geometry.suggest_width(crowded, 20.0, 300)
        self.assertGreater(wide, 20.0)
        self.assertLessEqual(wide, geometry.MAX_WIDTH_MM)

    def test_suggest_width_keeps_a_readable_page(self):
        self.assertEqual(
            geometry.suggest_width(geometry.parse_cdxml(PAGE), 200.0, 300),
            200.0)

    def test_tier_boundaries(self):
        self.assertEqual(geometry.tier(50)['name'], 'small')
        self.assertEqual(geometry.tier(150)['name'], 'medium')
        self.assertEqual(geometry.tier(500)['name'], 'large')
        self.assertEqual(geometry.tier(1290)['name'], 'natural-product')


class Sources(unittest.TestCase):
    def test_smiles(self):
        kind, mol = tasks._read_source('c1ccccc1O')
        self.assertEqual(kind, 'smiles')
        self.assertEqual(mol.GetNumAtoms(), 7)

    def test_inchi(self):
        kind, mol = tasks._read_source(
            'InChI=1S/H2O/h1H2')
        self.assertEqual(kind, 'inchi')
        self.assertIsNotNone(mol)

    def test_molblock(self):
        from rdkit import Chem
        block = Chem.MolToMolBlock(Chem.MolFromSmiles('CC'))
        kind, mol = tasks._read_source(block)
        self.assertEqual(kind, 'molblock')
        self.assertEqual(mol.GetNumAtoms(), 2)

    def test_name_is_reported_as_unsupported_for_now(self):
        kind, mol = tasks._read_source('aspirin')
        self.assertEqual(kind, 'unknown')
        self.assertIsNone(mol)


class Routes(unittest.TestCase):
    def test_capability_table_lists_every_route(self):
        for name in route.ROUTES:
            self.assertIn(name, route.TASKS['status'])

    def test_pick_prefers_the_first_available(self):
        self.assertEqual(route.pick('draw', {route.CHEMDRAW: True,
                                           route.KINGDRAW: False}),
                         route.CHEMDRAW)
        self.assertEqual(route.pick('convert', {route.CHEMDRAW: True,
                                                route.KINGDRAW: True}),
                         route.KINGDRAW)

    def test_pick_returns_empty_when_nothing_is_available(self):
        self.assertEqual(route.pick('draw', {route.CHEMDRAW: False,
                                          route.KINGDRAW: False}), '')


class StatusShape(unittest.TestCase):
    def test_status_reports_routes_and_picks(self):
        result = tasks.status()
        data = result['data']
        self.assertIn('routes', data)
        self.assertIn('picked', data)
        self.assertEqual(set(data['routes']), set(route.ROUTES))
        self.assertIn('session', data)
        for key in ('ok', 'channel', 'data', 'failure', 'degraded',
                    'degrade_reason', 'evidence', 'evidence_note',
                    'elapsed_ms', 'warnings'):
            self.assertIn(key, result)


class FigurePresets(unittest.TestCase):
    def test_known_presets_have_physical_widths(self):
        from chemdraw_tool.v2 import figure
        row = figure.preset('cn-1col')
        self.assertEqual(row['width_mm'], 80.0)
        self.assertEqual(row['dpi'], 600)
        self.assertEqual(figure.preset('nature-2col')['width_mm'], 183.0)

    def test_unknown_preset_names_the_alternatives(self):
        from chemdraw_tool.v2 import figure
        with self.assertRaises(KeyError) as caught:
            figure.preset('nope')
        self.assertIn('cn-1col', str(caught.exception))

    def test_resolve_says_when_the_preset_is_too_narrow(self):
        from chemdraw_tool.v2 import figure
        row = figure.resolve(figure.preset('cn-1col'),
                             {'readable': False, 'median_px': 3.0}, 160.0)
        self.assertFalse(row['readable_at_preset'])
        self.assertIn('160', row['advice'])


class Properties(unittest.TestCase):
    def test_describe_matches_known_values(self):
        from rdkit import Chem
        from chemdraw_tool.v2 import props
        row = props.describe(Chem.MolFromSmiles('CCO'), 'ethanol')
        self.assertEqual(row['formula'], 'C2H6O')
        self.assertEqual(row['inchikey'], 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N')
        self.assertEqual(row['hbd'], 1)
        self.assertAlmostEqual(row['tpsa'], 20.23, places=2)

    def test_markdown_table_keeps_every_column(self):
        from rdkit import Chem
        from chemdraw_tool.v2 import props
        rows = [props.describe(Chem.MolFromSmiles('CCO'))]
        table = props.to_markdown(rows)
        self.assertIn('InChIKey', table)
        self.assertIn('LFQSCWFLJHTTHZ', table)
        self.assertEqual(len(table.splitlines()), 3)


class ConvertAndAnalyze(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix='v2-')

    def test_convert_writes_a_readable_sdf(self):
        result = tasks.convert('CCO', to='sdf', out_dir=self.tmp)
        self.assertTrue(result['ok'], result.get('failure'))
        path = result['data']['path']
        self.assertTrue(os.path.exists(path))
        from rdkit import Chem
        supplier = Chem.SDMolSupplier(path)
        mols = [m for m in supplier if m is not None]
        self.assertEqual(len(mols), 1)
        self.assertEqual(Chem.MolToInchiKey(mols[0]),
                         'LFQSCWFLJHTTHZ-UHFFFAOYSA-N')

    def test_convert_rejects_an_unknown_target(self):
        result = tasks.convert('CCO', to='docx', out_dir=self.tmp)
        self.assertFalse(result['ok'])
        self.assertEqual(result['failure']['code'], 'E08')

    def test_analyze_writes_csv_and_markdown(self):
        result = tasks.analyze(['CCO', 'c1ccccc1O'], out_dir=self.tmp)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['data']['rows']), 2)
        self.assertTrue(os.path.exists(result['data']['csv']))
        self.assertIn('| 1 |', result['data']['markdown'])

    def test_analyze_reports_bad_input_per_item(self):
        result = tasks.analyze(['CCO', 'aspirin'], out_dir=self.tmp)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['data']['failed']), 1)


class Checks(unittest.TestCase):
    def test_clean_structure_has_no_errors(self):
        from rdkit import Chem
        from chemdraw_tool.v2 import checks
        report = checks.inspect(Chem.MolFromSmiles('CCO'))
        self.assertTrue(report['ok'])
        self.assertEqual(report['summary']['errors'], 0)

    def test_unassigned_stereocentre_is_flagged(self):
        from rdkit import Chem
        from chemdraw_tool.v2 import checks
        report = checks.inspect(Chem.MolFromSmiles('CC(Cl)Br'))
        codes = [row['code'] for row in report['issues']]
        self.assertIn('stereo-unassigned', codes)

    def test_salt_is_reported_as_disconnected(self):
        from rdkit import Chem
        from chemdraw_tool.v2 import checks
        report = checks.inspect(Chem.MolFromSmiles('CC(=O)[O-].[Na+]'))
        self.assertEqual(report['summary']['fragments'], 2)
        self.assertEqual(report['summary']['charge'], 0)

    def test_overlapping_atoms_are_found(self):
        from chemdraw_tool.v2 import checks
        page = {'atoms': {'1': (0.0, 0.0), '2': (10.0, 0.0), '3': (10.1, 0.05)},
                'bonds': [('1', '2')]}
        clashes = checks.overlaps(page)
        self.assertEqual(len(clashes), 1)
        self.assertEqual({clashes[0]['a'], clashes[0]['b']}, {'2', '3'})


class Stoichiometry(unittest.TestCase):
    def test_esterification_table(self):
        from chemdraw_tool.v2 import stoich
        table = stoich.table('CC(=O)O.OCC>>CC(=O)OCC.O', scale_mmol=10,
                             yield_percent=85)
        self.assertEqual(len(table['rows']), 4)
        acid = table['rows'][0]
        self.assertEqual(acid['formula'], 'C2H4O2')
        self.assertAlmostEqual(acid['mass_mg'], 600.52, places=1)
        product = [r for r in table['rows'] if r['role'] == 'product'][0]
        self.assertAlmostEqual(product['mass_at_yield_mg'],
                               product['mass_mg'] * 0.85, places=1)

    def test_malformed_reaction_is_rejected(self):
        from chemdraw_tool.v2 import stoich
        with self.assertRaises(ValueError):
            stoich.table('CCO')


class ThreeD(unittest.TestCase):
    def test_ethanol_embeds_with_hydrogens(self):
        from chemdraw_tool.v2 import geom3d
        built = geom3d.embed('CCO')
        self.assertEqual(built['atoms_with_h'], 9)
        self.assertIn('ETKDGv3', built['method'])
        xyz = geom3d.to_xyz(built['mol'])
        self.assertEqual(len(xyz.strip().splitlines()), 11)

    def test_bad_smiles_raises(self):
        from chemdraw_tool.v2 import geom3d
        with self.assertRaises(ValueError):
            geom3d.embed('C1CC')


class Resolve(unittest.TestCase):
    def test_chinese_trivial_name(self):
        result = tasks.resolve_name('阿司匹林', allow_network=False)
        self.assertTrue(result['ok'], result.get('failure'))
        self.assertEqual(result['data']['source'], 'local-names')
        self.assertEqual(result['data']['identity']['inchikey'],
                         'BSYNRYMUTXBXSQ-UHFFFAOYSA-N')

    def test_cas_number(self):
        result = tasks.resolve_name('64-17-5', allow_network=False)
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['identity']['formula'], 'C2H6O')

    def test_unknown_name_offline_says_so(self):
        result = tasks.resolve_name('some-unheard-of-compound',
                                    allow_network=False)
        self.assertFalse(result['ok'])
        self.assertIn('offline',
                      (result['failure']['message'] or '').lower())


class OcrVoting(unittest.TestCase):
    def test_two_readers_agreeing_raise_confidence(self):
        from chemdraw_tool.v2 import ocr
        result = ocr.vote([{'smiles': 'CCO', 'source': 'decimer'},
                           {'smiles': 'OCC', 'source': 'llm'}])
        self.assertEqual(result['best']['votes'], 2)
        self.assertEqual(result['best']['confidence'], 'high')
        self.assertFalse(result['needs_confirmation'])

    def test_single_reader_needs_confirmation(self):
        from chemdraw_tool.v2 import ocr
        result = ocr.vote([{'smiles': 'CCO', 'source': 'llm'}])
        self.assertTrue(result['needs_confirmation'])
        self.assertEqual(result['best']['confidence'], 'medium')

    def test_invalid_proposal_is_rejected_not_guessed(self):
        from chemdraw_tool.v2 import ocr
        result = ocr.vote([{'smiles': 'C1CC', 'source': 'decimer'},
                           {'smiles': 'CCO', 'source': 'llm'}])
        self.assertEqual(len(result['rejected']), 1)
        self.assertEqual(result['best']['smiles'], 'CCO')

    def test_read_image_uses_injected_engine_and_hint(self):
        import tempfile
        from chemdraw_tool.v2 import ocr
        folder = tempfile.mkdtemp(prefix='ocr-')
        result = ocr.read_image('', llm_hint='CCO', engines=['decimer'],
                                runners={'decimer': lambda path: ['OCC']},
                                available={'decimer': True}, out_dir=folder)
        self.assertEqual(result['best']['votes'], 2)
        self.assertFalse(result['needs_confirmation'])

    def test_missing_engine_is_reported_not_hidden(self):
        import tempfile
        from chemdraw_tool.v2 import ocr
        folder = tempfile.mkdtemp(prefix='ocr-')
        result = ocr.read_image('', llm_hint='CCO', engines=['osra'],
                                runners={}, available={'osra': False},
                                out_dir=folder)
        self.assertTrue(any('osra' in note for note in result['notes']))
        self.assertEqual(result['best']['votes'], 1)


class OcrEngines(unittest.TestCase):
    '''The reader registry: a verdict must carry the reason with it.'''

    def test_every_engine_reports_availability_and_reason(self):
        from chemdraw_tool.v2 import ocr
        reports = ocr.engine_reports()
        self.assertTrue(reports)
        for name, row in reports.items():
            self.assertIn('available', row, name)
            self.assertIn('reason', row, name)
            if not row['available']:
                self.assertTrue(row.get('needs'), name)

    def test_molblock_with_blank_title_line_still_parses(self):
        # MolVec writes an empty first line; trimming it shifted the counts line
        # up by one and RDKit read the header as atoms. This is that regression.
        from rdkit import Chem
        from chemdraw_tool.v2 import ocr
        block = Chem.MolToMolBlock(Chem.MolFromSmiles('CCO'))
        lines = block.split('\n')
        lines[0] = ''
        blank_titled = '\n'.join(lines)
        self.assertEqual(ocr._mol_from_text(blank_titled, '.mol'), ['CCO'])

    def test_smiles_text_is_read_as_smiles(self):
        from chemdraw_tool.v2 import ocr
        self.assertEqual(ocr._mol_from_text('OCC', '.smi'), ['CCO'])

    def test_a_split_vote_names_the_reader_that_disagreed(self):
        # Two readers agree, one reads a different bond order. The envelope has
        # to say which one split, or the agent cannot tell a wrong reading from a
        # low-confidence one.
        from chemdraw_tool.v2 import ocr
        result = ocr.vote([
            {'smiles': 'CC(=O)Oc1ccccc1C(=O)O', 'source': 'molvec'},
            {'smiles': 'CC(=O)Oc1ccccc1C(=O)O', 'source': 'decimer'},
            {'smiles': 'CC(=O)Oc1ccccc1C(=O)', 'source': 'stray'}])
        self.assertEqual(result['best']['votes'], 2)
        self.assertEqual([row['source'] for row in result['differing']],
                         ['stray'])
        by_source = {row['source']: row for row in result['readers']}
        self.assertTrue(by_source['molvec']['agrees'])
        self.assertFalse(by_source['stray']['agrees'])
        self.assertNotEqual(by_source['stray']['smiles'],
                            by_source['molvec']['smiles'])

    def test_an_unreadable_reading_is_listed_not_hidden(self):
        from chemdraw_tool.v2 import ocr
        result = ocr.vote([{'smiles': 'not a structure', 'source': 'osra'}])
        self.assertIsNone(result['best'])
        self.assertEqual(result['readers'][0]['source'], 'osra')
        self.assertIsNone(result['readers'][0]['agrees'])
        self.assertIn('RDKit', result['readers'][0]['why'])

class Grading(unittest.TestCase):
    def setUp(self):
        self.answer = 'CC(=O)Oc1ccccc1C(=O)O'

    def test_identical_structure_is_correct(self):
        from chemdraw_tool.v2 import grade
        report = grade.grade(self.answer, [self.answer])
        self.assertEqual(report['rows'][0]['verdict'], 'correct')

    def test_wrong_formula_is_explained(self):
        from chemdraw_tool.v2 import grade
        report = grade.grade(self.answer, ['OC(=O)c1ccccc1'])
        row = report['rows'][0]
        self.assertEqual(row['verdict'], 'different')
        self.assertTrue(any('formula' in line for line in row['differences']))

    def test_wrong_stereochemistry_is_its_own_verdict(self):
        from chemdraw_tool.v2 import grade
        report = grade.grade('C[C@H](N)C(=O)O', ['C[C@@H](N)C(=O)O'])
        self.assertEqual(report['rows'][0]['verdict'], 'stereo')

    def test_unreadable_submission_is_counted(self):
        from chemdraw_tool.v2 import grade
        report = grade.grade(self.answer, ['C1CC'])
        self.assertEqual(report['counts'].get('unreadable'), 1)


class QuestionVariants(unittest.TestCase):
    def test_benzene_scaffold_expands(self):
        from chemdraw_tool.v2 import variants
        report = variants.expand('c1ccc([*])cc1', ['C(=O)O', 'O', 'N'])
        self.assertEqual(len(report['variants']), 3)
        smiles = {row['smiles'] for row in report['variants']}
        self.assertIn('O=C(O)c1ccccc1', smiles)

    def test_duplicate_substituents_are_merged(self):
        from chemdraw_tool.v2 import variants
        report = variants.expand('c1ccc([*])cc1', ['O', '[OH]'])
        self.assertEqual(report['duplicates'], 1)
        self.assertEqual(len(report['variants']), 1)

    def test_bad_scaffold_raises(self):
        from chemdraw_tool.v2 import variants
        with self.assertRaises(ValueError):
            variants.expand('C1CC', ['O'])


class RouteIsolation(unittest.TestCase):
    '''Two vendors must stay two: separate locks, separate route tables.'''

    def test_the_two_routes_have_separate_locks(self):
        from chemdraw_tool import applock
        self.assertNotEqual(applock.CHEMDRAW, applock.KINGDRAW)

    def test_every_task_lists_routes_that_exist(self):
        from chemdraw_tool.v2 import route
        for task, order in route.TASKS.items():
            self.assertTrue(order, task)
            for name in order:
                self.assertIn(name, route.ROUTES, (task, name))

    def test_both_vendors_are_preferred_somewhere(self):
        from chemdraw_tool.v2 import route
        preferred = {order[0] for order in route.TASKS.values()}
        self.assertEqual(preferred, {route.CHEMDRAW, route.KINGDRAW})

class ReactionScheme(unittest.TestCase):
    '''Mapping and the RXN block, none of which needs a vendor program.'''

    def test_split_needs_two_sides(self):
        from chemdraw_tool.v2 import reaction
        with self.assertRaises(ValueError):
            reaction.split('CCO')
        with self.assertRaises(ValueError):
            reaction.split('>>CC')

    def test_esterification_maps_what_can_be_proven(self):
        from chemdraw_tool.v2 import reaction
        reactants, products = reaction.split('CCO.CC(=O)O>>CC(=O)OCC.O')
        _r, _p, rows = reaction.map_atoms(reactants, products)
        self.assertEqual(len(rows), 7)
        kinds = {}
        for row in rows:
            kinds[row['match']] = kinds.get(row['match'], 0) + 1
        self.assertEqual(kinds.get('exact'), 5)
        numbered = [row['map'] for row in rows if row['map']]
        self.assertEqual(len(numbered), len(set(numbered)), 'duplicate map number')

    def test_rxn_block_has_both_sides_and_maps(self):
        from chemdraw_tool.v2 import reaction
        reactants, products = reaction.split('CCO.CC(=O)O>>CC(=O)OCC.O')
        r_mols, p_mols, rows = reaction.map_atoms(reactants, products)
        block = reaction.rxn_block(r_mols, p_mols, rows)
        self.assertTrue(block.startswith('$RXN'))
        self.assertEqual(block.count('$MOL'), len(reactants) + len(products))
        self.assertIn('  2  2', block.splitlines()[4])

    def test_unparseable_side_is_refused(self):
        from chemdraw_tool.v2 import reaction
        reactants, products = reaction.split('CCO>>not-a-structure')
        with self.assertRaises(ValueError):
            reaction.map_atoms(reactants, products)

class CaptionCompositing(unittest.TestCase):
    '''The figure caption is composited; prove it lands and grows the image.'''

    def test_caption_band_is_added(self):
        import os
        import tempfile
        from PIL import Image
        from chemdraw_tool.v2 import tasks
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'page.png')
            Image.new('RGB', (200, 80), 'white').save(path)
            self.assertTrue(tasks._composite_caption(path, 'H2SO4, 80 C'))
            with Image.open(path) as image:
                self.assertGreater(image.size[1], 80)

    def test_empty_caption_is_refused(self):
        from chemdraw_tool.v2 import tasks
        self.assertFalse(tasks._composite_caption('does-not-exist.png', ''))

if __name__ == '__main__':
    unittest.main(verbosity=2)