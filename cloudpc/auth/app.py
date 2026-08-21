#!/usr/bin/env python3
"""CloudPC authentication portal.

Sits behind nginx. Responsibilities:
  - /login            username/password form, argon2id verification
  - /change-password  forced on first login (must_change flag) and on demand
  - /verify           nginx auth_request endpoint: 200 only if the session
                      is valid AND the session user owns the requested
                      /desktop/<user>/ path
  - /logout
  - rate limiting: per-IP and per-account failure counters with lockout
  - append-only auth log (fail2ban-compatible) at AUTH_LOG

No unauthenticated route returns anything but the login page or 401/429.
"""

import fcntl
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
SECRET_FILE = os.path.join(DATA_DIR, "flask-secret")
AUTH_LOG = os.environ.get("AUTH_LOG", "/var/log/cloudpc/auth.log")

# Lockout policy
MAX_FAILURES = 5          # consecutive failures before lockout
LOCKOUT_SECONDS = 900     # 15 minutes
IP_MAX_FAILURES = 20      # per-IP across all accounts
IP_WINDOW_SECONDS = 900

SESSION_LIFETIME = 8 * 3600

app = Flask(__name__)
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

_lock = threading.Lock()
_failures = {}      # username -> [count, first_ts, locked_until]
_ip_failures = {}   # ip -> list of ts


def _load_secret():
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return key


app.secret_key = _load_secret()
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_NAME="cloudpc_session",
    PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
)


def client_ip():
    # nginx sets X-Real-IP from $remote_addr; trust only that single hop.
    return request.headers.get("X-Real-IP", request.remote_addr or "unknown")


def authlog(event, username="-"):
    """fail2ban-friendly single-line log."""
    line = "%s cloudpc-auth %s user=%s ip=%s\n" % (
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        event, username, client_ip())
    os.makedirs(os.path.dirname(AUTH_LOG), exist_ok=True)
    with open(AUTH_LOG, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f, fcntl.LOCK_UN)


def load_users():
    with open(USERS_FILE) as f:
        return json.load(f)


def save_users(users):
    tmp = USERS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, USERS_FILE)


PASSWORD_RULES = ("Password must be at least 12 characters and contain an "
                  "uppercase letter, a lowercase letter, a digit, and a symbol.")


def password_ok(pw, username):
    if len(pw) < 12:
        return False
    classes = [re.search(r"[a-z]", pw), re.search(r"[A-Z]", pw),
               re.search(r"[0-9]", pw), re.search(r"[^a-zA-Z0-9]", pw)]
    if not all(classes):
        return False
    if username.lower() in pw.lower():
        return False
    return True


def locked_out(username, ip):
    now = time.time()
    with _lock:
        rec = _failures.get(username)
        if rec and rec[2] > now:
            return True
        stamps = [t for t in _ip_failures.get(ip, []) if now - t < IP_WINDOW_SECONDS]
        _ip_failures[ip] = stamps
        return len(stamps) >= IP_MAX_FAILURES


def register_failure(username, ip):
    now = time.time()
    with _lock:
        cnt, first, _until = _failures.get(username, (0, now, 0))
        cnt += 1
        until = now + LOCKOUT_SECONDS if cnt >= MAX_FAILURES else 0
        _failures[username] = (cnt, first, until)
        _ip_failures.setdefault(ip, []).append(now)
        return until > 0


def clear_failures(username):
    with _lock:
        _failures.pop(username, None)


@app.after_request
def security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'")
    return resp


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user"):
            return redirect("/")
        return render_template("login.html", error=None)

    username = (request.form.get("username") or "").strip()[:64]
    password = request.form.get("password") or ""
    ip = client_ip()

    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
        authlog("LOGIN-FAIL invalid-username", username or "-")
        return render_template("login.html",
                               error="Invalid credentials."), 401

    if locked_out(username, ip):
        authlog("LOGIN-LOCKED", username)
        return render_template(
            "login.html",
            error="Too many failed attempts. Try again later."), 429

    users = load_users()
    user = users.get(username)
    ok = False
    if user:
        try:
            ph.verify(user["hash"], password)
            ok = True
        except VerifyMismatchError:
            ok = False
    else:
        # Constant-ish time: hash anyway so unknown users cost the same
        ph.hash(password)

    if not ok:
        just_locked = register_failure(username, ip)
        authlog("LOGIN-FAIL", username)
        if just_locked:
            authlog("LOGIN-LOCKED", username)
            return render_template(
                "login.html",
                error="Too many failed attempts. Account locked for "
                      "15 minutes."), 429
        return render_template("login.html", error="Invalid credentials."), 401

    clear_failures(username)
    session.clear()
    session.permanent = True
    session["user"] = username
    session["issued"] = time.time()
    authlog("LOGIN-OK", username)

    if user.get("must_change"):
        session["must_change"] = True
        return redirect(url_for("change_password"))
    return redirect("/desktop/%s/" % username)


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    username = session.get("user")
    if not username:
        return redirect(url_for("login"))
    forced = bool(session.get("must_change"))

    if request.method == "GET":
        return render_template("change_password.html",
                               forced=forced, error=None,
                               rules=PASSWORD_RULES)

    current = request.form.get("current") or ""
    new = request.form.get("new") or ""
    confirm = request.form.get("confirm") or ""

    users = load_users()
    user = users.get(username)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    try:
        ph.verify(user["hash"], current)
    except VerifyMismatchError:
        authlog("PWCHANGE-FAIL wrong-current", username)
        return render_template("change_password.html", forced=forced,
                               error="Current password is incorrect.",
                               rules=PASSWORD_RULES), 401
    if new != confirm:
        return render_template("change_password.html", forced=forced,
                               error="New passwords do not match.",
                               rules=PASSWORD_RULES), 400
    if new == current:
        return render_template("change_password.html", forced=forced,
                               error="New password must differ from the "
                                     "current one.", rules=PASSWORD_RULES), 400
    if not password_ok(new, username):
        return render_template("change_password.html", forced=forced,
                               error=PASSWORD_RULES,
                               rules=PASSWORD_RULES), 400

    user["hash"] = ph.hash(new)
    user["must_change"] = False
    save_users(users)
    session.pop("must_change", None)
    authlog("PWCHANGE-OK", username)
    return redirect("/desktop/%s/" % username)


@app.route("/verify")
def verify():
    """nginx auth_request: authorize the original URI for this session."""
    username = session.get("user")
    if not username:
        abort(401)
    if session.get("must_change"):
        abort(401)          # no desktop until the password is changed
    users = load_users()
    if username not in users:
        session.clear()
        abort(401)
    uri = request.headers.get("X-Original-URI", "")
    m = re.match(r"^/desktop/([a-z_][a-z0-9_-]{0,31})(?:/|$|\?)", uri)
    if not m or m.group(1) != username:
        authlog("VERIFY-DENY foreign-desktop", username)
        abort(403)
    resp = jsonify(ok=True)
    resp.headers["X-Auth-User"] = username
    return resp


@app.route("/logout", methods=["POST", "GET"])
def logout():
    user = session.get("user")
    session.clear()
    if user:
        authlog("LOGOUT", user)
    return redirect(url_for("login"))


@app.route("/")
def index():
    username = session.get("user")
    if not username:
        return redirect(url_for("login"))
    if session.get("must_change"):
        return redirect(url_for("change_password"))
    return redirect("/desktop/%s/" % username)


@app.route("/healthz")
def healthz():
    return "ok"
