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
