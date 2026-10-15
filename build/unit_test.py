import json, subprocess, glob, os
def run(d):
    p = subprocess.run(["python3", "vlan.py"], input=json.dumps(d), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)
fx = {}
for f in glob.glob("fixtures/*.json"):
    j = json.load(open(f)); fx[os.path.basename(f)[:-5].replace("_", " ")] = j["result"]["stdout"]
def raw_for(cmds):
    res = []
    for c in cmds:
        key = c.replace("/", " ")
        out = fx.get(key, "% Invalid input detected at '^' marker.")
        res.append({"command": c, "output": out})
    return {"result": {"results": res}}
def collect(device, access, trunk, override=None):
    c = run({"mode": "cmds", "device": device, "accessPorts": access, "trunkPorts": trunk})
    raw = raw_for(c["commands"])
    if override:
        for r in raw["result"]["results"]:
            if r["command"] in override: r["output"] = override[r["command"]]
    s = run({"mode": "parse", "cmds": {"stdout_json": c}, "raw": raw})
    return {"variables": {"stateResult": {"stdout_json": s}}}, c
def plan(**kw):
    jd, c = collect(kw.get("device", "LAB-C8300-SW01"), kw.get("accessPorts", ""), kw.get("trunkPorts", ""), kw.pop("override", None))
    d = {"mode": "plan", "collect": jd, "justification": "demo", "device": "LAB-C8300-SW01"}; d.update(kw)
    return run(d)
ok = plan(operation="create", vlanId=3900, vlanName="DEMO_ITENTIAL_3900", accessPorts="Gi1/0/39")
print("happy valid:", ok["valid"], ok["reasons"]); print("\n".join(ok["configLines"])); print("--rb\n" + "\n".join(ok["rollbackLines"]))
assert ok["valid"]
cases = {
 "vlan 1": dict(operation="create", vlanId=1, vlanName="X", accessPorts="Gi1/0/39"),
 "bad name": dict(operation="create", vlanId=3900, vlanName="bad name", accessPorts="Gi1/0/39"),
 "exists": dict(operation="create", vlanId=10, vlanName="X", accessPorts="Gi1/0/39"),
 "modify missing": dict(operation="modify", vlanId=3900, vlanName="X", accessPorts="Gi1/0/39"),
 "bad port": dict(operation="create", vlanId=3900, vlanName="X", accessPorts="Gi9/9/9"),
 "non trunk": dict(operation="create", vlanId=3900, vlanName="X", trunkPorts="Tw1/0/47"),
 "device": dict(operation="create", vlanId=3900, vlanName="X", accessPorts="Gi1/0/39", device="LAB-C8000V-01"),
}
for k, v in cases.items():
    r = plan(**v); print("%-15s valid=%s  %s" % (k, r["valid"], r["reasons"])); assert not r["valid"]
# modify with an existing vlan + trunk port configured
trunk_cfg = "Building configuration...\n!\ninterface TwoGigabitEthernet1/0/47\n switchport trunk allowed vlan 1,10\n switchport mode trunk\nend\n"
vl = fx["show vlan brief"] + "\n3900 DEMO_ITENTIAL_3900               active    Gi1/0/39"
m = plan(operation="modify", vlanId=3900, vlanName="DEMO_ITENTIAL_3900_B", accessPorts="Gi1/0/38", trunkPorts="Tw1/0/47",
         override={"show vlan brief": vl, "show running-config interface TwoGigabitEthernet1/0/47": trunk_cfg})
print("modify valid:", m["valid"], m["reasons"]); print("\n".join(m["configLines"])); print("--rb\n" + "\n".join(m["rollbackLines"]))
assert m["valid"]
# verify: simulate post state after create
post_vl = fx["show vlan brief"] + "\n3900 DEMO_ITENTIAL_3900               active    Gi1/0/39"
post_p = "interface GigabitEthernet1/0/39\n description \"Test\"\n switchport access vlan 3900\n switchport mode access\n shutdown\nend"
jd, _ = collect("LAB-C8300-SW01", "Gi1/0/39", "", {"show vlan brief": post_vl, "show running-config interface GigabitEthernet1/0/39": post_p})
push = {"result": {"results": [{"name": "LAB-C8300-SW01", "success": True, "output": "ok"}]}}
v = run({"mode": "verify", "plan": {"stdout_json": ok}, "phase": "deploy", "collect": jd, "push": push})
print("verify deploy:", v["passed"], [c["check"] + ":" + str(c["pass"]) for c in v["checks"]]); assert v["passed"]
jd0, _ = collect("LAB-C8300-SW01", "Gi1/0/39", "")
v2 = run({"mode": "verify", "plan": {"stdout_json": ok}, "phase": "rollback", "collect": jd0, "push": push})
print("verify rollback on baseline:", v2["passed"], [c["check"] + ":" + str(c["pass"]) for c in v2["checks"]]); assert v2["passed"]
v3 = run({"mode": "verify", "plan": {"stdout_json": ok}, "phase": "deploy", "collect": jd0, "push": push})
print("verify deploy on baseline (should fail):", v3["passed"]); assert not v3["passed"]
mv = run({"mode": "verify", "plan": {"stdout_json": m}, "phase": "deploy", "collect": jd0, "push": push})
cr = run({"mode": "crprep", "plan": {"stdout_json": ok}, "cr": {"body": {"result": {"number": {"value": "CHG1"}, "sys_id": {"value": "abc"}}}}})
print("crprep:", cr["number"], cr["sysId"], cr["baselineBody"]["work_notes"][:200])
rep = run({"mode": "report", "plan": {"stdout_json": ok}, "crprep": {"stdout_json": cr}, "deploy": {"stdout_json": v}, "rollback": "none", "save": push})
print(rep["status"], rep["closeBody"]); print(rep["reviewBody"]["work_notes"])
ap = run({"mode": "applied", "jd": {"variables": {"verifyResult": {"stdout_json": v}}}}); assert ap["passedStr"] == "true"
print("ALL OK")
