"""the manifests ARE the problem index. registry.py scans
$PROBLEMS_ROOT/*/problem.yaml for id/title/status instead of parsing a separate
registry.yaml (which drifted on every single problem before it was collapsed).
"""
import os

import pytest

import registry

REPO_PROBLEMS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), "problems")


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A problems root with two manifests, a _template, and a non-problem dir;
    overrides pointed at a throwaway file."""
    def manifest(dirname, body):
        d = tmp_path / dirname
        d.mkdir()
        (d / "problem.yaml").write_text(body, encoding="utf-8")

    manifest("_template", "id: never-listed\ntitle: T\nstatus: draft\n")
    manifest("b-second-001",
             "id: b-second-001\n"
             "title: Second problem  # trailing comment stripped\n"
             "status: hidden\n"
             "summary: >\n  indented lines are\n  not top-level keys\n")
    manifest("a-first-001",
             "# leading comment\n"
             "id: a-first-001\ntitle: First problem\nstatus: active\n"
             "candidate_paths:\n  - problem.md\n")
    (tmp_path / "not-a-problem").mkdir()  # no problem.yaml — skipped
    monkeypatch.setattr(registry, "VISIBILITY_PATH", str(tmp_path / "vis.json"))
    return str(tmp_path)


def test_scan_lists_manifests_sorted_and_skips_template(root):
    got = registry.all_problems(root)
    assert [p["id"] for p in got] == ["a-first-001", "b-second-001"]
    assert got[0]["title"] == "First problem"
    assert got[1]["title"] == "Second problem"          # comment stripped
    assert got[0]["status"] == "active" and got[0]["visible"] is True
    assert got[1]["status"] == "hidden" and got[1]["visible"] is False


def test_admin_override_wins_over_manifest_status(root):
    registry.set_visibility("b-second-001", True)
    got = {p["id"]: p for p in registry.all_problems(root)}
    assert got["b-second-001"]["visible"] is True
    assert got["b-second-001"]["base_status"] == "hidden"   # manifest baseline kept
    assert [p["id"] for p in registry.load_problems(root)] == \
        ["a-first-001", "b-second-001"]
    registry.set_visibility("a-first-001", False)
    assert [p["id"] for p in registry.load_problems(root)] == ["b-second-001"]


def test_missing_root_is_empty_not_an_error():
    assert registry.all_problems("/no/such/root") == []


def test_real_repo_manifests_are_the_index():
    """The committed manifests carry the statuses registry.yaml used to hold —
    and registry.yaml itself is gone."""
    assert not os.path.exists(os.path.join(REPO_PROBLEMS, "registry.yaml"))
    got = {p["id"]: p["base_status"] for p in registry.all_problems(REPO_PROBLEMS)}
    assert got == {
        "ml-eval-concepts-001": "active",
        "ml-txn-anomaly-001": "active",
    }
