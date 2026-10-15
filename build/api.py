#!/usr/bin/env python3
"""Tiny Itential API client: python3 api.py METHOD PATH [json-body-file|-] [out-file]"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

UC = Path(__file__).resolve().parents[1]
env = dict(l.strip().split("=", 1) for l in open(UC / ".env") if "=" in l and not l.startswith("#"))
BASE = env["PLATFORM_URL"].rstrip("/")


def _auth():
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": env["CLIENT_ID"], "client_secret": env["CLIENT_SECRET"]}).encode()
    r = urllib.request.Request(BASE + "/oauth/token", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    tok = json.load(urllib.request.urlopen(r))["access_token"]
    p = UC / ".auth.json"
    p.write_text(json.dumps({"platform_url": BASE, "auth_method": "oauth", "token": tok, "timestamp": int(time.time())}, indent=2))
    os.chmod(p, 0o600)
    return tok


def _token():
    try:
        return json.load(open(UC / ".auth.json"))["token"]
    except Exception:
        return _auth()


def call(method, path, body=None, retry=True):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and retry:
            _auth()
            return call(method, path, body, retry=False)
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


if __name__ == "__main__":
    m, p = sys.argv[1], sys.argv[2]
    b = None
    if len(sys.argv) > 3 and sys.argv[3] != "":
        b = json.load(sys.stdin) if sys.argv[3] == "-" else json.load(open(sys.argv[3]))
    code, res = call(m, p, b)
    out = json.dumps(res, indent=2) if not isinstance(res, str) else res
    if len(sys.argv) > 4:
        open(sys.argv[4], "w").write(out)
        print(code, "->", sys.argv[4], len(out), "bytes")
    else:
        print(code)
        print(out[:6000])
