import sys, json, re, html, datetime

data = json.load(sys.stdin)
mode = data.get("mode")

# Devices this automation may change, and how to reach them.
ALLOW = {"LAB-C8300-SW01": {"clusterId": "lab_gateway_cluster", "inventory": "lab-inventory"}}
NAME_RE = r"^[A-Z0-9_-]{1,32}$"
PREFIX = {"gi": "GigabitEthernet", "tw": "TwoGigabitEthernet", "te": "TenGigabitEthernet",
          "fa": "FastEthernet", "fo": "FortyGigabitEthernet", "hu": "HundredGigE", "twe": "TwentyFiveGigE"}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def split(s):
    if isinstance(s, list):
        return [str(p).strip() for p in s if str(p).strip()]
    return [p.strip() for p in re.split(r"[\s,;]+", s or "") if p.strip()]


def full_port(p):
    m = re.match(r"^([A-Za-z-]+)\s*([\d/.:]+)$", p.strip())
    if not m:
        return p.strip()
    pre, num = m.group(1), m.group(2)
    low = pre.lower()
    for k in sorted(PREFIX, key=len, reverse=True):
        if low == k or PREFIX[k].lower() == low:
            return PREFIX[k] + num
    return pre + num


def short_port(p):
    for k, v in PREFIX.items():
        if p.startswith(v):
            return k.capitalize() + p[len(v):]
    return p


def find(obj, key):
    """First value stored under `key` anywhere inside obj (childJob job_details are nested)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find(v, key)
            if r is not None:
                return r
    return None


def stdout_json(res):
    """runCode result (or something holding one) -> its stdout_json."""
    if isinstance(res, dict):
        if "stdout_json" in res:
            return res.get("stdout_json") or {}
        if isinstance(res.get("stdout"), str):
            try:
                return json.loads(res["stdout"])
            except Exception:
                return {}
        for k in ("result",):
            if k in res:
                return stdout_json(res[k])
    return {}


def outputs(res):
    # sendCommand result is {"result": {"results": [{"command", "output", ...}]}}; tolerate unwrapped forms
    if isinstance(res, list):
        flat = []
        for r in res:
            flat.extend([r] if isinstance(r, dict) and "output" in r else outputs(r))
        return flat
    if isinstance(res, dict):
        if "output" in res:
            return [res]
        for k in ("result", "results"):
            if k in res:
                return outputs(res[k])
    return []


def expand(spec):
    """'1,10,20-22' -> {1,10,20,21,22}; 'ALL' -> None (everything)."""
    spec = (spec or "").strip()
    if not spec or spec.upper() == "ALL":
        return None
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part or part.lower() == "none":
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def device_target(device):
    t = ALLOW.get(device)
    if not t:
        return None
    return {"clusterId": t["clusterId"], "inventory": [{"inventory": t["inventory"], "nodeNames": [device]}]}


# ---------------------------------------------------------------- parsing
def parse_vlans(text):
    vlans = {}
    for line in (text or "").splitlines():
        m = re.match(r"^(\d+)\s+(\S+)\s+(\S+)\s*(.*)$", line)
        if m:
            ports = [p.strip() for p in m.group(4).split(",") if p.strip()]
            vlans[m.group(1)] = {"name": m.group(2), "status": m.group(3), "ports": ports}
        elif vlans and re.match(r"^\s{20,}\S", line):
            last = list(vlans)[-1]
            vlans[last]["ports"] += [p.strip() for p in line.split(",") if p.strip()]
    return vlans


def parse_port(text):
    if not text or "Invalid input" in text or "interface" not in text:
        return {"exists": False}
    lines = [l.strip() for l in text.splitlines()]
    mode_ = None
    access = None
    allowed = None
    for l in lines:
        if l.startswith("switchport mode "):
            mode_ = l.split()[-1]
        elif l.startswith("switchport access vlan "):
            access = l.split()[-1]
        elif l.startswith("switchport trunk allowed vlan "):
            v = l[len("switchport trunk allowed vlan "):]
            if v.startswith("add "):
                allowed = (allowed + "," if allowed else "") + v[4:]
            else:
                allowed = v
    no_sw = any(l == "no switchport" for l in lines)
    return {"exists": True, "switchport": not no_sw, "mode": mode_, "accessVlan": access,
            "trunkAllowed": allowed if mode_ == "trunk" else None,
            "shutdown": "shutdown" in lines,
            "config": [l for l in lines if l and not l.startswith(("Building", "Current configuration", "!", "end"))]}


def build_state(raw, ports):
    outs = outputs(raw)
    by_cmd = {o.get("command", ""): o.get("output", "") for o in outs}
    state = {"vlans": parse_vlans(by_cmd.get("show vlan brief", "")),
             "trunkSummary": by_cmd.get("show interfaces trunk", "").strip(), "ports": {}}
    for p in ports:
        state["ports"][p] = parse_port(by_cmd.get("show running-config interface " + p, ""))
    state["collectedAt"] = now()
    return state


def collected_state(jd):
    """State from a 'VLAN - Collect State' childJob's job_details."""
    return stdout_json(find(jd, "stateResult")).get("state") or {}


