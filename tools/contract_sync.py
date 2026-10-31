'''Three-way contract reconciliation: MCP tools / DSH plugin tools / CLI subcommands.

Why this exists
---------------
The same capability is declared in three places. The declarations drifted once
already (the plugin table forgot chem_crosscheck, the MCP count was written as
12 while TOOLS held 14), and more capabilities are coming, so the drift will
keep coming back. Reading three files by eye is not a control; this script is.

Truth source
------------
The Python side is authoritative: core/chemdraw_tool/{cli,mcp_server}.py.
The DSH plugin is a thin shell -- it may expose a subset, and it may rename
parameters to camelCase, but it must not invent capabilities or forward an
argument that the CLI does not accept.

What is compared
----------------
1. names      -- which tools each side has (MCP vs plugin vs the CLI path it targets)
2. parameters -- every parameter must be forwarded to a CLI token that exists
3. required   -- a parameter the tool marks required must land on a required CLI argument

Usage
-----
    python tools/contract_sync.py              # human table, exit 1 on drift
    python tools/contract_sync.py --json       # machine output
    python tools/contract_sync.py --dump       # raw surfaces, for debugging
'''
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'core'))

SENTINEL = re.compile(r'^__SENT_(?P<key>[A-Za-z0-9_]+)__$')


# --------------------------------------------------------------------- surfaces
def _walk_parser(parser):
    '''Walk an argparse tree: path -> {flags, positionals}.'''
    surface = {}

    def walk(parser, prefix):
        for action in parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, sub in action.choices.items():
                path = prefix + (name,)
                flags, positionals = {}, []
                for act in sub._actions:
                    if isinstance(act, argparse._SubParsersAction):
                        continue
                    if act.option_strings:
                        for opt in act.option_strings:
                            flags[opt] = {
                                'dest': act.dest,
                                'required': bool(getattr(act, 'required', False)),
                                'takes_value': act.nargs != 0,
                            }
                    elif act.dest != 'help':
                        positionals.append({'dest': act.dest, 'nargs': act.nargs})
                surface[' '.join(path)] = {'flags': flags, 'positionals': positionals,
                                            'children': []}
                walk(sub, path)

    walk(parser, ())

    # A subparser group is only a group if something sits under it. Derive that
    # from the finished table instead of from argparse internals: the action that
    # owns the choices belongs to the parent, so reading it while walking gives
    # every leaf the parent's children.
    for key in surface:
        prefix = key + ' '
        surface[key]['children'] = sorted({
            other[len(prefix):].split(' ')[0]
            for other in surface
            if other.startswith(prefix) and ' ' not in other[len(prefix):]
        })
    return surface


def cli_surface():
    '''The atomic CLI: one leaf per engine action.'''
    from chemdraw_tool import cli

    return _walk_parser(cli.build_parser())


