#!/usr/bin/env python3
"""Print a PBKDF2-HMAC-SHA256 hash for an admin password, for ADMIN_PASSWORD_HASH
in .env (model.hash_password is the single source of the scheme).

    python environments/portal/hashpw.py 'my-password'

The line is printed ready to paste into environments/.env, with every '$' doubled.
Docker Compose interpolates '$' in .env values, so a raw hash arrives at the container
with its separators eaten and the admin account is seeded unusable; '$$' is compose's
escape for a literal '$'. Pass --raw for the unescaped hash (for a non-compose consumer).
"""
import sys

import model

USAGE = "usage: hashpw.py [--raw] <password>"

if __name__ == "__main__":
    args = sys.argv[1:]
    raw = "--raw" in args
    if raw:
        args.remove("--raw")
    if len(args) != 1:
        sys.exit(USAGE)
    digest = model.hash_password(args[0])
    if raw:
        print(digest)
    else:
        print(f"ADMIN_PASSWORD_HASH={digest.replace('$', '$$')}")
