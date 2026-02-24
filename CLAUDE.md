# CLAUDE.md

## Project Overview

**SM-code-generator** (aka sm-compiler) is a Python-based code generator that takes a YAML/SMB state machine definition (produced by the SM-GUI editor at `../SM-gui`) and generates executable Hierarchical State Machine (HSM) code plus a Graphviz DOT visualization.

The tool is designed to support multiple output languages. Currently **Rust is fully implemented and up-to-date**; a **C backend exists but is outdated** and not in sync with the current YAML schema.

## Commands

```bash
# Run the compiler (Rust output, default)
uv run python sm-compiler.py model.smb --lang rust

# Run the compiler with custom output directory
uv run python sm-compiler.py model.smb --lang rust -o /path/to/output

# Run the compiler (C output - outdated)
uv run python sm-compiler.py model.yaml --lang c

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
  c_lang.py             # C code generator (outdated, standalone, does not yet use BaseGenerator)
```

### Pipeline

1. **Parse** YAML/SMB input via `yaml.safe_load()`
2. **Collect decisions** from all levels into a flat dict (`collect_decisions()`)
3. **Validate** the model: check initial states, transition targets, fork targets, decision references
4. **Generate DOT** visualization (`common.generate_dot()`)
5. **Generate code** via the selected language backend (`RustGenerator` or `CGenerator`)

### Code Generation Pattern

The `BaseGenerator` (`codegen/base_lang.py`) implements a template-method pattern. It provides the shared algorithmic skeleton — `__init__`, `generate`, `recurse`, `emit_transition_logic`, `gen_inspector` — while subclasses supply language-specific templates (as class attributes) and implement `assemble_output()` for final source assembly. `RustGenerator` inherits from `BaseGenerator`; `CGenerator` is standalone pending its update to the current schema.

The generator recursively walks the state tree (`recurse()`), producing for each state:
- **Leaf states**: `_start`, `_entry`, `_exit`, `_do` functions
- **Composite states (OR)**: same functions plus hierarchy pointer management, history support
- **Composite states (AND/orthogonal)**: same plus parallel region entry/exit/tick with safety checks
- **Inspector functions**: for runtime state path introspection (`get_state_str()`)

State machine uses **function pointers** (`Option<StateFn>`) stored in a `Context` struct to track active states at each hierarchy level. Transitions compute exit/entry sequences based on **Least Common Ancestor (LCA)**.

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

## C Backend Status

The C generator (`c_lang.py`) is **outdated**:
- Uses old keywords: `test` instead of `guard`, `transfer_to` instead of `to`, `run` instead of `do`, `parallel` instead of `orthogonal`
- Missing features: `@decision` prefix syntax, fork targets, cross-limb orthogonal transitions, `context_init`, transition hooks with `t_src`/`t_dst`
- The `first.yaml` example file uses old C-style schema

## Improvement Ideas

### High Priority
1. **Bring C backend up to date** with current schema (rename keywords, add missing features). Once updated, refactor `CGenerator` to inherit from `BaseGenerator`.
2. **Add Python backend** - next planned target language (extend `BaseGenerator`)

### Medium Priority
3. **Input file format**: The tool accepts both `.yaml` and `.smb` files but treats them identically. Consider formally defining `.smb` as the canonical extension.
4. **Error messages**: Validation errors could include line numbers from the YAML source for better debugging.
5. **Self-transition (`.`) handling**: `resolve_target_path` returns `current_path` for `.`, which causes LCA to be at the state itself. Verify this produces correct exit+re-enter behavior in all cases.

### Low Priority
6. **`get_state_data` duplication**: Both `sm-compiler.py` and `common.py` have `get_state_data`/`resolve_state_data` doing the same thing.
7. **Guard macro expansion**: `IN_STATE(X)` is expanded to `ctx.in_state_X()` via regex in Rust. This should be language-specific and handled in the generator, not hardcoded.
8. **Makefile** is configured for C workflow; the Rust workflow uses `compileRun` script instead.

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
| `transition-verification-c` | C | Failing — C backend is outdated |

## Related Projects

- **SM-GUI** (`../SM-gui`): Electron/React visual editor that produces `.smb` files consumed by this compiler.
