"""
Integration tests for the sm-compiler pipeline.

Each test fixture consists of:
  - <name>.smb          the state machine definition (with a `language:` field)
  - <name>.<lang>       the driver program (hand-written, calls into the generated SM)
  - <name>.<lang>.expect expected stdout output

Pipeline per language:
  1. Copy the driver to a temp directory
  2. Run sm-compiler.py to generate the state machine source into the same temp dir
  3. Compile the driver (which brings in the generated file)
  4. Run the binary and compare stdout to the .expect file

To add a new test case:
  - Add <name>.smb, <name>.rs (driver), <name>.rust.expect to tests/fixtures/
  - Add a test_<name>() function below
"""

import shutil
import subprocess
import sys
import pytest
import yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Language pipeline definitions
#
# gen_ext:    extension(s) appended to the -o base path by the compiler
# driver_ext: extension of the hand-written driver in fixtures/
# compile:    callable(driver_src, exe, base) -> argv list, or None
# run:        callable(driver_src, exe) -> argv list
# ---------------------------------------------------------------------------

LANG_PIPELINE = {
    "rust": {
        "gen_ext": ".rs",
        "driver_ext": ".rs",
        "compile": lambda driver, exe, base: ["rustc", str(driver), "-o", str(exe)],
        "run": lambda driver, exe: [str(exe)],
    },
    "c": {
        "gen_ext": ".c",
        "driver_ext": ".c",
        "compile": lambda driver, exe, base: ["gcc", str(driver), str(base) + ".c", "-o", str(exe)],
        "run": lambda driver, exe: [str(exe)],
    },
    "python": {
        "gen_ext": ".py",
        "driver_ext": ".py",
        "compile": None,
        "run": lambda driver, exe: [sys.executable, str(driver)],
    },
    "typescript": {
        "gen_ext": ".ts",
        "driver_ext": ".ts",
        "compile": None,
        "run": lambda driver, exe: ["npx", "tsx", str(driver)],
    },
}


def get_languages(smb_file: str) -> list[str]:
    """Read the `language` field from a .smb fixture file."""
    data = yaml.safe_load((FIXTURES / smb_file).read_text())
    lang = data.get("language", "rust")
    return [lang] if isinstance(lang, str) else list(lang)