# ---------------------------------------------------------------- plan
def make_plan(d):
    op = (d.get("operation") or "").strip().lower()
    device = (d.get("device") or "").strip()
    name = (d.get("vlanName") or "").strip()
    access = [full_port(p) for p in split(d.get("accessPorts"))]
    trunk = [full_port(p) for p in split(d.get("trunkPorts"))]
    just = (d.get("justification") or "").strip()
    state = collected_state(d.get("collect"))
    reasons = []
    try:
        vid = int(str(d.get("vlanId")).strip())
    except Exception:
        vid = None
    if op not in ("create", "modify"):
        reasons.append("Operation must be 'create' or 'modify' (got '%s')." % op)
    if vid is None or not (2 <= vid <= 1001 or 1006 <= vid <= 4094):
        reasons.append("VLAN ID must be 2-1001 or 1006-4094 (got '%s')." % d.get("vlanId"))
    if op == "create" and not re.match(NAME_RE, name):
        reasons.append("VLAN name '%s' must be 1-32 characters of A-Z, 0-9, '_' or '-'." % name)
    if op == "modify" and name and not re.match(NAME_RE, name):
        reasons.append("VLAN name '%s' must be 1-32 characters of A-Z, 0-9, '_' or '-'." % name)
    if device not in ALLOW:
        reasons.append("Device '%s' is not on the allow-list (%s)." % (device, ", ".join(ALLOW)))
    if not access and not trunk and not (op == "modify" and name):
        reasons.append("Nothing to do: give access ports, trunk ports, or (for modify) a new name.")
    if set(access) & set(trunk):
        reasons.append("A port cannot be both access and trunk: %s." % ", ".join(sorted(set(access) & set(trunk))))
    if not state.get("vlans") and device in ALLOW:
        reasons.append("Could not read the VLAN table from %s." % device)
    vlans = state.get("vlans") or {}
    existing = vlans.get(str(vid)) if vid is not None else None
    if state.get("vlans"):
        if op == "create" and existing:
            reasons.append("VLAN %s already exists on %s (name %s)." % (vid, device, existing["name"]))
        if op == "modify" and not existing:
            reasons.append("VLAN %s does not exist on %s, so it cannot be modified." % (vid, device))
    ports = state.get("ports") or {}
    for p in access + trunk:
        pst = ports.get(p) or {}
        if not pst.get("exists"):
            reasons.append("Port %s does not exist on %s." % (p, device))
        elif not pst.get("switchport", True):
            reasons.append("Port %s is a routed port (no switchport)." % p)
    for p in trunk:
        pst = ports.get(p) or {}
        if pst.get("exists") and pst.get("mode") != "trunk":
            reasons.append("Port %s is not a trunk (mode %s); this automation only adds VLANs to existing trunks." % (p, pst.get("mode") or "default"))
    for p in access:
        pst = ports.get(p) or {}
        if pst.get("exists") and pst.get("mode") == "trunk":
            reasons.append("Port %s is a trunk; it cannot be made an access port by this automation." % p)

    valid = not reasons
    target = device_target(device) or {}
    old_name = existing["name"] if existing else None
    new_name = name or old_name

    # change lines
    cfg = []
    if op == "create" or (op == "modify" and name and name != old_name):
        cfg += ["vlan %s" % vid, " name %s" % new_name, "exit"]
    for p in access:
        cfg += ["interface %s" % p, " switchport mode access", " switchport access vlan %s" % vid, "exit"]
    for p in trunk:
        cfg += ["interface %s" % p, " switchport trunk allowed vlan add %s" % vid, "exit"]

    # rollback lines (restore the baseline for every touched item)
    rb = []
    for p in access:
        b = ports.get(p) or {}
        rb += ["interface %s" % p]
        rb += [" switchport access vlan %s" % b["accessVlan"]] if b.get("accessVlan") else [" no switchport access vlan"]
        if b.get("mode") != "access":
            rb += [" no switchport mode access"] if not b.get("mode") else [" switchport mode %s" % b["mode"]]
        rb += ["exit"]
    for p in trunk:
        b = ports.get(p) or {}
        allowed = expand(b.get("trunkAllowed"))
        if allowed is not None and vid not in allowed:
            rb += ["interface %s" % p, " switchport trunk allowed vlan remove %s" % vid, "exit"]
    if op == "create":
        rb += ["no vlan %s" % vid]
    elif name and name != old_name:
        rb += ["vlan %s" % vid, " name %s" % old_name, "exit"]

    expect = {"vlanId": str(vid), "vlanPresent": True, "vlanName": new_name,
              "access": {p: str(vid) for p in access},
              "trunk": {p: {"must": vid, "keep": (ports.get(p) or {}).get("trunkAllowed")} for p in trunk}}
    base_expect = {"vlanId": str(vid), "vlanPresent": op != "create", "vlanName": old_name,
                   "access": {p: (ports.get(p) or {}).get("accessVlan") or "1" for p in access},
                   "accessMode": {p: (ports.get(p) or {}).get("mode") for p in access},
                   "trunk": {p: {"exact": (ports.get(p) or {}).get("trunkAllowed")} for p in trunk}}

    summary = "VLAN %s %s on %s" % (vid, op, device)
    impl = "\n".join(cfg) + "\nwrite memory"
    cr_body = {
        "type": "standard",
        "short_description": summary + (" (%s)" % new_name if new_name else ""),
        "description": ("Itential 'VLAN Provisioning' request.\nOperation: %s\nVLAN: %s %s\nDevice: %s\n"
                        "Access ports: %s\nTrunk ports: %s\nJustification: %s")
                       % (op, vid, new_name, device, ", ".join(access) or "-", ", ".join(trunk) or "-", just),
        "justification": just,
        "implementation_plan": "Push to %s via Itential after approval:\n%s" % (device, impl),
        "backout_plan": "Itential restores the captured baseline automatically if post-checks fail:\n%s" % "\n".join(rb),
        "test_plan": ("Post-check by Itential: VLAN %s present as %s in 'show vlan brief'; access ports in VLAN %s; "
                      "trunk ports carry VLAN %s and keep every VLAN allowed before the change.") % (vid, new_name, vid, vid),
        "category": "Network", "risk": "low", "impact": "3", "priority": "4",
        "cmdb_ci": device,
    }
    reject = {"status": "rejected", "reasons": reasons,
              "message": "Request rejected before any change: " + " ".join(reasons) +
                         " No change request was opened and no configuration was pushed."}
    return {
        "valid": valid, "validStr": "true" if valid else "false", "reasons": reasons, "rejectReport": reject,
        "operation": op, "vlanId": vid, "vlanName": new_name, "oldVlanName": old_name, "device": device,
        "accessPorts": access, "trunkPorts": trunk, "ports": access + trunk, "justification": just,
        "clusterId": target.get("clusterId"), "inventory": target.get("inventory"),
        "configLines": cfg, "rollbackLines": rb, "saveCommands": ["write memory"], "expect": expect, "baselineExpect": base_expect,
        "baseline": state, "crBody": cr_body, "summary": summary,
    }


