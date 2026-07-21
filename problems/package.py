#!/usr/bin/env python3
"""the packager problem packager.

    python -m problems.package <session_id> <problem_id>...

Builds ``$PROBLEMS_SEED_DIR/<session_id>/`` — the read-only seed the workspace
entrypoint copies into the candidate volume, and the same source the portal's
"copy to workspace" button copies from.

Visibility contract (CLAUDE.md hard rule): ONLY a problem's ``candidate_paths``
(plus generated candidate data) may reach a candidate. This module is the *sole*
component that copies problem content, so it enforces the contract by construction:

  * it copies exactly the files/dirs listed in ``candidate_paths`` — nothing else
    from the source tree (never ``solution/``, ``rubric.md``, ``generate.py``,
    ``data_raw/``, ``*.xls`` answer sources, ...);
  * for the candidate dataset it prefers a problem's committed ``data/dist/``
    (pre-compiled, delivery-guaranteed) and only falls back to running
    ``data.generator`` in a throwaway copy when no ``dist/`` is present, shipping
    only the *top-level* files under ``data/out/`` (never the
    ``data/out/generated/`` subtree of interviewer answer keys);
  * a denylist backstops the whitelist in case a manifest is mis-authored.

Fail loud on missing data: if a problem is supposed to carry a candidate dataset
(it commits ``data/dist/`` or declares ``data.generator``) but neither path
delivers a single file, the packager raises and exits non-zero — a seed that
would drop the candidate into an empty data dir is treated as broken, not shipped.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # .../problems
PROBLEMS_ROOT = os.environ.get("PROBLEMS_ROOT", HERE)
SEED_ROOT = os.environ.get("PROBLEMS_SEED_DIR", "/problems_seed")

# Names that must never land in a candidate workspace, whatever a manifest says.
DENY_PARTS = {"solution", "data_raw"}
DENY_NAMES = {"rubric.md", "generate.py", "sanity_check.md"}
DENY_SUFFIXES = (".xls", ".xlsx")
# Heuristic backstop: any path part containing one of these never ships, whatever
# path it arrives by (a mis-placed answer_key.csv in dist/, a generator that emits
# grading notes, ...). Deliberately NOT including bare "label"/"key": labels.csv is
# documented candidate training data and "key" alone is
# too generic — "answer" already catches answer_key.*.
DENY_SUBSTRINGS = ("answer", "solution", "rubric", "grading", "sanity_check")


def _log(msg):
    print(f"[package] {msg}", file=sys.stderr, flush=True)


# --- tiny manifest reader (no YAML dependency) ----------------
def clean_scalar(val):
    """De-comment and unquote a YAML scalar value: drop a trailing `# comment`, strip
    surrounding whitespace, then surrounding quotes. Shared with the portal registry
    parser so both tiny hand-rolled readers treat a scalar identically."""
    return val.split(" #", 1)[0].strip().strip("\"'")


def parse_manifest(path):
    """Pull the few fields the packager needs from a problem.yaml: id, title, the
    ``candidate_paths`` list, ``data.generator``, and the folded ``summary``. A
    deliberately small parser — it understands top-level scalars, one block list,
    a one-level nested map (``data:``), and a folded ``summary: >`` block."""
    man = {"id": None, "title": None, "summary": "", "candidate_paths": [], "generator": None}
    section = None  # None | "candidate_paths" | "data" | "summary"
    with open(path, encoding="utf-8") as fh:
        for raw in fh.read().splitlines():
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                if section != "summary":
                    continue
            indented = line[:1] in (" ", "\t")
            stripped = line.strip()

            # A new top-level key closes any open section.
            if not indented and ":" in stripped and not stripped.startswith("- "):
                key, _, val = stripped.partition(":")
                key, val = key.strip(), clean_scalar(val)
                section = None
                if key == "candidate_paths":
                    section = "candidate_paths"
                elif key == "data":
                    section = "data"
                elif key == "summary":
                    section = "summary"
                elif key == "id":
                    man["id"] = val
                elif key == "title":
                    man["title"] = val
                continue

            if section == "candidate_paths" and stripped.startswith("- "):
                man["candidate_paths"].append(stripped[2:].strip().strip("\"'"))
            elif section == "data" and ":" in stripped:
                k, _, v = stripped.partition(":")
                if k.strip() == "generator":
                    man["generator"] = clean_scalar(v)
            elif section == "summary" and indented:
                man["summary"] += (" " if man["summary"] else "") + stripped
    return man


# --- safe copying -----------------------------------------------------------
def _denied(rel, *, suffixes=True):
    """True if any path part is denylisted. ``suffixes=False`` for curated dataset
    shipping (dist/ and generated data), where a raw workbook can BE the dataset."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if any(p in DENY_PARTS for p in parts):
        return True
    if any(s in p.lower() for p in parts for s in DENY_SUBSTRINGS):
        return True
    name = parts[-1] if parts else ""
    if name in DENY_NAMES:
        return True
    return suffixes and name.lower().endswith(DENY_SUFFIXES)


