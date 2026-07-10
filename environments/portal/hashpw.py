#!/usr/bin/env python3
"""Print a scrypt hash for an admin password, for ADMIN_PASSWORD_HASH in .env.

    python environments/portal/hashpw.py 'my-password'
"""
import sys

import model

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: hashpw.py <password>")
    print(model.hash_password(sys.argv[1]))
