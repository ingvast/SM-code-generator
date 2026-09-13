"""`initial:` may be omitted where it is never used; it is still required where
a composite can be entered without naming a child (see apply_implicit_initials)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def compile_model(tmp_path, smb, *extra):
    model = tmp_path / "model.smb"
    model.write_text(smb)
    return subprocess.run(
        [sys.executable, str(ROOT / "sm_compiler.py"), str(model), "--lang", "python",
         "-o", str(tmp_path / "out"), *extra],
        capture_output=True, text=True,
    )


@pytest.mark.parametrize("smb, message", [
    pytest.param("""
states:
  a: {}
  b: {}
""", "State '/' has several children but no 'initial'. It needs one because it is the root.",
        id="root"),
    pytest.param("""
initial: a
states:
  a:
    transitions:
      - to: c
  c:
    states:
      x: {}
      y: {}
""", "State '/c' has several children but no 'initial'. It needs one because the transition from '/a' targets it.",
        id="direct-target"),
    pytest.param("""
initial: a
states:
  a:
    transitions:
      - to: "@D"
  c:
    states:
      x: {}
      y: {}
decisions:
  D:
    - to: c
""", "the transition from '/a' targets it", id="via-decision"),
    pytest.param("""
initial: a
states:
  a:
    transitions:
      - to: /p/left/x
  p:
    orthogonal: true
    states:
      left:
        states:
          x: {}
          y: {}
      right:
        states:
          r1: {}
          r2: {}
""", "State '/p/right' has several children but no 'initial'. It needs one because the transition from '/a' enters its orthogonal parent '/p'.",
        id="orthogonal-sibling-region"),
    pytest.param("""
initial: a
states:
  a:
    transitions:
      - to: /p/[left/x]
  p:
    orthogonal: true
    states:
      left:
        states:
          x: {}
          y: {}
      right:
        states:
          r1: {}
          r2: {}
""", "the fork transition from '/a' does not name this region", id="fork-unnamed-region"),
    pytest.param("""
initial: h
states:
  h:
    initial: s
    history: true
    states:
      s:
        transitions:
          - to: c/x
      c:
        states:
          x: {}
          y: {}
""", "State '/h/c' has several children but no 'initial'. It needs one because its parent '/h' has history.",
        id="history"),
])
def test_initial_still_required(tmp_path, smb, message):
    result = compile_model(tmp_path, smb)
    assert result.returncode != 0
    assert message in result.stdout


def test_phoenix_never_requires_initial(tmp_path):
    result = compile_model(tmp_path, """
states:
  A:
    states:
      a1:
        transitions:
          - to: /B
      a2: {}
  B:
    states:
      b1: {}
      b2: {}
""", "--phoenix")
    assert result.returncode == 0, result.stdout
    assert (tmp_path / "out-phoenix.yaml").exists()