def plan_of(obj):
    p = stdout_json(obj)
    return p if p.get("configLines") is not None else (find(obj, "plan") or {})


def cr_fields(resp):
    body = resp.get("body", resp) if isinstance(resp, dict) else {}
    rec = body.get("result", body) if isinstance(body, dict) else {}

    def val(f):
        v = rec.get(f) if isinstance(rec, dict) else None
        if isinstance(v, dict):
            return v.get("value") if v.get("value") not in (None, "") else v.get("display_value")
        return v
    return val("number"), val("sys_id")


def baseline_note(plan):
    b = plan.get("baseline") or {}
    v = b.get("vlans", {}).get(str(plan.get("vlanId")))
    lines = ["Baseline captured by Itential at %s UTC on %s:" % (b.get("collectedAt"), plan.get("device")),
             "VLAN %s: %s" % (plan.get("vlanId"), ("present, name %s" % v["name"]) if v else "not present")]
    for p in plan.get("ports", []):
        s = (b.get("ports") or {}).get(p) or {}
        lines.append("%s: mode %s, access VLAN %s, trunk allowed %s%s" % (
            p, s.get("mode") or "default", s.get("accessVlan") or "1", s.get("trunkAllowed") or "-",
            ", shutdown" if s.get("shutdown") else ""))
    lines.append("Trunks on device: %s" % ("none" if not b.get("trunkSummary") else "see job output"))
    return "\n".join(lines)


