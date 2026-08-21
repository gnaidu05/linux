#!/usr/bin/env python3
"""CloudPC user management CLI (run inside the auth container).

  manage.py add <username> --role admin|user [--password PW]
  manage.py passwd <username> [--password PW]     (also re-arms must_change)
  manage.py del <username>
  manage.py list
"""
import argparse
import json
import os
import secrets
import string
import sys

from argon2 import PasswordHasher

DATA_DIR = os.environ.get("DATA_DIR", "/data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def load():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}


def save(users):
    tmp = USERS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, USERS_FILE)


def genpw():
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(14))
    return core + "!" + secrets.choice(string.digits)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("username")
    a.add_argument("--role", choices=["admin", "user"], required=True)
    a.add_argument("--password")
    w = sub.add_parser("passwd")
    w.add_argument("username")
    w.add_argument("--password")
    d = sub.add_parser("del")
    d.add_argument("username")
    sub.add_parser("list")
    args = p.parse_args()

    users = load()
    if args.cmd == "list":
        for name, u in sorted(users.items()):
            print("%-16s role=%-5s must_change=%s" %
                  (name, u.get("role"), u.get("must_change")))
        return

    if args.cmd == "del":
        if users.pop(args.username, None) is None:
            sys.exit("no such user: %s" % args.username)
        save(users)
        print("deleted %s" % args.username)
        return

    pw = args.password or genpw()
    if args.cmd == "add":
        if args.username in users:
            sys.exit("user exists: %s" % args.username)
        users[args.username] = {
            "role": args.role,
            "hash": ph.hash(pw),
            "must_change": True,
        }
    else:  # passwd
        if args.username not in users:
            sys.exit("no such user: %s" % args.username)
        users[args.username]["hash"] = ph.hash(pw)
        users[args.username]["must_change"] = True

    save(users)
    print("%s %s — initial password (must be changed at first login): %s"
          % (args.cmd, args.username, pw))


if __name__ == "__main__":
    main()
