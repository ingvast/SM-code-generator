SM-code-generator
=================

**TODO: write proper README**

<!-- Notes for when writing the real README -->

## Installation

### Isolated tool install (recommended — puts `sm-compiler` on PATH)

```bash
# From GitHub (latest main, no clone needed)
pipx install git+https://github.com/ingvast/SM-code-generator.git

# From a local clone
pipx install .
```

### pip / uv pip install (into the active Python environment)

```bash
# From GitHub
pip install git+https://github.com/ingvast/SM-code-generator.git
uv pip install git+https://github.com/ingvast/SM-code-generator.git

# From local source directory
pip install .
uv pip install .

# From a built wheel
pip install dist/smbuilder-0.6.1-py3-none-any.whl
uv pip install dist/smbuilder-0.6.1-py3-none-any.whl
```

### Build and install from source

```bash
uv build
uv tool install dist/smbuilder-*.whl
```

### PyPI (not yet published)

Once published: `pip install smbuilder`

## Man page

The man page (`sm-compiler.1`) is included in the wheel and installed to
`{prefix}/share/man/man1/`. For `pip install` (system) this is on the
standard `MANPATH` automatically. For `uv tool install` or `pipx install`
the prefix is inside the tool's isolated venv; add its `share/man` directory
to `MANPATH` or copy the file manually:

```bash
# uv tool install
export MANPATH="$HOME/.local/share/uv/tools/smbuilder/share/man:$MANPATH"

# pipx
export MANPATH="$HOME/.local/share/pipx/venvs/smbuilder/share/man:$MANPATH"
```

## Development

```bash
uv run python sm_compiler.py model.smb   # run without installing
uv run pytest                            # run tests
uv build                                 # build wheel into dist/
```