def _safe_src(root, rel):
    """Resolve ``rel`` under ``root``, refusing escapes and denylisted content."""
    if os.path.isabs(rel) or _denied(rel):
        raise ValueError(f"refusing disallowed candidate_path: {rel!r}")
    src = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([src, os.path.realpath(root)]) != os.path.realpath(root):
        raise ValueError(f"candidate_path escapes the problem dir: {rel!r}")
    return src


def _assert_tree_safe(path, root, *, suffixes=True, _seen=None):
    """Refuse to ship anything whose *resolved* target escapes ``root`` or is
    denylisted. ``copytree`` dereferences symlinks, so a committed symlink inside a
    whitelisted dir (``starter/notes.py -> ../solution/solution.py``) would otherwise
    copy the solution into the seed. Every file/dir reachable from ``path`` is
    checked by realpath (symlinked dirs are descended, loop-safe)."""
    real_root = os.path.realpath(root)
    seen = _seen if _seen is not None else set()
    rp = os.path.realpath(path)
    if os.path.commonpath([rp, real_root]) != real_root:
        raise ValueError(f"refusing to ship {path!r}: resolves outside the problem dir")
    rel = os.path.relpath(rp, real_root)
    if rel != "." and _denied(rel, suffixes=suffixes):
        raise ValueError(f"refusing to ship {path!r}: resolves to denylisted {rel!r}")
    if os.path.isdir(path):
        if rp in seen:
            return
        seen.add(rp)
        for name in sorted(os.listdir(path)):
            _assert_tree_safe(os.path.join(path, name), root,
                              suffixes=suffixes, _seen=seen)


