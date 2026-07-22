"""Tests for the admin workspace file manager (integrations.list/read/delete over the
candidate `workspace` volume). The property that matters most is confinement: an admin-
supplied path must never escape WORKSPACE_DIR (traversal or symlink), because that path
reaches os.path.join + the filesystem (the traversal class of bug).
"""
import os
import sys
import tempfile

import pytest

# Point WORKSPACE_DIR (and the other dirs integrations reads at import) at throwaways
# BEFORE importing the module — its module-level constants capture env at import time.
_WS = tempfile.mkdtemp(prefix="ws-files-test-")
_SEED = tempfile.mkdtemp(prefix="ws-files-seed-")
os.environ["WORKSPACE_DIR"] = _WS
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ws-files-data-")
os.environ["PROBLEMS_SEED_DIR"] = _SEED
os.environ.setdefault("PORTAL_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integrations  # noqa: E402


@pytest.fixture(autouse=True)
def clean_ws():
    for name in os.listdir(_WS):
        p = os.path.join(_WS, name)
        if os.path.isdir(p) and not os.path.islink(p):
            import shutil
            shutil.rmtree(p)
        else:
            os.remove(p)
    yield


def _write(rel, content="x"):
    p = os.path.join(_WS, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(content)
    return p


# --- confinement ------------------------------------------------------------
@pytest.mark.parametrize("bad", ["../etc/passwd", "..", "a/../../outside"])
def test_traversal_paths_are_rejected(bad):
    with pytest.raises(ValueError):
        integrations._safe_workspace_path(bad)


def test_absolute_looking_path_is_confined_not_escaped():
    # A leading slash is stripped and the path is confined INSIDE the workspace — it must
    # never resolve to the host's real /etc/passwd.
    target, base = integrations._safe_workspace_path("/etc/passwd")
    assert target == os.path.join(base, "etc", "passwd")
    assert target.startswith(base + os.sep)


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret")
    os.symlink(str(outside), os.path.join(_WS, "link"))
    with pytest.raises(ValueError):
        integrations.read_workspace_file("link")


def test_root_is_confined_but_allowed():
    target, base = integrations._safe_workspace_path("")
    assert target == base == os.path.realpath(_WS)


# --- list / read ------------------------------------------------------------
def test_list_orders_dirs_first_and_reports_sizes():
    _write("prob1/data/train.csv", "a,b,c\n1,2,3\n")
    _write("notes.txt", "hello")
    listing = integrations.list_workspace("")
    names = [e["name"] for e in listing["entries"]]
    assert names == ["prob1", "notes.txt"]                 # dir before file
    assert listing["entries"][0]["is_dir"] is True
    assert listing["entries"][1]["size"] == len("hello")


def test_read_file_and_binary_detection():
    _write("hello.py", "print('hi')\n")
    view = integrations.read_workspace_file("hello.py")
    assert view["binary"] is False and "print" in view["text"]

    with open(os.path.join(_WS, "blob.bin"), "wb") as fh:
        fh.write(b"\x00\x01\x02data")
    b = integrations.read_workspace_file("blob.bin")
    assert b["binary"] is True and b["text"] is None


def test_read_nonfile_raises():
    _write("dir1/f.txt")
    with pytest.raises(ValueError):
        integrations.read_workspace_file("dir1")           # a directory, not a file


# --- delete -----------------------------------------------------------------
def test_delete_file_and_dir():
    _write("keep.txt")
    _write("drop/inner.txt")
    assert integrations.delete_workspace_path("drop") == "drop"
    assert not os.path.exists(os.path.join(_WS, "drop"))
    assert os.path.exists(os.path.join(_WS, "keep.txt"))   # unrelated file untouched


def test_delete_root_refused():
    with pytest.raises(ValueError):
        integrations.delete_workspace_path("")


def test_delete_missing_raises():
    with pytest.raises(ValueError):
        integrations.delete_workspace_path("nope.txt")


# --- wipe / reset-to-clean --------------------------------------------------
def _seed(sid, pid, files):
    for rel, content in files.items():
        p = os.path.join(_SEED, sid, pid, "data", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)


def test_clear_workspace_contents_empties_but_keeps_mount():
    _write("notebook.ipynb", "{}")
    _write("sub/deep/file.txt", "x")
    with open(os.path.join(_WS, ".hidden"), "w") as fh:   # dotfiles included
        fh.write("h")
    removed = integrations.clear_workspace_contents()
    assert removed == 3                                   # notebook, sub/, .hidden
    assert os.path.isdir(_WS)                             # mount point preserved
    assert os.listdir(_WS) == []                          # everything else gone


def test_wipe_does_not_reprovision():
    # A bare wipe leaves the workspace EMPTY — it must not silently re-copy seed data.
    _write("customers.csv", "stale")
    _seed("sess-9", "prob1", {"train.csv": "pristine\n"})
    integrations.clear_workspace_contents()
    assert os.listdir(_WS) == []                          # nothing re-provisioned


def test_problem_has_seed_data():
    _seed("sess-9", "with-data", {"train.csv": "x"})
    os.makedirs(os.path.join(_SEED, "sess-9", "code-only"), exist_ok=True)  # no data/ dir
    assert integrations.problem_has_seed_data("sess-9", "with-data") is True
    assert integrations.problem_has_seed_data("sess-9", "code-only") is False
    assert integrations.problem_has_seed_data("sess-9", "not-packaged") is False


def test_session_seed_exists_distinguishes_packaged_from_not():
    assert integrations.session_seed_exists("never-activated") is False
    _seed("sess-pkgd", "p1", {"train.csv": "x"})       # packaging created the seed dir
    assert integrations.session_seed_exists("sess-pkgd") is True
