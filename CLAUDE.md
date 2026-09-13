# CLAUDE.md

## Project Overview

**SM-code-generator** (aka sm-compiler) is a Python-based code generator that takes a YAML/SMB state machine definition (produced by the SM-GUI editor at `../SM-gui`) and generates executable Hierarchical State Machine (HSM) code, with optional Graphviz DOT/PNG visualization.

The tool is designed to support multiple output languages. Currently **Rust, C, Python, and TypeScript are fully implemented and up-to-date**.

## Commands

```bash
# Generate code (language read from 'language:' key in .smb file)
# After installing: sm-compiler model.smb
# During development:
uv run python sm_compiler.py model.smb

# Override language
uv run python sm_compiler.py model.smb --lang rust
uv run python sm_compiler.py model.smb --lang c
uv run python sm_compiler.py model.smb --lang python
uv run python sm_compiler.py model.smb --lang typescript

# Custom output base path (extensions added automatically)
uv run python sm_compiler.py model.smb -o /path/to/myfsm

# Generate Graphviz DOT file
uv run python sm_compiler.py model.smb --dot

# Generate PNG diagram (requires Graphviz 'dot' tool on PATH)
uv run python sm_compiler.py model.smb --png

# Both DOT and PNG
uv run python sm_compiler.py model.smb --dot --png

# Export to Phoenix YAML (same as SM-gui Ctrl-E) -> <output>-phoenix.yaml (implies --no-code)
uv run python sm_compiler.py model.smb --phoenix

# Skip source code generation (e.g. only --dot/--png)
uv run python sm_compiler.py model.smb --png --no-code

# Build distributable package (bump `version` in pyproject.toml first)
uv build
# Install/upgrade the `sm-compiler` command on PATH (--force replaces an older install)
uv tool install --force dist/smbuilder-0.7.0-py3-none-any.whl
uv tool list              # shows the installed smbuilder version

# Run the test suite
uv run pytest
uv run pytest -v          # verbose
uv run pytest -x          # stop on first failure

# Compile and run generated Rust code manually
./compileRun transition-verification-rust.smb

# View state machine diagram (--png generates it directly)
uv run python sm_compiler.py model.smb --png && open statemachine.png
```

Python 3.14, managed with `uv`. Dependencies: `pyyaml`, `pytest` (dev).

**Installing the CLI:** use `uv tool install`, not `uv pip install`. The `sm-compiler` on PATH
(`~/.local/bin/sm-compiler`) runs from uv's isolated tool environment
(`~/.local/share/uv/tools/smbuilder`). `uv pip install <wheel>` only installs into the project
`.venv` (used by `uv run`), so `sm-compiler --version` keeps reporting the old tool version.

## Architecture

```
sm-compiler.py          # Entry point: CLI, YAML loading, validation, orchestration
codegen/
  base_lang.py          # Abstract BaseGenerator: shared init, recurse, emit_transition_logic, gen_inspector
  common.py             # Shared utilities: path resolution, DOT generation, LCA/exit/entry sequences
  rust_lang.py          # Rust code generator (extends BaseGenerator, templates + assemble_output)
  c_lang.py             # C code generator (extends BaseGenerator, templates + assemble_output)
  python_lang.py        # Python code generator (extends BaseGenerator, templates + assemble_output)
  typescript_lang.py    # TypeScript code generator (extends BaseGenerator, templates + assemble_output)
  phoenix_export.py     # --phoenix: simple two-level Phoenix YAML export (port of SM-gui's Ctrl-E)
```

### Pipeline

1. **Parse** YAML/SMB input via `yaml.safe_load()`
2. **Collect decisions** from all levels into a flat dict (`collect_decisions()`)
3. **Validate** the model: check initial states, transition targets, fork targets, decision references
4. **Generate DOT/PNG** visualization if `--dot` or `--png` flags are given (`common.generate_dot()`)
5. **Generate code** via the selected language backend (`RustGenerator`, `CGenerator`, `PythonGenerator`, or `TypeScriptGenerator`)

