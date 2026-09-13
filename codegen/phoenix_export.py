"""Export a state machine model to the simple Phoenix YAML format.

Port of `convertToPhoenixYaml` from SM-gui (`src/yamlConverter.ts`, Ctrl-E).

Phoenix format — only the top two levels of the state tree are kept:

    TopLevel:              # null if it has no children
      Child:               # null if it has nothing below
        in: [lines]        # entry code, one trimmed line per item
        out: [lines]       # exit code
        next: Target       # single unguarded transition
        next: {guard: Target, ...}   # guarded / multiple ('always' if no guard)

Targets are written as "TopLevel" or "TopLevel Child". Guards are Python
expressions evaluated in order. Transitions into decisions are flattened into
plain `next` entries. Everything else the format cannot express (AND nodes,
deeper states, top-level code, `do` code, ...) is dropped with a warning.
"""

import yaml

from codegen.common import resolve_target_path, resolve_pseudo_ref

# Guard the Phoenix interpreter treats as always true (used for unguarded transitions)
ALWAYS = 'always'


class _PhoenixDumper(yaml.SafeDumper):
    """Matches js-yaml's `dump` layout: sequences indented under their key."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _code_lines(code):
    if not isinstance(code, str) or not code.strip():
        return []
    return [l.strip() for l in code.strip().split('\n') if l.strip()]


def _has_code(code):
    return isinstance(code, str) and bool(code.strip())


def _edges(state_data):
    """Transitions the GUI can draw as edges. Terminations (`to: null`) and
    explicit forks (`[...]`) have no edge in SM-gui, so they are ignored
    silently, exactly as its Ctrl-E export does."""
    return [t for t in ((state_data or {}).get('transitions') or [])
            if isinstance(t, dict) and isinstance(t.get('to'), str) and t['to']
            and '[' not in t['to']]


def _children(state_data):
    return (state_data or {}).get('states') or {}


def _version_gte(ver, min_ver):
    def parse(v):
        try:
            return tuple(int(x) for x in str(v).split('.'))
        except ValueError:
            return (0, 0, 0)
    return parse(ver) >= parse(min_ver)


def _combine_guards(guards):
    """Guards are Python expressions: join with `and`, parenthesised when combined."""
    if len(guards) == 1:
        return guards[0]
    return ' and '.join(f'({g})' for g in guards)


def convert_to_phoenix_yaml(data):
    """Convert a parsed SMB model to Phoenix YAML.

    Transitions into decisions are flattened: each decision rule becomes its own
    `next` entry whose guard is the source guard AND-ed with the rule guards along
    the way, keeping priority order. This matches the generated code, where a
    decision with no matching rule falls through to the source's next transition.

    Returns (yaml_text, warnings).
    """
    warnings = []
    top_states = _children(data)
    hierarchical = _version_gte(data.get('SM-builder-version', ''), '0.6.0')

    # Pseudo-state index in the shape resolve_pseudo_ref expects:
    # (container_path, name) -> {kind, rules, scope}. A pseudo-state's scope (used
    # to resolve its rules' targets) is container + [name].
    pseudo_index = {}

    def walk_pseudo(container, state_data):
        for block, kind in (('decisions', 'decision'), ('ands', 'and')):
            for name, rules in ((state_data or {}).get(block) or {}).items():
                pseudo_index[(tuple(container), name)] = {
                    'kind': kind, 'rules': rules or [], 'scope': container + [name]}
                if kind == 'and':
                    warnings.append(f'AND node "{name}" was skipped')
        for child_name, child in _children(state_data).items():
            walk_pseudo(container + [child_name], child)
    walk_pseudo(['root'], data)

    def is_pseudo_ref(to):
        return ('@' in to) if hierarchical else to.startswith('@')

    def lookup_pseudo(to, scope):
        if hierarchical:
            try:
                return resolve_pseudo_ref(to, scope, pseudo_index)
            except (KeyError, ValueError):
                return None
        # Legacy: decision names are global
        for (_, name), entry in pseudo_index.items():
            if name == to[1:] and entry['kind'] == 'decision':
                return entry['kind'], entry['rules'], entry['scope']
        return None

    # States deeper than 2 levels
    def walk_deep(path, state_data):
        for name, child in _children(state_data).items():
            child_path = path + [name]
            if len(child_path) > 2:
                warnings.append(f'State "{"/".join(child_path)}" is deeper than 2 levels and was skipped')
            walk_deep(child_path, child)
    walk_deep([], data)

    for name, s in top_states.items():
        s = s or {}
        if _has_code(s.get('entry')):
            warnings.append(f'Top-level state "{name}" has entry code that was ignored')
        if _has_code(s.get('exit')):
            warnings.append(f'Top-level state "{name}" has exit code that was ignored')
        if _has_code(s.get('do')):
            warnings.append(f'Top-level state "{name}" has \'do\' code that was ignored')

    for top_name, s in top_states.items():
        for child_name, c in _children(s).items():
            if _has_code((c or {}).get('do')):
                warnings.append(f'State "{top_name}/{child_name}" has \'do\' code that was ignored')

    for name, s in top_states.items():
        if _edges(s):
            warnings.append(f'Top-level state "{name}" has transitions that were ignored')

    def resolve_phoenix_target(scope, to):
        """Return (phoenix_target or None, display path of the target)."""
        path = resolve_target_path(scope, to)
        if path and path[0] == 'root':
            path = path[1:]
        display = '/'.join(p.lstrip('@') for p in path)
        if not path or any(p.startswith('@') for p in path):
            return None, display
        # Target must be an existing top-level or second-level state
        if len(path) == 1 and path[0] in top_states:
            return path[0], display
        if len(path) == 2 and path[1] in _children(top_states.get(path[0])):
            return f'{path[0]} {path[1]}', display
        return None, display

    def flatten(source, scope, transitions, guards, via, seen):
        """Resolve `transitions` (of a state or decision) to [(guards, target)] in
        priority order, descending into decisions."""
        out = []
        via_str = ''.join(f' via "{v}"' for v in via)
        for t in transitions or []:
            if not isinstance(t, dict):
                continue
            to = t.get('to')
            guard = t.get('guard')
            g = guards + ([guard.strip()] if isinstance(guard, str) and guard.strip() else [])
            # Terminations and forks have no Phoenix equivalent. Directly on a state
            # they are dropped silently (as SM-gui does); inside a decision, warn.
            if not isinstance(to, str) or not to:
                if via:
                    warnings.append(f'Termination from "{source}"{via_str} was skipped')
                continue
            if '[' in to:
                if via:
                    warnings.append(f'Fork transition from "{source}"{via_str} to "{to}" was skipped')
                continue
            if is_pseudo_ref(to):
                entry = lookup_pseudo(to, scope)
                if entry and entry[0] == 'decision':
                    _, rules, pscope = entry
                    key = tuple(pscope)
                    if key in seen:
                        warnings.append(f'Decision loop from "{source}"{via_str} to "{to}" was skipped')
                        continue
                    out += flatten(source, pscope, rules, g, via + [pscope[-1]], seen | {key})
                    continue
                if entry:
                    warnings.append(f'Transition from "{source}"{via_str} to AND node '
                                    f'"{entry[2][-1]}" was skipped')
                    continue
            target, display = resolve_phoenix_target(scope, to)
            if target is None:
                warnings.append(
                    f'Transition from "{source}"{via_str} to "{display}" was skipped '
                    f'(target not in top 2 levels)')
                continue
            out.append((g, target))
        return out

    doc = {}
    for top_name, top in top_states.items():
        children = _children(top)
        if not children:
            doc[top_name] = None
            continue

        child_map = {}
        for child_name, child in children.items():
            child = child or {}
            child_obj = {}

            lines = _code_lines(child.get('entry'))
            if lines:
                child_obj['in'] = lines
            lines = _code_lines(child.get('exit'))
            if lines:
                child_obj['out'] = lines

            source = f'{top_name}/{child_name}'
            resolved = []
            seen_keys = set()
            for guards, target in flatten(source, ['root', top_name, child_name],
                                          child.get('transitions'), [], [], frozenset()):
                if resolved and not resolved[-1][0]:
                    warnings.append(f'Transition from "{source}" to "{target}" is unreachable '
                                    f'(after an unguarded transition) and was skipped')
                    continue
                key = _combine_guards(guards) if guards else ''
                if key in seen_keys:
                    warnings.append(f'Transition from "{source}" to "{target}" has the same guard '
                                    f'as an earlier one ("{key or ALWAYS}") and was skipped')
                    continue
                seen_keys.add(key)
                resolved.append((key, target))

            if len(resolved) == 1:
                guard, target = resolved[0]
                child_obj['next'] = {guard: target} if guard else target
            elif len(resolved) > 1:
                child_obj['next'] = {(guard or ALWAYS): target for guard, target in resolved}

            child_map[child_name] = child_obj or None

        doc[top_name] = child_map

    text = yaml.dump(doc, Dumper=_PhoenixDumper, sort_keys=False,
                     default_flow_style=False, allow_unicode=True, width=float('inf'))
    return text, warnings
