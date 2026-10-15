"""Run VLAN Provisioning end to end: python3 e2e.py <approve|reject> '<json variables>'"""
import json, sys, time
from api import call
from job import start, wait, summary, var
decision = sys.argv[1]
variables = json.loads(sys.argv[2])
jid = start("VLAN Provisioning", variables, "e2e %s" % decision)
print("job", jid)
d = wait(jid)
print("first stop:", d.get("status"), "manual" if d.get("_manual") else "")
if d.get("_manual"):
    for _ in range(20):
        c, r = call("GET", f"/work-center-service/work-items?rootExecutionId={jid}")
        items = [i for i in (r.get("items") or []) if i.get("status") not in ("complete", "completed")]
        if items: break
        time.sleep(3)
    wi = items[0]
    print("work item", wi.get("id"), wi.get("status"))
    print("claim", call("PATCH", f"/work-center-service/work-items/{wi['id']}/claim", {})[0])
    c, r = call("PATCH", f"/work-center-service/work-items/{wi['id']}/complete",
                {"finishState": "success" if decision == "approve" else "failure", "variables": {}})
    print("complete", c, json.dumps(r)[:200])
    d = wait(jid, timeout=900, manual_stop=False)
print("final:", d.get("status"), json.dumps(d.get("error"))[:800])
for row in summary(jid): print(row)
print("status:", var(jid, "status"))
rep = var(jid, "report")
print(json.dumps(rep, indent=1)[:3000] if not isinstance(rep, dict) else rep.get("evidence") or json.dumps(rep)[:3000])
cp = var(jid, "crPrep") or {}
print("CR:", (cp.get("stdout_json") or {}).get("number"))