def approval_html(plan, number):
    b = plan.get("baseline") or {}
    rows = "".join("<tr><td style='padding:3px 10px;color:#555'>%s</td><td style='padding:3px 10px'>%s</td></tr>" % (esc(k), esc(v)) for k, v in [
        ("Change request", number), ("Device", plan.get("device")), ("Operation", plan.get("operation")),
        ("VLAN", "%s %s" % (plan.get("vlanId"), plan.get("vlanName"))),
        ("Access ports", ", ".join(plan.get("accessPorts")) or "-"),
        ("Trunk ports", ", ".join(plan.get("trunkPorts")) or "-"),
        ("Justification", plan.get("justification")),
    ])
    prows = "".join("<tr><td style='padding:3px 10px'>%s</td><td style='padding:3px 10px'>%s</td><td style='padding:3px 10px'>%s</td><td style='padding:3px 10px'>%s</td></tr>" % (
        esc(p), esc(s.get("mode") or "default"), esc(s.get("accessVlan") or "1"), esc(s.get("trunkAllowed") or "-"))
        for p, s in ((p, (b.get("ports") or {}).get(p) or {}) for p in plan.get("ports", [])))
    return ("<div style='font-family:Arial,sans-serif;max-width:760px'>"
            "<h3 style='margin:0 0 8px'>Approve VLAN change %s?</h3><table>%s</table>"
            "<h4 style='margin:14px 0 4px'>Current state of the ports (baseline)</h4>"
            "<table style='border-collapse:collapse'><tr style='color:#555'><td style='padding:3px 10px'>Port</td><td style='padding:3px 10px'>Mode</td>"
            "<td style='padding:3px 10px'>Access VLAN</td><td style='padding:3px 10px'>Trunk allowed</td></tr>%s</table>"
            "<h4 style='margin:14px 0 4px'>Configuration to push</h4>"
            "<pre style='background:#f4f4f4;padding:10px;border-radius:4px'>%s</pre>"
            "<h4 style='margin:14px 0 4px'>Rollback if post-checks fail</h4>"
            "<pre style='background:#f4f4f4;padding:10px;border-radius:4px'>%s</pre>"
            "<p>APPROVE moves the change request to Implement and pushes the configuration. "
            "REJECT cancels the change request; nothing is pushed.</p></div>") % (
        esc(number), rows, prows, esc("\n".join(plan.get("configLines"))), esc("\n".join(plan.get("rollbackLines"))))


