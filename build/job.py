import json, sys, time
from api import call
PID = json.load(open(__file__.rsplit("/",1)[0] + "/ids.json"))["projectId"]
def start(wf, variables, desc="component test"):
    c, r = call("POST", "/operations-manager/jobs/start", {"workflow": f"@{PID}: {wf}", "options": {"description": desc, "type": "automation", "variables": variables}})
    if c >= 300: print(c, json.dumps(r)[:1500]); sys.exit(1)
    return r["data"]["_id"]
def tasks(jid):
    c, r = call("GET", f"/operations-manager/tasks?equals[job._id]={jid}&limit=200")
    return r.get("data", []) if isinstance(r, dict) else []
def wait(jid, timeout=600, manual_stop=True):
    t0 = time.time()
    while time.time() - t0 < timeout:
        c, r = call("GET", f"/operations-manager/jobs/{jid}")
        d = r.get("data", {})
        if d.get("status") not in ("running", "paused", "queued"):
            return d
        if manual_stop:
            m = [t for t in tasks(jid) if t.get("type") == "manual" and t.get("status") == "running"]
            if m: d["_manual"] = m; return d
        time.sleep(4)
    return {"status": "timeout"}
def task_detail(tid):
    c, r = call("GET", f"/operations-manager/tasks/{tid}")
    return r.get("data", r)
def summary(jid):
    rows = []
    for t in sorted(tasks(jid), key=lambda t: (t.get("metrics") or {}).get("start_time") or ""):
        rows.append((t.get("name"), t.get("summary"), t.get("status"), (t.get("metrics") or {}).get("finish_state")))
    return rows
def var(jid, name):
    c, r = call("GET", f"/operations-manager/jobs/{jid}?include=variables")
    return ((r.get("data") or {}).get("variables") or {}).get(name)
