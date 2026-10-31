"""Wire test for the v2 task MCP surface (bin/mcp.py --surface tasks)."""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def session(lines, timeout=180):
    '''Feed newline-delimited JSON, return the parsed responses.'''
    command = [PY, os.path.join(ROOT, 'bin', 'mcp.py'), '--surface', 'tasks']
    payload = '\n'.join(json.dumps(line) for line in lines) + '\n'
    completed = subprocess.run(command, input=payload, capture_output=True,
                               text=True, encoding='utf-8', errors='replace',
                               timeout=timeout, cwd=ROOT)
    out = []
    for line in (completed.stdout or '').splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out, completed


def call(name, arguments):
    responses, completed = session([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
         'params': {'name': name, 'arguments': arguments}},
    ])
    assert len(responses) == 2, (responses, completed.stderr[-400:])
    return responses[1]['result']


class Handshake(unittest.TestCase):
    def test_initialize_and_list(self):
        responses, completed = session([
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        ])
        self.assertEqual(len(responses), 2, completed.stderr[-400:])
        self.assertEqual(responses[0]['result']['serverInfo']['name'],
                         'chem-draw-tool-tasks')
        tools = responses[1]['result']['tools']
        self.assertEqual(len(tools), 15)
        names = {tool['name'] for tool in tools}
        for wanted in ('chem_status', 'chem_draw', 'chem_batch', 'chem_reaction',
                       'chem_resolve', 'chem_ocr', 'chem_grade',
                       'chem_variants', 'chem_close'):
            self.assertIn(wanted, names)
        for tool in tools:
            self.assertIn('inputSchema', tool)

    def test_notification_gets_no_answer(self):
        responses, _ = session([
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        ])
        self.assertEqual(responses, [])


class Tools(unittest.TestCase):
    def test_check_returns_an_envelope(self):
        result = call('chem_check', {'source': 'CCO'})
        self.assertFalse(result['isError'])
        payload = json.loads(result['content'][0]['text'])
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['summary']['formula'], 'C2H6O')

    def test_resolve_offline_hits_the_local_table(self):
        result = call('chem_resolve', {'query': '咖啡因', 'offline': True})
        payload = json.loads(result['content'][0]['text'])
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['identity']['inchikey'],
                         'RYYVLZVUVIJVGH-UHFFFAOYSA-N')

    def test_unknown_tool_is_an_error_not_a_crash(self):
        result = call('chem_nonexistent', {})
        self.assertTrue(result['isError'])
        payload = json.loads(result['content'][0]['text'])
        self.assertFalse(payload['ok'])
        self.assertIn('unknown tool', payload['failure']['message'])

    def test_missing_argument_names_the_problem(self):
        result = call('chem_draw', {})
        payload = json.loads(result['content'][0]['text'])
        self.assertFalse(payload['ok'])
        self.assertIn('missing argument', payload['failure']['message'])


if __name__ == '__main__':
    unittest.main(verbosity=2)