# ---------------------------------------------------------------- verify
def verify(state, exp):
    checks = []
    v = (state.get("vlans") or {}).get(exp.get("vlanId"))

    def add(name, ok, actual):
        checks.append({"check": name, "pass": bool(ok), "actual": actual})
    if exp.get("vlanPresent"):
        add("VLAN %s present" % exp["vlanId"], v is not None, "present" if v else "missing")
        if exp.get("vlanName"):
            add("VLAN %s named %s" % (exp["vlanId"], exp["vlanName"]), v and v["name"] == exp["vlanName"], v and v["name"])
    else:
        add("VLAN %s absent" % exp["vlanId"], v is None, "present" if v else "absent")
    ports = state.get("ports") or {}
    for p, want in (exp.get("access") or {}).items():
        s = ports.get(p) or {}
        got = s.get("accessVlan") or "1"
        add("%s access VLAN %s" % (p, want), got == str(want), got)
        if "accessMode" in exp:
            wm = (exp.get("accessMode") or {}).get(p)
            add("%s mode %s" % (p, wm or "default"), s.get("mode") == wm, s.get("mode") or "default")
        else:
            add("%s mode access" % p, s.get("mode") == "access", s.get("mode") or "default")
    for p, want in (exp.get("trunk") or {}).items():
        s = ports.get(p) or {}
        got = s.get("trunkAllowed")
        allowed = expand(got)
        if "exact" in want:
            add("%s trunk allowed restored" % p, (got or None) == (want["exact"] or None), got or "ALL")
            continue
        add("%s trunk carries VLAN %s" % (p, want["must"]), allowed is None or want["must"] in allowed, got or "ALL")
        before = expand(want.get("keep"))
        if before is not None:
            missing = sorted(before - (allowed or before))
            add("%s trunk kept previous VLANs" % p, not missing, "missing %s" % missing if missing else "all kept")
    return {"passed": all(c["pass"] for c in checks) and bool(checks), "checks": checks}


def push_ok(res):
    nodes = find(res, "results") or []
    if not isinstance(nodes, list) or not nodes:
        return False, "no per-node result"
    bad = [n for n in nodes if isinstance(n, dict) and not n.get("success")]
    out = " | ".join(str(n.get("output", ""))[-400:] for n in nodes if isinstance(n, dict))
    return not bad, out


# ---------------------------------------------------------------- modes
if mode == "cmds":
    device = (data.get("device") or "").strip()
    ports = [full_port(p) for p in split(data.get("accessPorts")) + split(data.get("trunkPorts"))]
    t = device_target(device)
    print(json.dumps({"known": t is not None, "knownStr": "true" if t else "false", "ports": ports,
                      "clusterId": (t or {}).get("clusterId"), "inventory": (t or {}).get("inventory"),
                      "commands": ["show vlan brief", "show interfaces trunk"] +
                                  ["show running-config interface " + p for p in ports]}))

elif mode == "parse":
    cmds = stdout_json(data.get("cmds"))
    print(json.dumps({"state": build_state(data.get("raw"), cmds.get("ports") or [])}))

elif mode == "plan":
    print(json.dumps(make_plan(data)))

elif mode == "crprep":
    plan = plan_of(data.get("plan"))
    number, sys_id = cr_fields(data.get("cr") or {})
    print(json.dumps({
        "number": number, "sysId": sys_id, "html": approval_html(plan, number),
        "baselineBody": {"work_notes": baseline_note(plan)},
        "scheduleBody": {"state": -2, "work_notes": "Approved in Itential Work Center (VLAN Provisioning) %s UTC. Scheduled for immediate implementation." % now()},
        "implementBody": {"state": -1, "work_notes": "Implementation started by Itential %s UTC: pushing configuration to %s." % (now(), plan.get("device"))},
        "cancelBody": {"state": 4, "close_code": "Unsuccessful",
                       "close_notes": "Change rejected by the approver in Itential Work Center. Nothing was pushed to %s." % plan.get("device"),
                       "work_notes": "Rejected in Itential Work Center %s UTC; change canceled." % now()},
    }))

elif mode == "cfg":
    plan = plan_of(data.get("plan"))
    lines = plan.get("rollbackLines") if data.get("phase") == "rollback" else plan.get("configLines")
    print(json.dumps({"config": "\n".join(lines or []), "lines": lines or [],
                      "clusterId": plan.get("clusterId"), "inventory": plan.get("inventory"),
                      "accessPorts": ",".join(plan.get("accessPorts") or []),
                      "trunkPorts": ",".join(plan.get("trunkPorts") or [])}))