### Code Generation Pattern

The `BaseGenerator` (`codegen/base_lang.py`) implements a template-method pattern. It provides the shared algorithmic skeleton — `__init__`, `generate`, `recurse`, `emit_transition_logic`, `gen_inspector` — while subclasses supply language-specific templates (as class attributes) and implement `assemble_output()` for final source assembly. Both `RustGenerator` and `CGenerator` inherit from `BaseGenerator`.

`BaseGenerator` also defines overridable **syntax hook methods** (`fmt_if_open`, `fmt_set_fn`, `fmt_opt_call`, `fmt_guard_expand`, etc.) that abstract language-specific syntax differences (e.g., Rust `if let Some(f) = ctx.ptr { f(ctx); }` vs C `if (ctx->ptr) ctx->ptr(ctx);` vs Python `if ctx.ptr is not None: ctx.ptr(ctx)`). Class attributes `STMT_END`, `BLOCK_CLOSE`, `TRUE_LIT`, `FALSE_LIT`, `COMMENT` handle syntax tokens. The `format_template()` method can be overridden for indent-sensitive languages (Python). This allows the core transition logic, orthogonal region handling, and inspector generation to be fully shared.

The generator recursively walks the state tree (`recurse()`), producing for each state:
- **Leaf states**: `_start`, `_entry`, `_exit`, `_do` functions
- **Composite states (OR)**: same functions plus hierarchy pointer management, history support
- **Composite states (AND/orthogonal)**: same plus parallel region entry/exit/tick with safety checks
- **Inspector functions**: for runtime state path introspection (`get_state_str()`)

State machine uses **function pointers** (Rust: `Option<StateFn>`, C: `StateFunc`, Python: first-class callables) stored in a `Context` struct/class to track active states at each hierarchy level. Transitions compute exit/entry sequences based on **Least Common Ancestor (LCA)**.

### Key YAML/SMB Schema Keywords

| Keyword | Scope | Description |
|---------|-------|-------------|
| `initial` | root/composite | Name of default child state (optional where never used, see below) |
| `states` | root/composite | Child state definitions |
| `transitions` | any state | List of `{guard, action, to}` |
| `guard` | transition | Boolean condition (target language expression) |
| `action` | transition | Code to run during transition |
| `to` | transition | Target path (see path syntax below) |
| `entry` / `exit` / `do` | state | Lifecycle code blocks |
| `orthogonal` | composite | `true` for parallel regions |
| `history` | composite | `true` to remember last active child |
| `decisions` | root or state | Named decision trees (`@name` references) |
| `hooks` | root | Global `entry`/`exit`/`do`/`transition` code injected everywhere |
| `context` | root | User-defined fields for the Context struct |
| `context_init` | root | Initialization code for context fields |
| `includes` | root | Code placed before the Context struct (imports, helpers) |

### Optional `initial`

`apply_implicit_initials()` (in `sm_compiler.py`, run from `validate_model`) relaxes the `initial`
requirement. A composite's initial is only used on **default entry** (entered without naming a
child). It computes every default-enterable state, mirroring `emit_transition_logic`: root;
transition/decision/AND-rule targets (followed from the source state, incl. `.`); regions of an
orthogonal ancestor entered at/below the LCA; regions a fork doesn't name; and the closure through
`initial` children, all regions of orthogonal states, and all children of `history` states. Then, for
non-orthogonal composites without `initial`: one child -> it becomes the initial; not
default-enterable -> first child as a placeholder plus `_initial_unused` (DOT hides the marker);
otherwise an error naming the reason. `--phoenix` calls `validate_model(require_initial=False)`.
Tests: `tests/test_implicit_initial.py`, fixture `implicit-initial-python`.

### Path Syntax in `to:` clauses

