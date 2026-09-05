"""One throwaway root for the whole suite, installed before any app module is imported.

The portal freezes its paths at import time: `db.DB_PATH`, `model.DATA_DIR`,
`integrations.CONTROL_FILE` and their neighbours are module-level constants read from the
environment exactly once. Whatever the environment holds when the first test module is
imported is what every test in the run then reads and writes.

That redirect used to live in the test modules themselves, so which values won depended on
which filename sorted first — and the first one used `os.environ.setdefault`, which keeps
an existing value instead of replacing it. Inside the portal/admin container those values
are the live ones, so running the suite there pointed `db.DB_PATH` at the real
`/data/platform.db` and emptied the sessions table.

pytest imports conftest.py before it imports any test module, so this is the one place the
redirect cannot lose a race. Three rules follow from the bug: assign rather than
`setdefault`, cover every constant that names platform state (not just the database), and
assert afterwards that the constants really did land under this root — a run that is
somehow still pointed at real data must fail loudly at collection, not quietly destroy it.
"""
import os
import shutil
import sys
import tempfile

TEST_ROOT = tempfile.mkdtemp(prefix="portal-tests-")

DATA_DIR = os.path.join(TEST_ROOT, "data")
WORKSPACE_DIR = os.path.join(TEST_ROOT, "workspace")
PROBLEMS_SEED_DIR = os.path.join(TEST_ROOT, "problems_seed")
CONTROL_FILE = os.path.join(TEST_ROOT, "control", "active.json")
# scripts/ holds export_session.sh and reset_workspace.sh, which really do export and
# really do wipe a workspace. Point integrations at a directory that has neither, so the
# worst a test can reach is the "script not found, skipping" branch.
SCRIPTS_DIR = os.path.join(TEST_ROOT, "no-scripts")

for _d in (DATA_DIR, WORKSPACE_DIR, PROBLEMS_SEED_DIR, os.path.dirname(CONTROL_FILE)):
    os.makedirs(_d, exist_ok=True)

os.environ["PLATFORM_DB"] = os.path.join(DATA_DIR, "platform.db")
os.environ["DATA_DIR"] = DATA_DIR
os.environ["WORKSPACE_DIR"] = WORKSPACE_DIR
os.environ["PROBLEMS_SEED_DIR"] = PROBLEMS_SEED_DIR
os.environ["CONTROL_FILE"] = CONTROL_FILE
os.environ["SCRIPTS_DIR"] = SCRIPTS_DIR
# Not a real secret and not meant to be one; it only has to differ from the public dev
# default, which model.assert_boot_config() rejects by name outside APP_ENV=dev.
os.environ["PORTAL_SECRET"] = "test-secret-not-default"
os.environ["APP_ENV"] = "dev"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import integrations  # noqa: E402
import model  # noqa: E402
import registry  # noqa: E402

# Importing them here is half the point: the constants are now frozen to this root, so a
# test module can no longer freeze them to anything else by importing first.
_FROZEN = {
    "db.DB_PATH": db.DB_PATH,
    "model.DATA_DIR": model.DATA_DIR,
    "registry.DATA_DIR": registry.DATA_DIR,
    "integrations.CONTROL_FILE": integrations.CONTROL_FILE,
    "integrations.WORKSPACE_DIR": integrations.WORKSPACE_DIR,
    "integrations.PROBLEMS_SEED_DIR": integrations.PROBLEMS_SEED_DIR,
    "integrations.SCRIPTS_DIR": integrations.SCRIPTS_DIR,
}
_escaped = sorted(f"{name} = {value}" for name, value in _FROZEN.items()
                  if not os.path.abspath(value).startswith(TEST_ROOT + os.sep))
if _escaped:
    raise RuntimeError(
        "refusing to run: the suite is pointed at paths outside its throwaway root "
        f"({TEST_ROOT}), so it would read and write real platform state — "
        + "; ".join(_escaped))


def pytest_sessionfinish(session, exitstatus):
    """Delete the root. Some of it is deliberately read-only (integrations chmods seeded
    problem data to 0555), and a directory has to be writable to lose its entries."""
    for base, dirs, _files in os.walk(TEST_ROOT):
        for name in dirs:
            try:
                os.chmod(os.path.join(base, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