elif mode == "verify":
    plan = plan_of(data.get("plan"))
    phase = data.get("phase") or "deploy"
    exp = plan.get("baselineExpect") if phase == "rollback" else plan.get("expect")
    ok, out = push_ok(data.get("push"))
    state = collected_state(data.get("collect"))
    v = verify(state, exp or {})
    passed = ok and v["passed"]
    print(json.dumps({"phase": phase, "passed": passed, "passedStr": "true" if passed else "false",
                      "pushOk": ok, "pushOutput": out, "checks": v["checks"], "post": state,
                      "lines": plan.get("rollbackLines") if phase == "rollback" else plan.get("configLines")}))

elif mode == "applied":
    r = stdout_json(find(data.get("jd"), "verifyResult"))
    if not r:
        r = {"passed": False, "checks": [], "pushOk": False, "pushOutput": "apply child did not finish",
             "phase": data.get("phase")}
    r["passedStr"] = "true" if r.get("passed") else "false"
    print(json.dumps(r))

elif mode == "report":
    plan = plan_of(data.get("plan"))
    cr = stdout_json(data.get("crprep"))
    dep = stdout_json(data.get("deploy"))
    rb = stdout_json(data.get("rollback")) if isinstance(data.get("rollback"), dict) else {}
    saved = bool(outputs(data.get("save")))
    if dep.get("passed"):
        outcome, code = "successful", "Successful"
    elif rb.get("passed"):
        outcome, code = "rolled_back", "Successful with issues"
    else:
        outcome, code = "failed_manual_attention", "Unsuccessful"
    def lines_of(r):
        return "\n".join("  [%s] %s (actual: %s)" % ("PASS" if c["pass"] else "FAIL", c["check"], c["actual"]) for c in r.get("checks", []))
    text = ["Itential VLAN Provisioning evidence - %s UTC" % now(),
            "Change request: %s" % cr.get("number"),
            "Request: %s; VLAN %s name %s; access %s; trunk %s" % (plan.get("operation"), plan.get("vlanId"), plan.get("vlanName"),
                                                                  ", ".join(plan.get("accessPorts", [])) or "-", ", ".join(plan.get("trunkPorts", [])) or "-"),
            "Approval: approved in Itential Work Center",
            "Configuration pushed to %s:" % plan.get("device")] + ["  " + l for l in plan.get("configLines", [])] + [
            "Push result: %s" % ("ok" if dep.get("pushOk") else "FAILED"),
            "Post-checks:", lines_of(dep) or "  none"]
    if rb:
        text += ["Rollback pushed:"] + ["  " + l for l in plan.get("rollbackLines", [])] + ["Rollback checks:", lines_of(rb) or "  none"]
    text += ["Config saved (write memory): %s" % ("yes" if dep.get("passed") and saved else "no"),
             "Outcome: %s" % outcome]
    note = "\n".join(text)
    report = {"status": outcome, "changeRequest": cr.get("number"), "device": plan.get("device"),
              "operation": plan.get("operation"), "vlanId": plan.get("vlanId"), "vlanName": plan.get("vlanName"),
              "configPushed": plan.get("configLines"), "deployChecks": dep.get("checks"),
              "rollbackPushed": plan.get("rollbackLines") if rb else None, "rollbackChecks": rb.get("checks") if rb else None,
              "baseline": plan.get("baseline"), "post": dep.get("post"), "evidence": note}
    print(json.dumps({"status": outcome, "report": report,
                      "reviewBody": {"state": 0, "work_notes": note},
                      "closeBody": {"state": 3, "close_code": code,
                                    "close_notes": "Automated close-out by Itential VLAN Provisioning: %s. %s" % (
                                        outcome.replace("_", " "),
                                        "Device needs manual attention." if outcome == "failed_manual_attention" else "")}}))
else:
    print(json.dumps({"error": "unknown mode %s" % mode}))
