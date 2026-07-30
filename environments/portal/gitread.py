"""Read-only pure-stdlib reader for the shadow.git snapshot stream.

The snapshot agent (alpine/git) commits the candidate workspace into a bare
``data/sessions/<sid>/shadow.git`` every 60 s; until now that stream had no reader
short of unpacking the export bundle and running ``git log -p`` by hand. This module
lets the admin panel render it without putting the git binary into the portal image: it parses the object store directly.

Supported: loose objects, pack-v2 packfiles including OFS/REF deltas, HEAD/refs/
packed-refs resolution, first-parent history walk, tree flattening, and a
parent-vs-commit file diff. Not supported (never produced by the agent): rename
detection, octopus merges, pack idx v1.

Everything here is read-only over an append-only stream; nothing in this module
writes. Callers must cap what they render — blobs can be dataset-sized.
"""
from __future__ import annotations

import difflib
import os
import re
import struct
import zlib
from datetime import datetime, timezone


class GitReadError(Exception):
    """The repo is missing, malformed, or an object can't be resolved."""


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Pack object type codes (pack format v2).
_T_COMMIT, _T_TREE, _T_BLOB, _T_TAG = 1, 2, 3, 4
_T_OFS_DELTA, _T_REF_DELTA = 6, 7
_TYPE_NAMES = {_T_COMMIT: "commit", _T_TREE: "tree", _T_BLOB: "blob", _T_TAG: "tag"}