def _copy(src, dst, *, root=None, suffixes=True):
    """Copy a file/tree into the seed. When ``root`` is given, every entry (after
    symlink resolution) must stay under it and clear the denylist."""
    if root is not None:
        _assert_tree_safe(src, root, suffixes=suffixes)
    os.makedirs(os.path.dirname(dst.rstrip("/")) or ".", exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        shutil.copy2(src, dst)


# --- candidate data: prefer committed, pre-compiled dist/ -------------------
def _ship_compiled(problem_src, dest_data_dir):
    """Ship a problem's committed, pre-compiled candidate dataset from
    ``data/dist/`` — the deterministic, delivery-guaranteed source that rides
    along in git and needs no generator (or raw extract) on the host. Everything
    under ``dist/`` is candidate-safe by construction, so files *and* directories
    (e.g. ``reports/``) are shipped; the name/part denylist still backstops a
    mis-placed answer key. Won't clobber a path already provided via ``candidate_paths``.
    Returns the list of shipped top-level names (empty when there is no ``dist/``)."""
    dist = os.path.join(problem_src, "data", "dist")
    shipped = []
    if not os.path.isdir(dist):
        return shipped
    os.makedirs(dest_data_dir, exist_ok=True)
    for name in sorted(os.listdir(dist)):
        src = os.path.join(dist, name)
        # No DENY_SUFFIXES here: dist/ is deliberately curated candidate data, and a
        # raw workbook can BE the dataset.
        # The suffix rule still guards candidate_paths, where a mis-authored manifest
        # could reach into un-curated problem files.
        if _denied(name, suffixes=False):
            _log(f"denylisted dist/ entry not shipped: {name}")
            continue
        dst = os.path.join(dest_data_dir, name)
        if os.path.exists(dst):
            continue  # already provided via candidate_paths
        # root=problem_src: a symlink under dist/ that resolves into solution/ (or out
        # of the problem tree) raises instead of shipping the target's content.
        _copy(src, dst, root=problem_src, suffixes=False)
        shipped.append(name)
    return shipped


# --- generated candidate data (fallback when no committed dist/) ------------
def _generate_into(problem_src, dest_data_dir):
    """Run the problem's generator in a throwaway copy of the problem tree, then ship
    the top-level files it wrote under ``data/out/`` (the candidate dataset) into
    ``dest_data_dir``. The ``data/out/generated/`` subtree (interviewer answer keys)
    is never copied. A generator that *fails* (non-zero exit, timeout, OS error)
    raises ``RuntimeError`` — a broken generator must be loud, not silently ship an
    empty dataset. A clean run that produces no top-level candidate file (e.g. a
    generator that only writes interviewer answer keys) returns ``[]`` without
    error. Returns the list of shipped filenames."""
    shipped = []
    tmp = tempfile.mkdtemp(prefix="pkg-")
    try:
        work = os.path.join(tmp, "p")
        # The generator gets a working copy WITHOUT the answer material: it has no
        # business reading solution/ or the rubric, and excluding them here means a
        # buggy/malicious generator can't re-emit them as candidate data.
        # data_raw/ stays — generators legitimately compile candidate data from it.
        shutil.copytree(problem_src, work,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                      "solution", "rubric.md",
                                                      "sanity_check.md"))
        try:
            proc = subprocess.run(
                [sys.executable, "data/generate.py"],
                cwd=work, capture_output=True, text=True, timeout=180,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise RuntimeError(f"generator did not complete ({type(exc).__name__}: {exc})")
        if proc.returncode != 0:
            raise RuntimeError(
                f"generator exited {proc.returncode}: {(proc.stderr or '').strip()[-300:]}")
        out_dir = os.path.join(work, "data", "out")
        if not os.path.isdir(out_dir):
            return shipped
        os.makedirs(dest_data_dir, exist_ok=True)
        for name in sorted(os.listdir(out_dir)):
            src = os.path.join(out_dir, name)
            if os.path.isdir(src):
                continue  # skip generated/ (interviewer answer keys) and other subdirs
            # Same gate as dist/: a generator that emits an answer-key-looking file
            # (or a symlink to one) must not ship it to the candidate.
            _assert_tree_safe(src, work, suffixes=False)
            dst = os.path.join(dest_data_dir, name)
            if os.path.exists(dst):
                continue  # don't clobber a checked-in candidate file of the same name
            shutil.copy2(src, dst)
            shipped.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return shipped


# --- one problem ------------------------------------------------------------
def package_problem(problem_id, dest_root):
    src = os.path.join(PROBLEMS_ROOT, problem_id)
    manifest_path = os.path.join(src, "problem.yaml")
    if not os.path.isfile(manifest_path):
        raise ValueError(f"no such problem: {problem_id}")
    man = parse_manifest(manifest_path)
    dest = os.path.join(dest_root, problem_id)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)

    for rel in man["candidate_paths"]:
        s = _safe_src(src, rel)
        if not os.path.exists(s):
            _log(f"{problem_id}: candidate_path {rel!r} missing in source; skipped")
            continue
        _copy(s, os.path.join(dest, rel.rstrip("/")), root=src)

    dest_data = os.path.join(dest, "data")
    shipped = _ship_compiled(src, dest_data)  # committed compiled dataset — priority
    if shipped:
        _log(f"{problem_id}: shipped compiled dataset ({', '.join(shipped)})")
    elif man["generator"]:
        shipped = _generate_into(src, dest_data)  # fallback: regenerate on the host
        if shipped:
            _log(f"{problem_id}: generated {', '.join(shipped)}")

    # Fail loud: a committed data/dist/ is a problem's promise that it ships a
    # candidate dataset. If it delivered nothing, that promise is broken — block
    # the seed rather than start the candidate in an empty data dir (the pilot
    # failure mode). A crashing generator already raised above; this also catches
    # an empty/denylist-only dist/.
    if os.path.isdir(os.path.join(src, "data", "dist")) and not shipped:
        raise RuntimeError(
            f"{problem_id}: data/dist/ is committed but shipped no candidate files "
            f"(empty, or every entry was denylisted). Refusing to write a seed that "
            f"would hand the candidate an empty data dir."
        )
    return {"id": problem_id, "title": man["title"] or problem_id,
            "summary": man["summary"]}


