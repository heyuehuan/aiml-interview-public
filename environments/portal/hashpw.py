#!/usr/bin/env python3
"""Print a PBKDF2-HMAC-SHA256 hash for an admin password, for ADMIN_PASSWORD_HASH
in .env (model.hash_password is the single source of the scheme).

    python environments/portal/hashpw.py 'my-password'
"""
import sys

import model

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: hashpw.py <password>")
    print(model.hash_password(sys.argv[1]))
