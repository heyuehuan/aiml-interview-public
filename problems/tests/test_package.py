"""Packager visibility-contract tests (CONTRIBUTING: the packager must have tests).

a committed symlink inside a whitelisted dir must not dereference into
solution/ (or out of the problem tree) and ship the target's content.
name-denylisted content (answer keys etc.) must not ship from data/dist/
or a generator's data/out/, at any depth.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from problems import package  # noqa: E402


def _mk_problem(root, pid="p-001"):
    src = root / pid
    (src / "starter").mkdir(parents=True)
    (src / "solution").mkdir()
    (src / "data" / "dist").mkdir(parents=True)
    (src / "problem.md").write_text("# P\n")
    (src / "problem.yaml").write_text(
        "id: %s\ntitle: Test problem\ncandidate_paths:\n  - problem.md\n  - starter/\n" % pid
    )
    (src / "starter" / "main.py").write_text("print('hi')\n")
    (src / "solution" / "solution.py").write_text("SECRET_ANSWER = 42\n")
    (src / "data" / "dist" / "input.csv").write_text("a,b\n1,2\n")
    return src


def test_clean_problem_packages(tmp_path, monkeypatch):
    root, dest = tmp_path / "problems", tmp_path / "seed"
    _mk_problem(root)
    monkeypatch.setattr(package, "PROBLEMS_ROOT", str(root))
    package.package_problem("p-001", str(dest))
    assert (dest / "p-001" / "starter" / "main.py").exists()
    assert (dest / "p-001" / "data" / "input.csv").exists()
    assert not (dest / "p-001" / "solution").exists()


def test_symlink_into_solution_is_refused(tmp_path, monkeypatch):
    root, dest = tmp_path / "problems", tmp_path / "seed"
    src = _mk_problem(root)
    os.symlink(src / "solution" / "solution.py", src / "starter" / "notes.py")
    monkeypatch.setattr(package, "PROBLEMS_ROOT", str(root))
    with pytest.raises(ValueError, match="denylisted"):
        package.package_problem("p-001", str(dest))


def test_symlink_escaping_problem_dir_is_refused(tmp_path, monkeypatch):
    root, dest = tmp_path / "problems", tmp_path / "seed"
    src = _mk_problem(root)
    outside = tmp_path / "outside.txt"
    outside.write_text("host file\n")
    os.symlink(outside, src / "starter" / "leak.txt")
    monkeypatch.setattr(package, "PROBLEMS_ROOT", str(root))
    with pytest.raises(ValueError, match="outside the problem dir"):
        package.package_problem("p-001", str(dest))


def test_dist_symlink_to_solution_is_refused(tmp_path, monkeypatch):
    root, dest = tmp_path / "problems", tmp_path / "seed"
    src = _mk_problem(root)
    os.symlink(src / "solution" / "solution.py", src / "data" / "dist" / "extra.csv")
    monkeypatch.setattr(package, "PROBLEMS_ROOT", str(root))
    with pytest.raises(ValueError, match="denylisted"):
        package.package_problem("p-001", str(dest))


def test_dist_answer_key_by_name_is_not_shipped(tmp_path, monkeypatch):
    """a mis-placed answer key in dist/ must not reach the candidate, even
    though it isn't a DENY_NAMES exact match."""
    root, dest = tmp_path / "problems", tmp_path / "seed"
    src = _mk_problem(root)
    (src / "data" / "dist" / "answer_key.csv").write_text("id,label\n1,anomaly\n")
    monkeypatch.setattr(package, "PROBLEMS_ROOT", str(root))
    package.package_problem("p-001", str(dest))
    shipped = os.listdir(dest / "p-001" / "data")
    assert "answer_key.csv" not in shipped
    assert "input.csv" in shipped  # the real dataset still ships


def test_generator_cannot_read_solution(tmp_path, monkeypatch):
    """the generator's working copy excludes solution/, so a generator that
    tries to copy the answer key into data/out/ finds nothing to copy."""
    root, dest = tmp_path / "problems", tmp_path / "gen-seed"
    pid = "g-001"
    src = root / pid
    (src / "solution").mkdir(parents=True)
    (src / "data").mkdir(parents=True)
    (src / "problem.md").write_text("# G\n")
    (src / "problem.yaml").write_text(
        "id: %s\ntitle: Gen problem\ncandidate_paths:\n  - problem.md\n"
        "data:\n  generator: data/generate.py\n" % pid
    )
    (src / "solution" / "key.txt").write_text("THE ANSWER\n")
    (src / "data" / "generate.py").write_text(
        "import os, shutil\n"
        "os.makedirs('data/out', exist_ok=True)\n"
        "open('data/out/dataset.csv','w').write('x\\n1\\n')\n"
        "# a hostile generator trying to exfiltrate the solution:\n"
        "if os.path.exists('solution/key.txt'):\n"
        "    shutil.copy('solution/key.txt', 'data/out/leaked.txt')\n"
    )
    monkeypatch.setattr(package, "PROBLEMS_ROOT", str(root))
    package.package_problem(pid, str(dest))
    shipped = os.listdir(dest / pid / "data")
    assert "dataset.csv" in shipped
    assert "leaked.txt" not in shipped


def test_parse_manifest_reads_the_trimmed_schema(tmp_path):
    """status (the visibility baseline) is a manifest field now; the parser
    returns exactly the trimmed schema's fields."""
    p = tmp_path / "problem.yaml"
    p.write_text(
        "id: p-002\ntitle: T  # comment\nstatus: hidden\n"
        "summary: >\n  first line\n  second line\n"
        "candidate_paths:\n  - problem.md\ndata:\n  generator: data/generate.py\n"
    )
    man = package.parse_manifest(str(p))
    assert man == {"id": "p-002", "title": "T", "status": "hidden",
                   "summary": "first line second line",
                   "candidate_paths": ["problem.md"], "generator": "data/generate.py"}
