'''Talk to the MCP server the way a client does: real stdio, real JSON-RPC.

Why this exists: the tool bodies are unit tested, but nothing proved the
server itself answers over the wire. t21 rewired the COM channel through a
broker thread; that is exactly the kind of change that can leave the process
alive and mute.

Run:  python test/test_mcp_wire.py
'''
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def talk(requests, timeout=90):
    process = subprocess.Popen(
        [sys.executable, str(ROOT / 'bin' / 'mcp.py')],
        cwd=str(ROOT),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
    )
    answers = []
    try:
        for request in requests:
            # A str goes on the wire untouched, so the junk phase can send
            # bytes that are not JSON at all.
            line = request if isinstance(request, str) else json.dumps(request)
            process.stdin.write(line + '\n')
            process.stdin.flush()
        process.stdin.close()
        deadline = time.time() + timeout
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                answers.append(json.loads(line))
            except json.JSONDecodeError:
                answers.append({'unparseable': line[:120]})
            if time.time() > deadline:
                break
    finally:
        process.kill()
    return answers


def _body(answer):
    '''The text of one tools/call answer, or '' when it was an error.'''
    result = (answer or {}).get('result') or {}
    return ''.join(part.get('text', '') for part in (result.get('content') or []))


def main():
    failures = 0

    def check(name, ok, detail=''):
        nonlocal failures
        print(('  PASS ' if ok else '  FAIL ') + name + ('' if ok else ' -- ' + str(detail)[:200]))
        if not ok:
            failures += 1

    answers = talk([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
         'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                    'clientInfo': {'name': 'wire-probe', 'version': '0'}}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
         'params': {'name': 'chem_identity',
                    'arguments': {'smiles': 'c1ccccc1O'}}},
    ])

    check('the server answered at all', bool(answers), answers)
    by_id = {a.get('id'): a for a in answers if isinstance(a, dict)}

    init = by_id.get(1, {})
    check('initialize returns a result', 'result' in init, init)
    check('it names the protocol version', bool(init.get('result', {}).get('protocolVersion')), init)

    catalog = by_id.get(2, {}).get('result', {})
    tools = catalog.get('tools', [])
    # 16 since kingdraw_close landed: the CLI grew the command first and the
    # agent surfaces did not follow, which left the advice 'close that window
    # and open again' with no tool behind it.
    check('tools/list returns 16 tools', len(tools) == 16, len(tools))
    check('every tool has a name and a schema',
          all(t.get('name') and t.get('inputSchema') for t in tools))

    call = by_id.get(3, {})
    result = call.get('result', {})
    check('tools/call returns content', bool(result.get('content')), call)
    body = ''
    for part in result.get('content', []):
        body += part.get('text', '')
    check('the identity answer is JSON', body.strip().startswith('{'), body[:120])
    check('the InChIKey is in the answer', 'ISWSIDIOOBJBQZ-UHFFFAOYSA-N' in body, body[:200])

    # -- the same server, fed what a client should never send --------------
    # A real client sends notifications (no answer allowed), mistypes a tool
    # name, forgets a required argument, and occasionally says something that
    # is not JSON. None of that may kill the loop or leak a traceback.
    answers = talk([
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        # A request body with no id is a notification too, whatever the method
        # says. This one used to come back with "id": null.
        {'jsonrpc': '2.0', 'method': 'tools/call',
         'params': {'name': 'chem_identity', 'arguments': {'smiles': 'CCO'}}},
        'this is not json',
        {'jsonrpc': '2.0', 'id': 20, 'method': 'nosuch/method'},
        {'jsonrpc': '2.0', 'id': 21, 'method': 'tools/call',
         'params': {'name': 'no_such_tool', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 22, 'method': 'tools/call',
         'params': {'name': 'chem_identity', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 23, 'method': 'tools/call',
         'params': {'name': 'chem_identity', 'arguments': {'smiles': 'C' * 50000}}},
        {'jsonrpc': '2.0', 'id': 24, 'method': 'tools/call',
         'params': {'name': 'chem_identity', 'arguments': {'smiles': 'c1ccccc1O'}}},
    ], timeout=240)
    junk = {a.get('id'): a for a in answers if isinstance(a, dict)}
    # 8 inputs, 6 answers: neither notification may be answered.
    check('neither notification is answered (8 in, 6 out)',
          len(answers) == 6, [a.get('id') for a in answers])
    # The one legitimate null id is the parse error: JSON-RPC answers an
    # unparseable line with id null because there is no id to echo. Anything
    # else with a null id would be the server replying to a notification.
    null_ids = [a for a in answers if isinstance(a, dict) and a.get('id') is None]
    check('the only null-id answer is the parse error',
          len(null_ids) == 1
          and null_ids[0].get('error', {}).get('code') == -32700, null_ids)
    check('a line that is not JSON is a -32700 parse error',
          any(a.get('error', {}).get('code') == -32700
              for a in answers if isinstance(a, dict)), answers)
    check('an unknown method is -32601',
          junk.get(20, {}).get('error', {}).get('code') == -32601, junk.get(20))
    unknown_tool = _body(junk.get(21))
    check('an unknown tool is an error result, not a crash',
          junk.get(21, {}).get('result', {}).get('isError') is True
          and 'unknown tool' in unknown_tool, unknown_tool[:160])
    missing = _body(junk.get(22))
    check('a missing argument names the argument',
          "missing required argument 'smiles'" in missing, missing[:200])
    # The answer used to be {'message': 'tool raised', 'detail': <traceback
    # sliced mid-word>}, which named neither the argument nor the schema.
    check('a missing argument is not a traceback',
          'Traceback' not in missing and 'tool raised' not in missing,
          missing[:200])
    check('a 50 KB argument does not kill the loop', 23 in junk,
          [a.get('id') for a in answers])
    after = _body(junk.get(24))
    check('a normal call still works after all that',
          'ISWSIDIOOBJBQZ-UHFFFAOYSA-N' in after, after[:200])

    print('')
    if failures:
        print('%d FAILED' % failures)
        return 1
    print('all wire checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())