def run_pipeline(smb_file: str, lang: str, tmp_path: Path) -> list[str]:
    """
    Run the full pipeline for one language.
    Generated and compiled files go into tmp_path (auto-cleaned by pytest).
    Returns stdout lines of the executed program.
    """
    if lang not in LANG_PIPELINE:
        raise ValueError(f"Unknown language '{lang}'. Add it to LANG_PIPELINE.")

    pipeline = LANG_PIPELINE[lang]
    stem = Path(smb_file).stem
    smb_path = FIXTURES / smb_file
    exe_path = tmp_path / stem
    output_base = tmp_path / "statemachine"

    # Step 1: Copy driver into tmp_path
    driver_src = FIXTURES / f"{stem}{pipeline['driver_ext']}"
    assert driver_src.exists(), f"Driver not found: {driver_src}"
    shutil.copy(driver_src, tmp_path / driver_src.name)
    driver_tmp = tmp_path / driver_src.name

    # Step 2: Generate state machine source into tmp_path
    result = subprocess.run(
        [sys.executable, str(ROOT / "sm_compiler.py"), str(smb_path),
         "--lang", lang, "-o", str(output_base)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"sm_compiler.py failed:\n{result.stderr}"
    generated = tmp_path / ("statemachine" + pipeline["gen_ext"])
    assert generated.exists(), f"Compiler did not produce {generated.name}"

    # Step 3: Compile
    if pipeline["compile"]:
        cmd = pipeline["compile"](driver_tmp, exe_path, output_base)
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"

    # Step 4: Run
    cmd = pipeline["run"](driver_tmp, exe_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Program exited with code {result.returncode}:\n{result.stderr}"

    return result.stdout.splitlines()


def check_output(actual_lines: list[str], smb_file: str, lang: str) -> None:
    """
    Compare actual output against <name>.expect, line by line.
    Reports all mismatches before failing.
    """
    stem = Path(smb_file).stem
    expect_path = FIXTURES / f"{stem}.expect"
    expected_lines = expect_path.read_text().splitlines()

    while actual_lines and actual_lines[-1] == "":
        actual_lines.pop()
    while expected_lines and expected_lines[-1] == "":
        expected_lines.pop()

    failures = []
    for i in range(max(len(actual_lines), len(expected_lines))):
        actual = actual_lines[i] if i < len(actual_lines) else "<missing>"
        expected = expected_lines[i] if i < len(expected_lines) else "<missing>"
        if actual != expected:
            failures.append(
                f"  Line {i + 1}:\n"
                f"    Expected: {expected!r}\n"
                f"    Got:      {actual!r}"
            )

    assert not failures, "Output mismatch:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_version():
    """--version / -v prints the version from pyproject.toml and exits cleanly."""
    import tomllib
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

    result = subprocess.run(
        [sys.executable, str(ROOT / "sm_compiler.py"), "-v"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == expected

@pytest.mark.parametrize("lang", get_languages("transition-verification-rust.smb"))
def test_transition_verification(lang, tmp_path):
    """Full pipeline test covering all transition types in the HSM."""
    actual = run_pipeline("transition-verification-rust.smb", lang, tmp_path)
    check_output(actual, "transition-verification-rust.smb", lang)


@pytest.mark.parametrize("lang", get_languages("transition-verification-c.smb"))
def test_transition_verification_c(lang, tmp_path):
    """Same machine as test_transition_verification but targeting the C backend."""
    actual = run_pipeline("transition-verification-c.smb", lang, tmp_path)
    check_output(actual, "transition-verification-c.smb", lang)


@pytest.mark.parametrize("lang", get_languages("transition-verification-python.smb"))
def test_transition_verification_python(lang, tmp_path):
    """Same machine as test_transition_verification but targeting the Python backend."""
    actual = run_pipeline("transition-verification-python.smb", lang, tmp_path)
    check_output(actual, "transition-verification-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("self-transition-python.smb"))
def test_self_transition_python(lang, tmp_path):
    """Test self transition by to: ."""
    actual = run_pipeline("self-transition-python.smb", lang, tmp_path)
    check_output(actual, "self-transition-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("transition-verification-typescript.smb"))
def test_transition_verification_typescript(lang, tmp_path):
    """Same machine as test_transition_verification but targeting the TypeScript backend."""
    actual = run_pipeline("transition-verification-typescript.smb", lang, tmp_path)
    check_output(actual, "transition-verification-typescript.smb", lang)

@pytest.mark.parametrize("lang", get_languages("dashed-names.smb"))
def test_dashed_names(lang, tmp_path):
    """Test that state names with dashes work correctly."""
    actual = run_pipeline("dashed-names.smb", lang, tmp_path)
    check_output(actual, "dashed-names.smb", lang)

@pytest.mark.parametrize("lang", get_languages("timer-test.smb"))
def test_timer(lang, tmp_path):
    """Two-state machine: transitions from 'waiting' to 'done' after 0.1s (10 ticks of 0.01s) using the built-in time variable."""
    actual = run_pipeline("timer-test.smb", lang, tmp_path)
    check_output(actual, "timer-test.smb", lang)


@pytest.mark.parametrize("lang", get_languages("self-transition-composite.smb"))
def test_self_transition_composite(lang, tmp_path):
    """Self-transition (to: .) on a composite state exits/re-enters child and parent."""
    actual = run_pipeline("self-transition-composite.smb", lang, tmp_path)
    check_output(actual, "self-transition-composite.smb", lang)

@pytest.mark.parametrize("lang", get_languages("decision-scope-python.smb"))
def test_decision_scope(lang, tmp_path):
    """Decision-rule `to:` paths must resolve from the decision's own scope,
    not from the caller state's path. Covers bare-sibling and `./` forms."""
    actual = run_pipeline("decision-scope-python.smb", lang, tmp_path)
    check_output(actual, "decision-scope-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("hierarchical-decisions-python.smb"))
def test_hierarchical_decisions(lang, tmp_path):
    """Hierarchical pseudo-state references (SM-builder-version >= 0.6.0).
    Tests @D (same-container) and ../Sibling/@D (relative cross-container) refs."""
    actual = run_pipeline("hierarchical-decisions-python.smb", lang, tmp_path)
    check_output(actual, "hierarchical-decisions-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("and-join-python.smb"))
def test_and_join(lang, tmp_path):
    """AND join node (ands: block, SM-builder-version >= 0.6.0).
    Orthogonal state with two regions feeding @A1; AND gate fires only when
    both regions are simultaneously in their ready state (step>=3)."""
    actual = run_pipeline("and-join-python.smb", lang, tmp_path)
    check_output(actual, "and-join-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("and-3way-python.smb"))
def test_and_3way(lang, tmp_path):
    """3-way AND join: three orthogonal regions all feed the same AND node.
    Staggered guards (step>=2, >=3, >=4) verify the AND does NOT fire until
    all three guards are simultaneously satisfied (at step=4)."""
    actual = run_pipeline("and-3way-python.smb", lang, tmp_path)
    check_output(actual, "and-3way-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("and-cross-boundary-python.smb"))
def test_and_cross_boundary(lang, tmp_path):
    """Cross-orthogonal-boundary AND: AND node at root level, sources from
    different nested orthogonal composites (ActiveA inside OrthoA/Worker,
    ActiveB directly in OrthoB). Demonstrates generality beyond sibling regions."""
    actual = run_pipeline("and-cross-boundary-python.smb", lang, tmp_path)
    check_output(actual, "and-cross-boundary-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("and-time-join-python.smb"))
def test_and_time_join(lang, tmp_path):
    """AND join with the special `time` variable in source guards. Each source's
    `time` must be measured from that source's own entry, not from the firing
    region's. SB2 is entered later than SA, so the join fires at now=4 (SB2
    active >= 2), not at now=3."""
    actual = run_pipeline("and-time-join-python.smb", lang, tmp_path)
    check_output(actual, "and-time-join-python.smb", lang)

@pytest.mark.parametrize("lang", get_languages("and-order-join-python.smb"))
def test_and_order_join(lang, tmp_path):
    """AND join must honor the other source's transition ordering. RegA ticks
    first and would evaluate the join, but RegB lists a higher-priority /Escaped
    transition before its join edge. The join is suppressed so RegB escapes."""
    actual = run_pipeline("and-order-join-python.smb", lang, tmp_path)
    check_output(actual, "and-order-join-python.smb", lang)

