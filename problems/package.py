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
  * it runs ``data.generator`` in a throwaway copy and ships only the *top-level*
    files it writes under ``data/out/`` (the candidate dataset), never the
    ``data/out/generated/`` subtree (the interviewer answer keys);
  * a denylist backstops the whitelist in case a manifest is mis-authored.

Best-effort per problem: a generator that can't run (missing deps / raw extract)
is logged and skipped so the candidate still gets the statement + starter + data
dictionary; the packager exits 0 as long as the seed dir is written.
"""
from __future__ import annotations

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


def _log(msg):
    print(f"[package] {msg}", flush=True)


# --- tiny manifest reader (no YAML dependency) ----------------
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
                key, val = key.strip(), val.split(" #", 1)[0].strip()
                section = None
                if key == "candidate_paths":
                    section = "candidate_paths"
                elif key == "data":
                    section = "data"
                elif key == "summary":
                    section = "summary"
                elif key == "id":
                    man["id"] = val.strip("\"'")
                elif key == "title":
                    man["title"] = val.strip("\"'")
                continue

            if section == "candidate_paths" and stripped.startswith("- "):
                man["candidate_paths"].append(stripped[2:].strip().strip("\"'"))
            elif section == "data" and ":" in stripped:
                k, _, v = stripped.partition(":")
                if k.strip() == "generator":
                    man["generator"] = v.split(" #", 1)[0].strip().strip("\"'")
            elif section == "summary" and indented:
                man["summary"] += (" " if man["summary"] else "") + stripped
    return man


# --- safe copying -----------------------------------------------------------
def _denied(rel):
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if any(p in DENY_PARTS for p in parts):
        return True
    name = parts[-1] if parts else ""
    return name in DENY_NAMES or name.lower().endswith(DENY_SUFFIXES)


def _safe_src(root, rel):
    """Resolve ``rel`` under ``root``, refusing escapes and denylisted content."""
    if os.path.isabs(rel) or _denied(rel):
        raise ValueError(f"refusing disallowed candidate_path: {rel!r}")
    src = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([src, os.path.realpath(root)]) != os.path.realpath(root):
        raise ValueError(f"candidate_path escapes the problem dir: {rel!r}")
    return src


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst.rstrip("/")) or ".", exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        shutil.copy2(src, dst)


# --- generated candidate data ----------------------------------------------
def _generate_into(problem_src, dest_data_dir):
    """Run the problem's generator in a throwaway copy of the problem tree, then ship
    the top-level files it wrote under ``data/out/`` (the candidate dataset) into
    ``dest_data_dir``. The ``data/out/generated/`` subtree (interviewer answer keys)
    is never copied. Returns the list of shipped filenames (may be empty)."""
    shipped = []
    tmp = tempfile.mkdtemp(prefix="pkg-")
    try:
        work = os.path.join(tmp, "p")
        shutil.copytree(problem_src, work,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        proc = subprocess.run(
            [sys.executable, "data/generate.py"],
            cwd=work, capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            _log(f"generator failed (rc={proc.returncode}); shipping static data only. "
                 f"stderr: {proc.stderr.strip()[:300]}")
            return shipped
        out_dir = os.path.join(work, "data", "out")
        if not os.path.isdir(out_dir):
            return shipped
        os.makedirs(dest_data_dir, exist_ok=True)
        for name in sorted(os.listdir(out_dir)):
            src = os.path.join(out_dir, name)
            if os.path.isdir(src):
                continue  # skip generated/ (interviewer answer keys) and other subdirs
            dst = os.path.join(dest_data_dir, name)
            if os.path.exists(dst):
                continue  # don't clobber a checked-in candidate file of the same name
            shutil.copy2(src, dst)
            shipped.append(name)
    except (subprocess.SubprocessError, OSError) as exc:
        _log(f"generator error ({type(exc).__name__}: {exc}); shipping static data only")
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
        _copy(s, os.path.join(dest, rel.rstrip("/")))

    if man["generator"]:
        shipped = _generate_into(src, os.path.join(dest, "data"))
        if shipped:
            _log(f"{problem_id}: generated {', '.join(shipped)}")
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 1:
        print("usage: python -m problems.package <session_id> <problem_id>...", file=sys.stderr)
        return 2
    session_id, problem_ids = argv[0], argv[1:]
    dest = package_session(session_id, problem_ids)
    _log(f"wrote seed: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
