# CLAUDE.md

## Project Overview

**SM-code-generator** (aka sm-compiler) is a Python-based code generator that takes a YAML/SMB state machine definition (produced by the SM-GUI editor at `../SM-gui`) and generates executable Hierarchical State Machine (HSM) code plus a Graphviz DOT visualization.

The tool is designed to support multiple output languages. Currently **Rust, C, and Python are fully implemented and up-to-date**.

## Commands

```bash
# Generate code (language read from 'lang:' key in .smb file)
uv run python sm-compiler.py model.smb

# Override language
uv run python sm-compiler.py model.smb --lang rust
uv run python sm-compiler.py model.smb --lang c
uv run python sm-compiler.py model.smb --lang python

# Custom output base path (extensions added automatically)
# Produces /path/to/myfsm.rs, /path/to/myfsm.dot, etc.
uv run python sm-compiler.py model.smb -o /path/to/myfsm

# Run the test suite
uv run pytest
uv run pytest -v          # verbose
uv run pytest -x          # stop on first failure

# Compile and run generated Rust code manually
./compileRun transition-verification-rust.smb

# View state machine diagram
dot -Tpng statemachine.dot -o statemachine.png && open statemachine.png
```

Python 3.14, managed with `uv`. Dependencies: `pyyaml`, `pytest` (dev).

## Architecture

```
sm-compiler.py          # Entry point: CLI, YAML loading, validation, orchestration
codegen/
  base_lang.py          # Abstract BaseGenerator: shared init, recurse, emit_transition_logic, gen_inspector
  common.py             # Shared utilities: path resolution, DOT generation, LCA/exit/entry sequences
  rust_lang.py          # Rust code generator (extends BaseGenerator, templates + assemble_output)
  c_lang.py             # C code generator (extends BaseGenerator, templates + assemble_output)
  python_lang.py        # Python code generator (extends BaseGenerator, templates + assemble_output)
```

### Pipeline

1. **Parse** YAML/SMB input via `yaml.safe_load()`
2. **Collect decisions** from all levels into a flat dict (`collect_decisions()`)
3. **Validate** the model: check initial states, transition targets, fork targets, decision references
4. **Generate DOT** visualization (`common.generate_dot()`)
5. **Generate code** via the selected language backend (`RustGenerator`, `CGenerator`, or `PythonGenerator`)

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
| `initial` | root/composite | Name of default child state |
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
    <name>.smb              # state machine definition (contains `lang:` field)
    <name>.rs / .c / .py   # hand-written driver program for that language
    <name>.expect           # expected stdout output
```

### How it works

Each `.smb` fixture declares which languages to test via a `lang:` key (string or list). The test runner:
1. Reads `lang:` from the `.smb` file and parametrizes one test per language
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

## Related Projects

- **SM-GUI** (`../SM-gui`): Electron/React visual editor that produces `.smb` files consumed by this compiler.