- `/absolute/path` - from root
- `sibling` - same parent
- `./child` - direct child
- `../uncle` - up one level then sibling
- `.` - self-transition (exit + re-enter)
- `null` - termination
- `@decision_name` - delegate to decision tree
- `/path/to/orthogonal/[region1/target, region2/target]` - explicit fork

### Transition Execution Order

1. Evaluate guard condition
2. Set `transition_fired = true`
3. Execute `action` code (if any)
4. Execute exit sequence (leaf to LCA, bottom-up)
5. Execute entry sequence (LCA to target, top-down)

### The `time` Variable

`time` in a guard means elapsed time since the **current** state was entered. It is a local
declared in each state's function preamble: `time = ctx.now - ctx.state_timers[<this state id>]`.
State ids are assigned in `recurse()` DFS pre-order; `BaseGenerator._index_state_ids()` replays
that walk so cross-references can look up the same id.

### AND Joins and `time`

A join (`@A` targeting an `ands:` node) is emitted into the firing source's `_do`. The compound
condition that checks the **other** sources must therefore rebase any `time` in those guards to
each source's own timer via `fmt_time_since(state_id)` (`ctx.now - ctx.state_timers[id]`), since a
bare `time` would otherwise resolve to the firing state's elapsed time. The compound also AND-s in
`fmt_not(...)` of each other source's **preceding** transition guards (those listed before its join
edge, recorded as `preceding_guards` in `collect_and_inputs()`), so the join only fires when no
higher-priority transition of that source would have fired first — preserving transition ordering
across regions. See fixtures `and-time-join-python` and `and-order-join-python`.

## C Backend Notes

The C generator produces a `.h` header and `.c` source file. Key differences from Rust:
- Uses `SM_Context*` pointer syntax (`ctx->field`) instead of reference (`ctx.field`)
- Function pointers are `StateFunc` (typedef) instead of `Option<StateFn>`
- `IN_STATE` checks use C macros (`#define IN_STATE_X (ctx->ptr == fn)`) instead of Rust impl methods
- `context_init` should contain C assignment statements executed after `memset` in `sm_init()` (e.g., `sm->ctx.field = value;`)
- The `first.yaml` example file uses old C-style schema and is not compatible with the current generator

## Python Backend Notes

The Python generator produces a single `.py` file containing a `Context` class, state functions, and a `StateMachine` class. Key differences:
- Uses `ctx.field` dot notation (like Rust) but with `None` instead of Rust's `Option`
- `IN_STATE` checks are methods on `Context` (e.g., `ctx.in_state_X()`)
- No compilation step — run directly with `python statemachine.py` or import it
- `context_init` uses `ctx.field = value` syntax (the `ctx = self` alias is set in `__init__`)
- Boolean literals are `True`/`False`, logical operators are `and`/`or`/`not`
- Guards use Python syntax: `ctx.counter == 5`, `ctx.flag or ctx.other`
- `PythonGenerator` overrides `format_template()` for indent-aware template substitution

## TypeScript Backend Notes

The TypeScript generator produces a single `.ts` file containing a `Context` class, top-level state functions, and a `StateMachine` class. Key details:
- Uses `ctx.field` dot notation, `null` instead of `None`, `===` for equality
- `IN_STATE` checks are methods on `Context` (e.g., `ctx.inState_X()`)
- Type alias: `type StateFn = (ctx: Context) => void;`
- Function pointer fields typed as `StateFn | null`
- Non-null assertion operator (`!`) used for calling nullable function pointers: `ctx.ptr!(ctx)`
- `context_init` uses `ctx.field = value;` syntax (the `ctx = this` alias is set in the constructor)
- Boolean literals are `true`/`false`, logical operators are `||`/`&&`/`!`
- Guards use TypeScript syntax: `ctx.counter === 5`, `ctx.flag || ctx.other`
- Run with `npx tsx statemachine.ts` or import as a module
- Exports `StateMachine` and `Context` classes

