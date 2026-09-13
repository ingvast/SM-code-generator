"""Phoenix YAML export (--phoenix).

The export started as a port of SM-gui's Ctrl-E export; it now flattens decisions,
writes unguarded entries as `always`, and drops unreachable/duplicate-guard entries
(see codegen/phoenix_export.py). Expected files in fixtures/phoenix/:
  <name>.phoenix.yaml   exported YAML
  <name>.warnings       warnings, one per line
The source model is fixtures/phoenix/<name>.smb, or fixtures/<name>.smb if absent there.
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from codegen.phoenix_export import convert_to_phoenix_yaml

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PHOENIX = FIXTURES / "phoenix"
CASES = sorted(p.name.removesuffix(".phoenix.yaml") for p in PHOENIX.glob("*.phoenix.yaml"))


def source_for(name):
    local = PHOENIX / f"{name}.smb"
    return local if local.exists() else FIXTURES / f"{name}.smb"


@pytest.mark.parametrize("name", CASES)
def test_matches_gui_export(name):
    text, warnings = convert_to_phoenix_yaml(yaml.safe_load(source_for(name).read_text()))
    assert text == (PHOENIX / f"{name}.phoenix.yaml").read_text()
    expected_warnings = (PHOENIX / f"{name}.warnings").read_text().splitlines()
    assert sorted(warnings) == sorted(expected_warnings)


def test_cli_writes_phoenix_file_without_code(tmp_path):
    base = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(ROOT / "sm_compiler.py"), str(source_for("tricky")),
         "--phoenix", "-o", str(base)],
        check=True, capture_output=True, text=True,
    )
    assert (tmp_path / "out-phoenix.yaml").read_text() == (PHOENIX / "tricky.phoenix.yaml").read_text()
    assert [p.name for p in tmp_path.iterdir()] == ["out-phoenix.yaml"]