def v2_surface():
    '''The v2 task CLI (bin/v2.py): one leaf per finished task.'''
    import importlib.util

    path = os.path.join(ROOT, 'bin', 'v2.py')
    spec = importlib.util.spec_from_file_location('chemdraw_v2_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return _walk_parser(module.build_parser())


def mcp_surface():
    '''Import the TOOLS constant -- never regex the source.'''
    from chemdraw_tool import mcp_server

    out = []
    for tool in mcp_server.TOOLS:
        schema = tool.get('inputSchema') or {}
        props = schema.get('properties') or {}
        out.append({
            'name': tool['name'],
            'params': dict(props),
            'required': list(schema.get('required') or []),
        })
    return out


def plugin_surface(node='node'):
    '''Run tools/plugin_contract.mjs, which stubs the SDK and records argv.'''
    script = os.path.join(ROOT, 'tools', 'plugin_contract.mjs')
    proc = subprocess.run(
        [node, script, ROOT], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError('plugin harvester failed: ' + (proc.stderr or '')[-800:])
    return json.loads(proc.stdout)


# ------------------------------------------------------------------- resolution
def resolve_path(surface, argv):
    '''Longest leading run of tokens that names a real CLI subcommand path.'''
    best = ()
    tokens = [t for t in argv]
    for i in range(1, len(tokens) + 1):
        candidate = tuple(tokens[:i])
        if ' '.join(candidate) in surface:
            best = candidate
    return best, tokens[len(best):]


def split_args(rest):
    '''Rest -> (flags {name: value|None}, positionals [value]).'''
    flags, positionals = {}, []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith('-'):
            value = None
            if i + 1 < len(rest) and not rest[i + 1].startswith('-'):
                value = rest[i + 1]
                i += 1
            flags[token] = value
        else:
            positionals.append(token)
        i += 1
    return flags, positionals


def positional_room(entry):
    '''How many positional arguments the parser accepts: (min, max|None).'''
    low = high = 0
    for pos in entry['positionals']:
        nargs = pos['nargs']
        if nargs == '?':
            high += 1
        elif nargs in ('*', '+'):
            return (low + (1 if nargs == '+' else 0), None)
        elif isinstance(nargs, int):
            low += nargs
            high += nargs
        elif nargs is None:
            low += 1
            high += 1
        else:  # REMAINDER and friends: unbounded
            return (low, None)
    return (low, high)


def check_plugin_call(surface, tool, call):
    findings = []
    path, rest = resolve_path(surface, call['argv'])
    if not path:
        findings.append({
            'kind': 'path', 'side': 'plugin', 'tool': tool,
            'detail': 'no CLI subcommand matches argv ' + json.dumps(call['argv'], ensure_ascii=False),
            'truth': 'cli.py',
        })
        return findings, None
    key = ' '.join(path)
    entry = surface[key]
    if entry.get('children') and rest and not rest[0].startswith('-'):
        findings.append({
            'kind': 'path', 'side': 'plugin', 'tool': tool,
            'detail': '%s is a group; %r is not one of its subcommands (%s)'
                      % (key, rest[0], ', '.join(entry['children'])),
            'truth': 'cli.py',
        })
        return findings, key
    flags, positionals = split_args(rest)

    for flag, value in flags.items():
        if flag not in entry['flags']:
            findings.append({
                'kind': 'flag', 'side': 'plugin', 'tool': tool,
                'detail': key + ' does not accept ' + flag,
                'truth': 'cli.py',
            })
        elif entry['flags'][flag]['takes_value'] and value is None:
            findings.append({
                'kind': 'flag', 'side': 'plugin', 'tool': tool,
                'detail': key + ' ' + flag + ' needs a value',
                'truth': 'cli.py',
            })

    required = [f for f, meta in entry['flags'].items()
                if meta['required'] and f.startswith('--')]
    for flag in required:
        if flag not in flags:
            findings.append({
                'kind': 'required', 'side': 'plugin', 'tool': tool,
                'detail': key + ' requires ' + flag + ' but the plugin never passes it',
                'truth': 'cli.py',
            })

    low, high = positional_room(entry)
    got = len(positionals)
    if got < low:
        findings.append({
            'kind': 'positional', 'side': 'plugin', 'tool': tool,
            'detail': '%s needs %d positional argument(s), the plugin passes %d'
                      % (key, low, got),
            'truth': 'cli.py',
        })
    if high is not None and got > high:
        findings.append({
            'kind': 'positional', 'side': 'plugin', 'tool': tool,
            'detail': '%s takes at most %d positional argument(s), the plugin passes %d'
                      % (key, high, got),
            'truth': 'cli.py',
        })
    return findings, key


def param_covered(param, paths, cli):
    """Is this parameter name reachable on any CLI path the tool uses?"""
    snake = re.sub(r'(?<!^)(?=[A-Z])', '_', param).lower()
    kebab = '--' + snake.replace('_', '-')
    for path in paths:
        entry = cli.get(path)
        if not entry:
            continue
        if kebab in entry['flags']:
            return True
        if snake in {meta['dest'] for meta in entry['flags'].values()}:
            return True
        if snake in {pos['dest'] for pos in entry['positionals']}:
            return True
    return False


def plugin_param_targets(call):
    '''param name -> the CLI token it lands on (flag name, or "positional:N").'''
    path_rest = call['argv']
    flags, positionals = split_args(path_rest)
    mapping = {}
    for flag, value in flags.items():
        match = SENTINEL.match(value or '')
        if match:
            mapping[match.group('key')] = flag
    index = 0
    for token in positionals:
        match = SENTINEL.match(token)
        if match:
            mapping[match.group('key')] = 'positional:%d' % index
        index += 1
    return mapping


# ------------------------------------------------------------------- comparison
def compare(surfaces, mapping):
    mcp = {t['name']: t for t in surfaces['mcp']}
    plugin = {t['name']: t for t in surfaces['plugin']}
    cli = surfaces['cli']
    findings = []

    # 1. names: every MCP tool must be reachable from the CLI (Python side is the truth)
    for name, tool in sorted(mcp.items()):
        if name not in mapping:
            findings.append({
                'kind': 'unmapped', 'side': 'mcp', 'tool': name,
                'detail': 'no CLI path declared for this MCP tool',
                'truth': 'cli.py',
            })
            continue
        path, _params = mapping[name]
        if path not in cli:
            findings.append({
                'kind': 'path', 'side': 'mcp', 'tool': name,
                'detail': 'declared CLI path does not exist: ' + path,
                'truth': 'cli.py',
            })

    for name in sorted(set(mapping) - set(mcp)):
        findings.append({
            'kind': 'unmapped', 'side': 'mcp', 'tool': name,
            'detail': 'declared in the mapping but TOOLS has no such tool',
            'truth': 'mcp_server.py',
        })

    # 2. plugin tools: every forwarded argv must land on a real CLI subcommand
    plugin_paths = {}
    plugin_truth = {}
    for name, tool in sorted(plugin.items()):
        if not tool['calls']:
            findings.append({
                'kind': 'call', 'side': 'plugin', 'tool': name,
                'detail': 'the tool never calls the CLI (no argv recorded)',
                'truth': 'cli.py',
            })
            continue
        # A tool wraps either the atomic CLI or the task CLI, never both: the
        # argv the harvester recorded says which one, so each call is checked
        # against its own argparse tree instead of being called drift.
        v2 = surfaces.get('v2')
        surface = v2 if v2 and all(c.get('channel') == 'v2' for c in tool['calls']) \
            else cli
        plugin_truth[name] = surface
        for call in tool['calls']:
            got, path = check_plugin_call(surface, name, call)
            findings.extend(got)
            if path:
                plugin_paths.setdefault(name, set()).add(path)

    # 3. parameters: what the plugin declares must reach a real CLI destination.
    #
    # A parameter can legitimately arrive in three shapes, so a sentinel in argv
    # is not the only proof of life:
    #   * value flag        --route <sentinel>      (sentinel visible in argv)
    #   * boolean flag      --clear                 (no value, so no sentinel)
    #   * materialised file kingdraw_convert stages the molblock into a temp
    #                       file and passes the *path* positionally
    # So a parameter the sentinel pass does not see is still fine when its
    # kebab-case name (or its dest / positional dest) exists on a CLI path the
    # tool actually reaches. A rename on either side breaks this.
    for name, tool in sorted(plugin.items()):
        forwarded = set()
        for call in tool['calls']:
            forwarded.update(plugin_param_targets(call).keys())
        declared = set(tool['params'])
        for missing in sorted(declared - forwarded):
            if param_covered(missing, plugin_paths.get(name, set()),
                             plugin_truth.get(name, cli)):
                continue
            findings.append({
                'kind': 'param', 'side': 'plugin', 'tool': name,
                'detail': 'declares parameter ' + missing + ' but never forwards it to the CLI',
                'truth': 'cli.py',
            })

    # 4. required flags the CLI wants may not be optional in MCP's declared mapping
    for name, tool in sorted(mcp.items()):
        meta = mapping.get(name)
        if not meta:
            continue
        path, params = meta
        entry = cli.get(path)
        if not entry:
            continue
        for param, target in sorted(params.items()):
            if target.startswith('--') and target not in entry['flags']:
                findings.append({
                    'kind': 'mapping', 'side': 'mcp', 'tool': name,
                    'detail': path + ' has no ' + target + ' (parameter ' + param + ')',
                    'truth': 'cli.py',
                })
            elif target.startswith('--') and entry['flags'][target]['required'] \
                    and param not in set(tool['required']):
                findings.append({
                    'kind': 'required', 'side': 'mcp', 'tool': name,
                    'detail': (path + ' requires ' + target + ' but the MCP tool marks '
                               + param + ' optional, so a caller can legally omit it'),
                    'truth': 'cli.py',
                })
            elif target.startswith('positional:') and not entry['positionals']:
                findings.append({
                    'kind': 'mapping', 'side': 'mcp', 'tool': name,
                    'detail': path + ' takes no positional argument (parameter ' + param + ')',
                    'truth': 'cli.py',
                })

    return findings, mcp, plugin, cli, plugin_paths



# --------------------------------------------------------------------- mapping
# MCP tool -> (CLI path, {mcp parameter: CLI token}).
#
# Only the Python side can be derived automatically: MCP handlers call the
# adapters directly, they do not spawn the CLI. So the MCP->CLI correspondence is
# declared here, once, and this table is itself checked: a path or a flag that
# disappears from cli.py makes the check fail instead of silently rotting.
MCP_TO_CLI = {
    'chem_identity': ('identity', {'smiles': 'positional:0'}),
    'kingdraw_smiles_to_mol': ('kd mol', {'smiles': 'positional:0'}),
    'kingdraw_mol_to_smiles': ('kd smiles', {'mol': 'positional:0'}),
    'kingdraw_formula': ('kd formula', {'smiles': '--smiles', 'mol': '--mol'}),
    'kingdraw_read_king': ('kd king', {'path': 'positional:0'}),
    'kingdraw_match': ('kd match', {'a': 'positional:0', 'b': 'positional:1',
                                    'substructure': '--substructure'}),
    'kingdraw_to3d': ('kd to3d', {'smiles': '--smiles', 'mol': '--mol'}),
    'kingdraw_export': ('kd export', {'input': 'positional:0', 'out': '--out',
                                      'min_side': '--min-side', 'keep_kdx': '--keep-kdx',
                                      'timeout': '--timeout'}),
    'kingdraw_close': ('kd close', {'pid': '--pid', 'timeout': '--timeout'}),
    'chemdraw_draw': ('cd draw', {'smiles': 'positional:0', 'route': '--route'}),
    'chemdraw_modify': ('cd modify', {'replace': '--replace', 'clear': '--clear',
                                      'delete_atom': '--delete-atom',
                                      'delete_object': '--delete-object'}),
    'chemdraw_export': ('cd export', {'path': 'positional:0', 'format': '--format',
                                      'resolution': '--resolution', 'width_pt': '--width-pt',
                                      'height_pt': '--height-pt', 'smiles': '--smiles'}),
    'chemdraw_figure': ('cd figure', {'path': 'positional:0', 'width_mm': '--width-mm',
                                      'dpi': '--dpi', 'format': '--format',
                                      'smiles': '--smiles'}),
    'chemdraw_read': ('cd read', {'format': '--format', 'smiles': '--smiles'}),
    'chem_crosscheck': ('crosscheck', {'smiles': 'positional:0', 'compare_to': '--compare-to',
                                       'kingdraw_home': '--kingdraw-home'}),
    'chemdraw_capabilities': ('cd capabilities', {}),
}


def surfaces():
    return {'cli': cli_surface(), 'v2': v2_surface(), 'mcp': mcp_surface(),
            'plugin': plugin_surface()}


def report(findings, mcp, plugin, cli, plugin_paths, stream=sys.stdout):
    print('', file=stream)
    print('  truth source: core/chemdraw_tool/cli.py (argparse tree) + '
          'core/chemdraw_tool/mcp_server.py (TOOLS)', file=stream)
    print('  the plugin in dsh-plugin/lib/index.js is a thin shell: subset or mapping',
          file=stream)
    print('', file=stream)
    print('  side        count  note', file=stream)
    print('  ----------  -----  ---------------------------------------------', file=stream)
    print('  CLI paths   %5d  truth source (build_parser)' % len(cli), file=stream)
    print('  MCP tools   %5d  truth source (TOOLS)' % len(mcp), file=stream)
    print('  plugin      %5d  thin shell: subset or equivalent mapping' % len(plugin),
          file=stream)
    print('', file=stream)

    covered = set()
    for paths in plugin_paths.values():
        covered |= paths
    mcp_paths = {path for path, _params in MCP_TO_CLI.values()}
    unclaimed = sorted(set(cli) - covered - mcp_paths)
    if unclaimed:
        print('  CLI paths no tool reaches (allowed, informational):', file=stream)
        for path in unclaimed:
            print('    - ' + path, file=stream)
        print('', file=stream)

    only_mcp = sorted(set(mcp) - set(plugin))
    only_plugin = sorted(set(plugin) - set(mcp))
    print('  in MCP but not a plugin tool: %s' % (', '.join(only_mcp) or '-'), file=stream)
    print('  in plugin but not an MCP tool: %s' % (', '.join(only_plugin) or '-'), file=stream)
    print('', file=stream)

    if not findings:
        print('  no drift: every forwarded argv lands on a real CLI subcommand', file=stream)
        return 0
    print('  DRIFT: %d finding(s); the Python side (cli.py / mcp_server.py) is the truth'
          % len(findings), file=stream)
    print('', file=stream)
    for item in findings:
        print('  [%s] %s/%s: %s  (truth: %s)'
              % (item['kind'], item['side'], item['tool'], item['detail'], item['truth']),
              file=stream)
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='MCP / plugin / CLI contract reconciliation')
    parser.add_argument('--json', action='store_true', help='machine output')
    parser.add_argument('--dump', action='store_true', help='raw surfaces only')
    args = parser.parse_args(argv)

    data = surfaces()
    if args.dump:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    findings, mcp, plugin, cli, plugin_paths = compare(data, MCP_TO_CLI)
    if args.json:
        print(json.dumps({
            'truth_source': 'core/chemdraw_tool/{cli,mcp_server}.py',
            'counts': {'cli': len(cli), 'mcp': len(mcp), 'plugin': len(plugin)},
            'findings': findings,
            'mcp_only': sorted(set(mcp) - set(plugin)),
            'plugin_only': sorted(set(plugin) - set(mcp)),
        }, indent=2, ensure_ascii=False))
    else:
        return report(findings, mcp, plugin, cli, plugin_paths)
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