## Phoenix YAML Export

`--phoenix` (implies `--no-code`) writes `<output>-phoenix.yaml` via `codegen/phoenix_export.py`, a port of SM-gui's
`convertToPhoenixYaml` (`../SM-gui/src/yamlConverter.ts`, Ctrl-E). It runs on a deep copy of the
model taken before decision collection mutates it. Only the top two state levels are kept:
children get `in`/`out` (entry/exit split into trimmed lines) and `next` (target `"Top"` or
`"Top Child"`, a `{guard: target}` map when guarded or multiple, `always` for an unguarded one).
Phoenix evaluates guards as **Python, in order**. Deviations from the GUI export:
- Transitions into **decisions are flattened**: each rule becomes its own `next` entry with guard
  `(G) and (g1) and ...`, in priority order, recursing into nested decisions (targets resolved
  from the decision's scope; legacy `< 0.6.0` global names supported). This matches the generated
  code, where a decision with no matching rule falls through to the source's next transition.
  Decision loops and terminations/forks inside decisions are skipped with a warning.
- An unguarded entry in a `next` map gets the guard `always` (Phoenix's always-true guard; the GUI
  wrote `else`). A single unguarded transition is still written as plain `next: Target`.
- Entries after an unguarded one are unreachable and dropped (so `always` is always last); a repeated
  guard keeps the first entry. Both warn. Key order is preserved (no JS integer-key reordering).
Otherwise output matches the GUI (js-yaml layout, same warnings; AND nodes still skipped).
`tests/test_phoenix_export.py` checks the expected files in `tests/fixtures/phoenix/`.

## Improvement Ideas

### Medium Priority
1. **Input file format**: The tool accepts both `.yaml` and `.smb` files but treats them identically. Consider formally defining `.smb` as the canonical extension.
2. **Error messages**: Validation errors could include line numbers from the YAML source for better debugging.
3. **Self-transition (`.`) handling**: `resolve_target_path` returns `current_path` for `.`, which causes LCA to be at the state itself. Verify this produces correct exit+re-enter behavior in all cases.

### Low Priority
4. **`get_state_data` duplication**: Both `sm-compiler.py` and `common.py` have `get_state_data`/`resolve_state_data` doing the same thing.
5. **Makefile** is configured for C workflow; the Rust workflow uses `compileRun` script instead.

## Test Suite

Integration tests live in `tests/` and are run with `uv run pytest`.

### Structure

```
tests/
  test_integration.py       # test runner and pipeline helpers
  fixtures/
    <name>.smb              # state machine definition (contains `language:` field)
    <name>.rs / .c / .py   # hand-written driver program for that language
    <name>.expect           # expected stdout output
```

### How it works

Each `.smb` fixture declares which languages to test via a `language:` key (string or list). The test runner:
1. Reads `language:` from the `.smb` file and parametrizes one test per language
2. Copies the driver to a temporary directory
3. Runs `sm-compiler.py` to generate the state machine source into the same temp dir
4. Compiles (if needed) and runs the program
5. Compares stdout line-by-line against `<name>.expect`

Adding a new test: create `<name>.smb`, `<name>.<ext>` (driver), and `<name>.expect` in `fixtures/`, then add a `test_<name>()` function in `test_integration.py`.

Adding a new language: add an entry to `LANG_PIPELINE` in `test_integration.py` describing how to compile and run that language.

### Current fixtures

| Fixture | Language | Status |
|---------|----------|--------|
| `transition-verification-rust` | Rust | Passing — covers all transition types |
| `transition-verification-c` | C | Passing — covers all transition types |
| `transition-verification-python` | Python | Passing — covers all transition types |
| `transition-verification-typescript` | TypeScript | Passing — covers all transition types |

## Related Projects

- **SM-GUI** (`../SM-gui`): Electron/React visual editor that produces `.smb` files consumed by this compiler.