# --- index ------------------------------------------------------------------
def write_index(dest_root, packaged):
    lines = ["# Your problems", "",
             "The problems assigned for this session are below. Each has its own",
             "folder with the problem statement (`problem.md`), a data dictionary",
             "(`data/README.md`), any starter code (`starter/`), and the dataset.",
             ""]
    for p in packaged:
        lines.append(f"## {p['title']}")
        lines.append("")
        lines.append(f"- Folder: `{p['id']}/`")
        lines.append(f"- Statement: `{p['id']}/problem.md`")
        if p["summary"]:
            lines.append("")
            lines.append(p["summary"])
        lines.append("")
    with open(os.path.join(dest_root, "PROBLEMS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")


def package_session(session_id, problem_ids, seed_root=None):
    dest_root = os.path.join(seed_root or SEED_ROOT, session_id)
    os.makedirs(dest_root, exist_ok=True)
    packaged = []
    for pid in problem_ids:
        packaged.append(package_problem(pid, dest_root))
        _log(f"packaged {pid} -> {dest_root}/{pid}")
    write_index(dest_root, packaged)
    return dest_root


# --- deliverability check (admin dry-run) -----------------------------------
def deliverability_report(problem_ids):
    """Dry-run the packager for each problem into a throwaway dir and report whether
    it would actually hand the candidate a dataset. Never writes a real seed. Returns
    a list of ``{id, ok, files, error}`` — ``ok`` is False if packaging raised (broken
    generator, empty dist/, ...) or the problem shipped no data files at all. This is
    what the admin "validate data" button runs before a session goes live."""
    report = []
    for pid in problem_ids:
        entry = {"id": pid, "ok": False, "files": [], "error": None}
        tmp = tempfile.mkdtemp(prefix="pkg-check-")
        try:
            package_problem(pid, tmp)
            data_dir = os.path.join(tmp, pid, "data")
            files = []
            for root, _dirs, names in os.walk(data_dir):
                for n in names:
                    if n == "README.md":
                        continue  # the data dictionary is not the dataset
                    files.append(os.path.relpath(os.path.join(root, n), data_dir))
            entry["files"] = sorted(files)
            entry["ok"] = bool(files)
            if not files:
                entry["error"] = "no candidate data files (only the data dictionary)"
        except Exception as exc:  # broken generator / empty dist / bad manifest
            entry["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        report.append(entry)
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--check", "--check-json"):
        report = deliverability_report(argv[1:])
        if argv[0] == "--check-json":
            print(json.dumps(report))  # stdout: machine-readable for the admin panel
        else:
            for e in report:
                mark = "OK  " if e["ok"] else "FAIL"
                detail = ", ".join(e["files"]) if e["ok"] else (e["error"] or "no data")
                print(f"[{mark}] {e['id']}: {detail}")
        return 0 if all(e["ok"] for e in report) else 1
    if len(argv) < 1:
        print("usage: python -m problems.package <session_id> <problem_id>...\n"
              "       python -m problems.package --check <problem_id>...", file=sys.stderr)
        return 2
    session_id, problem_ids = argv[0], argv[1:]
    dest = package_session(session_id, problem_ids)
    _log(f"wrote seed: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
