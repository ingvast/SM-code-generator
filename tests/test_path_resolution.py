from codegen.common import resolve_target_path


CURRENT = ["root", "proc", "sys", "CP", "prepare-tanks", "empty-rg", "drip"]


def test_sibling_bare():
    assert resolve_target_path(CURRENT, "drain") == [
        "root", "proc", "sys", "CP", "prepare-tanks", "empty-rg", "drain",
    ]


def test_sibling_dotdot_equivalent_to_bare():
    # "../x" must resolve to the same path as bare "x" (both mean sibling).
    assert resolve_target_path(CURRENT, "../drain") == resolve_target_path(CURRENT, "drain")


def test_up_two_levels():
    # "../../x" goes one level above the sibling scope.
    assert resolve_target_path(CURRENT, "../../x") == [
        "root", "proc", "sys", "CP", "prepare-tanks", "x",
    ]


def test_up_three_levels():
    # Regression for not-exist.smb: dose-ch lives at CP/dose-ch, 3 "../" from drip.
    assert resolve_target_path(CURRENT, "../../../dose-ch") == [
        "root", "proc", "sys", "CP", "dose-ch",
    ]


def test_up_four_levels():
    assert resolve_target_path(CURRENT, "../../../../x") == [
        "root", "proc", "sys", "x",
    ]


def test_child_relative():
    assert resolve_target_path(CURRENT, "./child") == CURRENT + ["child"]


def test_child_nested():
    assert resolve_target_path(CURRENT, "./a/b") == CURRENT + ["a", "b"]


def test_self():
    assert resolve_target_path(CURRENT, ".") == CURRENT


def test_parent_alone():
    assert resolve_target_path(CURRENT, "..") == [
        "root", "proc", "sys", "CP", "prepare-tanks", "empty-rg",
    ]


def test_absolute_with_leading_slash():
    assert resolve_target_path(CURRENT, "/proc/sys/CP/dose-ch") == [
        "root", "proc", "sys", "CP", "dose-ch",
    ]


def test_absolute_with_root_prefix_via_slash():
    assert resolve_target_path(CURRENT, "/root/proc/sys") == ["root", "proc", "sys"]


def test_legacy_absolute_root_prefix():
    assert resolve_target_path(CURRENT, "root/proc/x") == ["root", "proc", "x"]


def test_empty_target_returns_current():
    assert resolve_target_path(CURRENT, "") == CURRENT


def test_nested_sibling_path():
    assert resolve_target_path(CURRENT, "a/b") == [
        "root", "proc", "sys", "CP", "prepare-tanks", "empty-rg", "a", "b",
    ]


def test_nested_up_path():
    assert resolve_target_path(CURRENT, "../../a/b") == [
        "root", "proc", "sys", "CP", "prepare-tanks", "a", "b",
    ]


def test_repeated_dotdot_not_collapsed_like_old_bug():
    # Old buggy resolver collapsed any number of "../" into 2 levels.
    # Ensure "../../../" and "../../" now produce different results.
    two = resolve_target_path(CURRENT, "../../x")
    three = resolve_target_path(CURRENT, "../../../x")
    assert two != three