class Repo:
    """One bare repository, opened per request (matches the DB-per-operation idiom)."""

    def __init__(self, gitdir):
        if not os.path.isdir(os.path.join(gitdir, "objects")):
            raise GitReadError("no git object store at this path")
        self.gitdir = gitdir
        self._packs = None      # lazy: [(idx_path, pack_path)]
        self._obj_cache = {}    # sha -> (type_name, bytes); bounded by request lifetime

    # --- refs ----------------------------------------------------------------
    def head(self):
        """The commit sha HEAD points at, or None for an empty repo."""
        try:
            with open(os.path.join(self.gitdir, "HEAD"), encoding="utf-8") as fh:
                head = fh.read().strip()
        except OSError:
            return None
        if head.startswith("ref: "):
            return self._resolve_ref(head[5:].strip())
        return head if _SHA_RE.match(head) else None

    def _resolve_ref(self, refname):
        path = os.path.join(self.gitdir, *refname.split("/"))
        try:
            with open(path, encoding="utf-8") as fh:
                sha = fh.read().strip()
            return sha if _SHA_RE.match(sha) else None
        except OSError:
            pass
        # packed-refs: "sha refname" lines (peeled "^" lines don't apply to branches).
        try:
            with open(os.path.join(self.gitdir, "packed-refs"), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith(("#", "^")):
                        continue
                    sha, _, name = line.partition(" ")
                    if name == refname and _SHA_RE.match(sha):
                        return sha
        except OSError:
            pass
        return None

    # --- object store --------------------------------------------------------
    def read_object(self, sha):
        """(type_name, payload_bytes) for one object, loose or packed."""
        sha = (sha or "").lower()
        if not _SHA_RE.match(sha):
            raise GitReadError("not a full object id")
        if sha in self._obj_cache:
            return self._obj_cache[sha]
        obj = self._read_loose(sha)
        if obj is None:
            obj = self._read_packed(sha)
        if obj is None:
            raise GitReadError(f"object {sha[:12]} not found")
        self._obj_cache[sha] = obj
        return obj

    def _read_loose(self, sha):
        path = os.path.join(self.gitdir, "objects", sha[:2], sha[2:])
        try:
            with open(path, "rb") as fh:
                raw = zlib.decompress(fh.read())
        except OSError:
            return None
        except zlib.error as exc:
            raise GitReadError(f"corrupt loose object {sha[:12]}: {exc}")
        header, _, payload = raw.partition(b"\x00")
        type_name = header.split(b" ", 1)[0].decode("ascii", "replace")
        return (type_name, payload)

    def _pack_files(self):
        if self._packs is None:
            self._packs = []
            pack_dir = os.path.join(self.gitdir, "objects", "pack")
            try:
                names = os.listdir(pack_dir)
            except OSError:
                names = []
            for name in sorted(names):
                if name.endswith(".idx"):
                    pack = os.path.join(pack_dir, name[:-4] + ".pack")
                    if os.path.exists(pack):
                        self._packs.append((os.path.join(pack_dir, name), pack))
        return self._packs

    def _read_packed(self, sha):
        want = bytes.fromhex(sha)
        for idx_path, pack_path in self._pack_files():
            offset = self._idx_lookup(idx_path, want)
            if offset is not None:
                type_code, payload = self._read_pack_object(pack_path, offset)
                return (_TYPE_NAMES.get(type_code, "unknown"), payload)
        return None

    def _idx_lookup(self, idx_path, want):
        """Pack-index v2: fanout + sorted sha table + 32-bit (or spilled 64-bit) offsets."""
        with open(idx_path, "rb") as fh:
            data = fh.read()
        if data[:4] != b"\xfftOc" or struct.unpack(">I", data[4:8])[0] != 2:
            raise GitReadError("unsupported pack index version (only v2)")
        fanout = struct.unpack(">256I", data[8:8 + 1024])
        total = fanout[255]
        lo = fanout[want[0] - 1] if want[0] else 0
        hi = fanout[want[0]]
        names_off = 8 + 1024
        while lo < hi:                          # binary search in the sha table
            mid = (lo + hi) // 2
            entry = data[names_off + 20 * mid: names_off + 20 * (mid + 1)]
            if entry == want:
                off_off = names_off + 20 * total + 4 * total + 4 * mid  # skip crc table
                off = struct.unpack(">I", data[off_off:off_off + 4])[0]
                if off & 0x80000000:            # spilled to the 64-bit table
                    big_off = names_off + 20 * total + 4 * total + 4 * total \
                        + 8 * (off & 0x7FFFFFFF)
                    off = struct.unpack(">Q", data[big_off:big_off + 8])[0]
                return off
            if entry < want:
                lo = mid + 1
            else:
                hi = mid
        return None

    def _read_pack_object(self, pack_path, offset, _depth=0):
        """One object out of a packfile, resolving delta chains."""
        if _depth > 64:
            raise GitReadError("delta chain too deep")
        with open(pack_path, "rb") as fh:
            fh.seek(offset)
            byte = fh.read(1)[0]
            type_code = (byte >> 4) & 0x7
            shift = 4
            while byte & 0x80:                  # size varint (we trust the stream's end)
                byte = fh.read(1)[0]
                shift += 7
            if type_code == _T_OFS_DELTA:
                byte = fh.read(1)[0]
                rel = byte & 0x7F
                while byte & 0x80:              # base offset: big-endian with +1 steps
                    byte = fh.read(1)[0]
                    rel = ((rel + 1) << 7) | (byte & 0x7F)
                base_offset = offset - rel
            elif type_code == _T_REF_DELTA:
                base_sha = fh.read(20).hex()
            payload = self._inflate_from(fh)
        if type_code in (_T_COMMIT, _T_TREE, _T_BLOB, _T_TAG):
            return type_code, payload
        if type_code == _T_OFS_DELTA:
            base_type, base = self._read_pack_object(pack_path, base_offset, _depth + 1)
        elif type_code == _T_REF_DELTA:
            base_type_name, base = self.read_object(base_sha)
            base_type = {v: k for k, v in _TYPE_NAMES.items()}[base_type_name]
        else:
            raise GitReadError(f"unknown pack object type {type_code}")
        return base_type, _apply_delta(base, payload)

    @staticmethod
    def _inflate_from(fh, chunk=65536):
        """zlib-inflate a stream whose compressed length is unknown (pack entries)."""
        z = zlib.decompressobj()
        out = []
        while True:
            data = fh.read(chunk)
            if not data:
                break
            out.append(z.decompress(data))
            if z.eof:
                break
        return b"".join(out)

    # --- commits / trees ------------------------------------------------------
    def commit(self, sha):
        type_name, payload = self.read_object(sha)
        if type_name != "commit":
            raise GitReadError(f"{sha[:12]} is a {type_name}, not a commit")
        return _parse_commit(sha, payload)

    def log(self, limit=500):
        """First-parent history from HEAD, newest first. The agent never merges, so
        first-parent IS the history; a hand-made merge would still walk sanely."""
        out, sha, seen = [], self.head(), set()
        while sha and len(out) < limit and sha not in seen:
            seen.add(sha)
            c = self.commit(sha)
            out.append(c)
            sha = c["parents"][0] if c["parents"] else None
        return out

    def tree_files(self, tree_sha, _prefix=""):
        """Flatten a tree to {path: (blob_sha, mode)} — snapshot trees are small."""
        type_name, payload = self.read_object(tree_sha)
        if type_name != "tree":
            raise GitReadError(f"{tree_sha[:12]} is a {type_name}, not a tree")
        files = {}
        i = 0
        while i < len(payload):
            sp = payload.index(b" ", i)
            nul = payload.index(b"\x00", sp)
            mode = payload[i:sp].decode("ascii", "replace")
            name = payload[sp + 1:nul].decode("utf-8", "replace")
            sha = payload[nul + 1:nul + 21].hex()
            path = _prefix + name
            if mode == "40000":
                files.update(self.tree_files(sha, path + "/"))
            else:
                files[path] = (sha, mode)
            i = nul + 21
        return files

    def blob(self, sha):
        type_name, payload = self.read_object(sha)
        if type_name != "blob":
            raise GitReadError(f"{sha[:12]} is a {type_name}, not a blob")
        return payload

    def commit_files(self, sha):
        return self.tree_files(self.commit(sha)["tree"])

    def diff_summary(self, sha):
        """[(status, path, old_sha, new_sha)] vs the first parent (empty tree for the
        first snapshot). Statuses: A added, M modified, D deleted. Sorted by path."""
        c = self.commit(sha)
        new = self.tree_files(c["tree"])
        old = self.commit_files(c["parents"][0]) if c["parents"] else {}
        out = []
        for path in sorted(set(old) | set(new)):
            o, n = old.get(path), new.get(path)
            if o == n:
                continue
            if o is None:
                out.append(("A", path, None, n[0]))
            elif n is None:
                out.append(("D", path, o[0], None))
            else:
                out.append(("M", path, o[0], n[0]))
        return out


# --- helpers -----------------------------------------------------------------
def _parse_commit(sha, payload):
    head, _, message = payload.partition(b"\n\n")
    tree, parents, author, ts = None, [], "", None
    for line in head.decode("utf-8", "replace").splitlines():
        key, _, val = line.partition(" ")
        if key == "tree":
            tree = val
        elif key == "parent":
            parents.append(val)
        elif key == "committer":
            author, ts = _parse_ident(val)
        elif key == "author" and ts is None:
            author, ts = _parse_ident(val)
    return {"sha": sha, "tree": tree, "parents": parents, "author": author,
            "ts": ts, "message": message.decode("utf-8", "replace").strip()}


def _parse_ident(val):
    """'Name <email> 1690000000 +0000' -> ('Name', ISO-8601 UTC)."""
    m = re.match(r"^(.*?)\s*<[^>]*>\s+(\d+)\s+[+-]\d{4}$", val)
    if not m:
        return val, None
    when = datetime.fromtimestamp(int(m.group(2)), tz=timezone.utc)
    return m.group(1), when.isoformat(timespec="seconds")


def _apply_delta(base, delta):
    """Reconstruct a delta object: two size varints, then copy/insert opcodes."""
    i, _src_size = _delta_size(delta, 0)
    i, _dst_size = _delta_size(delta, i)
    out = []
    while i < len(delta):
        cmd = delta[i]
        i += 1
        if cmd & 0x80:                          # copy from base
            offset = size = 0
            for bit in range(4):
                if cmd & (1 << bit):
                    offset |= delta[i] << (8 * bit)
                    i += 1
            for bit in range(3):
                if cmd & (1 << (4 + bit)):
                    size |= delta[i] << (8 * bit)
                    i += 1
            out.append(base[offset:offset + (size or 0x10000)])
        elif cmd:                               # insert literal bytes
            out.append(delta[i:i + cmd])
            i += cmd
        else:
            raise GitReadError("invalid delta opcode 0")
    return b"".join(out)


def _delta_size(delta, i):
    size, shift = 0, 0
    while True:
        byte = delta[i]
        i += 1
        size |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return i, size


def is_binary(data):
    return b"\x00" in data[:8000]


def unified_diff(old_bytes, new_bytes, path, max_lines=4000):
    """Plain-text unified diff of two blobs, capped. Returns (lines, truncated)."""
    old = (old_bytes or b"").decode("utf-8", "replace").splitlines()
    new = (new_bytes or b"").decode("utf-8", "replace").splitlines()
    lines = list(difflib.unified_diff(old, new, fromfile=f"a/{path}",
                                      tofile=f"b/{path}", lineterm=""))
    if len(lines) > max_lines:
        return lines[:max_lines], True
    return lines, False
