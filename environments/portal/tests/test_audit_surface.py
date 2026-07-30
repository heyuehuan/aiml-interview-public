"""the audit review surface's last two pieces — the events.jsonl timeline
and the shadow.git snapshot viewer. The gitread tests build real repos with the git
CLI exactly the way the snapshot agent does (bare GIT_DIR + read-only work-tree), then
read them back with the pure-stdlib reader — loose first, then repacked, so the
pack/delta path is exercised too.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="portal-issue4-test-")
os.environ["PLATFORM_DB"] = os.path.join(_TMP, "platform.db")
os.environ["DATA_DIR"] = _TMP
os.environ["PORTAL_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import gitread  # noqa: E402
import model  # noqa: E402
import views_admin  # noqa: E402

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git CLI not available")


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS sessions;")
    con.commit()
    con.close()
    db.init()


def _new(**kw):
    kw.setdefault("candidate_name", "Alex Doe")
    kw.setdefault("workspace_user", "candidate")
    return model.create_session(**kw)


# --- events timeline ----------------------------------------------------------
def test_read_events_is_newest_first_and_filterable():
    s = _new()  # create_session itself logs the first event
    model.record_event(s["id"], "root", "problem_released", {"problem_id": "p1", "released": 1})
    model.record_event(s["id"], "root", "problem_released", {"problem_id": "p1", "released": 2})
    model.record_event(s["id"], "candidate", "copy_action", {"path": "starter.ipynb"})
    data = model.read_events(s["id"])
    assert data["total"] >= 4
    assert data["entries"][0]["event"] == "copy_action"          # newest first
    assert "problem_released" in data["events"]
    only = model.read_events(s["id"], event="problem_released")
    assert only["total"] == 2
    assert all(e["event"] == "problem_released" for e in only["entries"])
    q = model.read_events(s["id"], query="starter.ipynb")        # detail JSON is searched
    assert q["total"] == 1 and q["entries"][0]["event"] == "copy_action"


def test_read_events_missing_stream_is_empty_not_an_error():
    assert model.read_events("no-such-session") == \
        {"entries": [], "total": 0, "shown": 0, "events": []}


def test_events_page_renders_filters_and_rows():
    s = _new()
    model.record_event(s["id"], "root", "session_extended", {"minutes": 30})
    page = views_admin.admin_events_page("root", s, model.read_events(s["id"]))
    assert "session_extended" in page and "append-only" in page
    empty = views_admin.admin_events_page(
        "root", s, {"entries": [], "total": 0, "shown": 0, "events": []})
    assert "No events recorded" in empty


# --- gitread against real agent-shaped repos ---------------------------------
@pytest.fixture
def shadow(tmp_path):
    """A bare shadow.git + work-tree, committed exactly like scripts/snapshot_agent.sh."""
    gitdir = str(tmp_path / "shadow.git")
    work = str(tmp_path / "ws")
    os.makedirs(work)
    env = dict(os.environ, GIT_DIR=gitdir, GIT_WORK_TREE=work,
               GIT_AUTHOR_NAME="snapshot-agent", GIT_AUTHOR_EMAIL="snapshot@interview.local",
               GIT_COMMITTER_NAME="snapshot-agent", GIT_COMMITTER_EMAIL="snapshot@interview.local")
    subprocess.run([GIT, "init", "-q", "--bare", gitdir], check=True)

    def commit(msg):
        subprocess.run([GIT, "add", "-A", "-f"], cwd=work, env=env, check=True)
        subprocess.run([GIT, "commit", "-q", "-m", msg], cwd=work, env=env, check=True)

    def write(rel, data):
        path = os.path.join(work, rel)
        os.makedirs(os.path.dirname(path) or work, exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(path, mode) as fh:
            fh.write(data)

    return {"gitdir": gitdir, "work": work, "env": env, "commit": commit, "write": write}


def _three_snapshots(shadow):
    big = "".join(f"line {i}: model.fit(X, y)\n" for i in range(300))
    shadow["write"]("analysis.py", big)
    shadow["write"]("notes/plan.md", "# plan\nstep one\n")
    shadow["commit"]("snapshot 2026-07-30T10:00:00Z")
    shadow["write"]("analysis.py", big + "line 300: model.predict(X)\n")
    shadow["write"]("data.bin", b"\x00\x01\x02binary")
    shadow["commit"]("snapshot 2026-07-30T10:01:00Z")
    os.remove(os.path.join(shadow["work"], "notes", "plan.md"))
    shadow["commit"]("snapshot 2026-07-30T10:02:00Z")


@needs_git
def test_log_diffs_and_blobs_from_loose_objects(shadow):
    _three_snapshots(shadow)
    repo = gitread.Repo(shadow["gitdir"])
    log = repo.log()
    assert [c["message"] for c in log] == [
        "snapshot 2026-07-30T10:02:00Z",
        "snapshot 2026-07-30T10:01:00Z",
        "snapshot 2026-07-30T10:00:00Z",
    ]
    assert all(c["ts"] for c in log) and log[0]["author"] == "snapshot-agent"

    first, second, third = log[2], log[1], log[0]
    assert {(d[0], d[1]) for d in repo.diff_summary(first["sha"])} == \
        {("A", "analysis.py"), ("A", "notes/plan.md")}      # vs the empty tree
    assert {(d[0], d[1]) for d in repo.diff_summary(second["sha"])} == \
        {("M", "analysis.py"), ("A", "data.bin")}
    assert {(d[0], d[1]) for d in repo.diff_summary(third["sha"])} == \
        {("D", "notes/plan.md")}

    files = repo.commit_files(second["sha"])
    assert "notes/plan.md" in files
    assert repo.blob(files["notes/plan.md"][0]) == b"# plan\nstep one\n"
    assert gitread.is_binary(repo.blob(files["data.bin"][0])) is True
    assert gitread.is_binary(repo.blob(files["analysis.py"][0])) is False


@needs_git
def test_reader_survives_gc_packed_objects_and_packed_refs(shadow):
    """gc packs the loose objects (with delta compression — analysis.py's two large,
    near-identical versions) and packs the refs; the reader must not care."""
    _three_snapshots(shadow)
    loose = gitread.Repo(shadow["gitdir"])
    expect = [(c["sha"], c["message"]) for c in loose.log()]
    subprocess.run([GIT, "gc", "-q", "--aggressive", "--prune=now"],
                   env=shadow["env"], cwd=shadow["work"], check=True)
    packs = os.listdir(os.path.join(shadow["gitdir"], "objects", "pack"))
    assert any(p.endswith(".pack") for p in packs)          # actually packed

    repo = gitread.Repo(shadow["gitdir"])
    assert [(c["sha"], c["message"]) for c in repo.log()] == expect
    second = repo.log()[1]
    assert {(d[0], d[1]) for d in repo.diff_summary(second["sha"])} == \
        {("M", "analysis.py"), ("A", "data.bin")}
    files = repo.commit_files(second["sha"])
    blob = repo.blob(files["analysis.py"][0])
    assert blob.endswith(b"line 300: model.predict(X)\n") and b"line 0:" in blob


@needs_git
def test_empty_repo_and_missing_repo(shadow, tmp_path):
    assert gitread.Repo(shadow["gitdir"]).head() is None    # bare init, no commits
    assert gitread.Repo(shadow["gitdir"]).log() == []
    with pytest.raises(gitread.GitReadError):
        gitread.Repo(str(tmp_path / "nope"))


@needs_git
def test_candidate_nested_repo_becomes_an_unreadable_gitlink(shadow):
    """A candidate running git init/clone in the workspace makes `git add -A` record a
    gitlink (mode 160000) whose object only exists in the nested repo — the reader must
    surface it as unreadable, and the admin route renders a note instead of 500ing."""
    sub = os.path.join(shadow["work"], "sub")
    subprocess.run([GIT, "init", "-q", sub], check=True)
    subprocess.run([GIT, "-C", sub, "-c", "user.email=c@x", "-c", "user.name=cand",
                    "commit", "-q", "--allow-empty", "-m", "inner"], check=True)
    shadow["write"]("a.txt", "hello\n")
    shadow["commit"]("snapshot with nested repo")
    repo = gitread.Repo(shadow["gitdir"])
    head = repo.log()[0]["sha"]
    files = repo.commit_files(head)
    assert files["sub"][1] == "160000"
    summary = {(d[0], d[1]) for d in repo.diff_summary(head)}
    assert ("A", "sub") in summary and ("A", "a.txt") in summary
    with pytest.raises(gitread.GitReadError):
        repo.blob(files["sub"][0])              # the admin route catches exactly this


def test_unified_diff_caps_and_binary_probe():
    lines, truncated = gitread.unified_diff(b"a\nb\n", b"a\nc\n", "f.txt")
    assert any(ln.startswith("-b") for ln in lines)
    assert any(ln.startswith("+c") for ln in lines)
    assert truncated is False
    many_old = "\n".join(f"x{i}" for i in range(500)).encode()
    _, truncated = gitread.unified_diff(many_old, b"y\n", "f.txt", max_lines=10)
    assert truncated is True
    assert gitread.is_binary(b"plain text") is False
    assert gitread.is_binary(b"\x00\x01") is True


# --- snapshot pages render ----------------------------------------------------
def _commit(sha="a" * 40, parents=()):
    return {"sha": sha, "tree": "t" * 40, "parents": list(parents),
            "author": "snapshot-agent", "ts": "2026-07-30T10:01:00+00:00",
            "message": "snapshot 2026-07-30T10:01:00Z"}


def test_snapshots_list_page_renders_rows_and_blankslate():
    s = _new()
    c = _commit()
    page = views_admin.admin_snapshots_page("root", s, [c], {c["sha"]: 2})
    assert c["sha"][:10] in page and "2 files" in page
    empty = views_admin.admin_snapshots_page("root", s, [], {})
    assert "No snapshots recorded" in empty
    broken = views_admin.admin_snapshots_page("root", s, [], {}, problem="corrupt loose object")
    assert "Could not read shadow.git" in broken


def test_snapshot_detail_page_renders_diffs_and_notes():
    s = _new()
    diffs = [
        {"status": "M", "path": "analysis.py", "truncated": False, "in_commit": True,
         "lines": ["--- a/analysis.py", "+++ b/analysis.py", "-old", "+new"], "note": None},
        {"status": "A", "path": "data.bin", "lines": None, "truncated": False,
         "in_commit": True, "note": "binary file (9 bytes)"},
        {"status": "D", "path": "notes/plan.md", "lines": [], "truncated": False,
         "in_commit": False, "note": None},
    ]
    page = views_admin.admin_snapshot_page("root", s, _commit(parents=["b" * 40]), diffs)
    assert "analysis.py" in page and "+new" in page and "-old" in page
    assert "binary file (9 bytes)" in page
    assert "modified" in page and "added" in page and "deleted" in page
    assert ("b" * 40)[:10] in page                           # parent link
    # A deleted file has no content at this commit — no View link for it.
    assert page.count("View file") == 2


def test_snapshot_file_page_escapes_and_caps():
    s = _new()
    page = views_admin.admin_snapshot_file_page(
        "root", s, _commit(), "a.py", b"<script>alert(1)</script>")
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    capped = views_admin.admin_snapshot_file_page(
        "root", s, _commit(), "big.csv", b"x" * 100, max_bytes=10)
    assert "showing first 10 of 100 bytes" in capped
    binary = views_admin.admin_snapshot_file_page(
        "root", s, _commit(), "d.bin", b"\x00\x01", binary=True)
    assert "binary file" in binary
