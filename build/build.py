#!/usr/bin/env python3
"""Build the 'VLAN Provisioning (Deterministic)' project: 3 workflows -> project-import.json."""
import json, os, re, sys, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from api import call

CODE = (HERE / "vlan.py").read_text()
ids_path = HERE / "ids.json"
IDS = json.loads(ids_path.read_text()) if ids_path.exists() else {}
PID = IDS.setdefault("projectId", os.urandom(12).hex())
WF_COLLECT, WF_APPLY, WF_MAIN = "VLAN - Collect State", "VLAN - Apply and Verify", "VLAN Provisioning"
for n in (WF_COLLECT, WF_APPLY, WF_MAIN):
    IDS.setdefault(n, str(uuid.uuid4()))
ids_path.write_text(json.dumps(IDS, indent=2))
PREFIX = f"@{PID}: "
RC_CLUSTER = "lab_gateway_cluster"   # where runCode executes
SNOW = "ServiceNow Change Management:latest"
SPINE, L, R = 600, 336, 864
y = lambda n: 100 + 108 * n


class WF:
    def __init__(self):
        self.tasks, self.tr = {}, {}

    def base(self, tid, name, summary, x, yy, app="WorkFlowEngine", typ="operation", disp=None, loc="Application",
             lt=None, actor="Pronghorn", canvas=None):
        t = {"name": name, "canvasName": canvas or name, "summary": summary, "description": summary, "location": loc,
             "locationType": lt, "app": app, "type": typ, "displayName": disp or app,
             "variables": {"incoming": {}, "outgoing": {}, "error": "", "decorators": []},
             "groups": [], "scheduled": False, "nodeLocation": {"x": x, "y": yy}}
        if actor:
            t["actor"] = actor
        self.tasks[tid] = t
        return t

    @staticmethod
    def q(t, field, ref, path):
        t["variables"]["incoming"][field] = f"{ref}#/{path}"
        t["variables"]["decorators"].append({"type": "query", "pointer": f"/incoming/{field}",
                                             "displayPath": "." + path.replace("/", ".")})

    def runcode(self, tid, summary, mode, data, x, yy, out_var=None):
        t = self.base(tid, "runCode", summary, x, yy, app="GatewayManager", typ="automatic")
        d = {"mode": mode}
        d.update(data)
        t["variables"]["incoming"] = {"clusterId": RC_CLUSTER, "language": "python", "code": CODE, "data": d,
                                      "safety": {"timeout": 120}, "packages": []}
        t["variables"]["outgoing"] = {"result": f"$var.job.{out_var}" if out_var else None}

    def send_command(self, tid, summary, src, cmd_path, x, yy, out_var=None):
        t = self.base(tid, "sendCommand", summary, x, yy, app="GatewayManager", typ="automatic")
        self.q(t, "clusterId", src, "stdout_json/clusterId")
        self.q(t, "commands", src, cmd_path)
        self.q(t, "inventory", src, "stdout_json/inventory")
        t["variables"]["outgoing"] = {"result": f"$var.job.{out_var}" if out_var else None}

    def send_config(self, tid, summary, src, x, yy, out_var=None):
        t = self.base(tid, "sendConfig", summary, x, yy, app="GatewayManager", typ="automatic")
        self.q(t, "clusterId", src, "stdout_json/clusterId")
        self.q(t, "config", src, "stdout_json/config")
        self.q(t, "inventory", src, "stdout_json/inventory")
        t["variables"]["outgoing"] = {"result": f"$var.job.{out_var}" if out_var else None}

    def snow(self, tid, method, summary, x, yy, body_src, body_path, sys_src=None, out_var=None):
        t = self.base(tid, method, summary, x, yy, app=SNOW, typ="automatic", disp="ServiceNow", loc="Adapter", lt=SNOW)
        t["variables"]["incoming"] = {"bodyContentType": "application/json", "adapter_id": "ServiceNow"}
        self.q(t, "requestBodyPayload", body_src, body_path)
        if sys_src:
            self.q(t, "sys_id", sys_src, "stdout_json/sysId")
        t["variables"]["outgoing"] = {"response": f"$var.job.{out_var}" if out_var else None}

    def new_var(self, tid, summary, name, value, x, yy):
        t = self.base(tid, "newVariable", summary, x, yy)
        t["variables"]["incoming"] = {"name": name, "value": value}
        t["variables"]["outgoing"] = {"value": f"$var.job.{name}"}

    def query(self, tid, summary, obj, path, x, yy, out_var=None):
        t = self.base(tid, "query", summary, x, yy)
        t["variables"]["incoming"] = {"pass_on_null": False, "query": path, "obj": obj}
        t["variables"]["outgoing"] = {"return_data": f"$var.job.{out_var}" if out_var else None}

    def is_true(self, tid, summary, src, const, x, yy):
        t = self.base(tid, "evaluation", summary, x, yy)
        t["variables"]["incoming"] = {"all_true_flag": True, "evaluation_groups": [{"all_true_flag": True, "evaluations": [
            {"operand_1": {"task": src, "variable": "return_data"}, "operator": "==",
             "operand_2": {"task": const, "variable": "value"}}]}], "options": ""}
        t["variables"]["outgoing"] = {"return_value": None}

    def approval(self, tid, summary, header, src, path, ok, no, x, yy):
        t = self.base(tid, "InteractiveHTML", summary, x, yy, app="WorkCenter", typ="manual", disp="Work Center",
                      actor=None, canvas="Interactive HTML")
        t["view"] = "/work-center/task/InteractiveHTML"
        t["variables"]["incoming"] = {"header": header, "variables": {}, "btn_success": ok, "btn_failure": no}
        self.q(t, "body", src, path)
        t["variables"]["outgoing"] = {"export": None}

    def child(self, tid, summary, wf_name, variables, x, yy):
        t = self.base(tid, "childJob", summary, x, yy, actor="job")
        t["variables"]["incoming"] = {"task": "", "workflow": PREFIX + wf_name, "variables": variables,
                                      "data_array": "", "transformation": "", "loopType": ""}
        t["variables"]["outgoing"] = {"job_details": None}

    def go(self, src, dst, state="success"):
        assert dst not in self.tr.setdefault(src, {}), (src, dst)
        self.tr[src][dst] = {"type": "standard", "state": state}

    def doc(self, name, description, inputs, required, outputs, end_y):
        tasks = {"workflow_start": {"name": "workflow_start", "groups": [], "nodeLocation": {"x": SPINE, "y": y(0)}},
                 **self.tasks,
                 "workflow_end": {"name": "workflow_end", "groups": [], "nodeLocation": {"x": SPINE, "y": end_y}}}
        tr = dict(self.tr)
        tr["workflow_end"] = {}
        bad = [k for k in tasks if k not in ("workflow_start", "workflow_end") and not re.fullmatch(r"[0-9a-f]{1,4}", k)]
        assert not bad, bad
        for src, dsts in tr.items():
            for d in dsts:
                assert d in tasks, (src, d)
        return {"name": name, "description": description, "type": "automation", "canvasVersion": 3, "font_size": 12,
                "tasks": tasks, "transitions": tr, "groups": [], "scenarios": [], "errors": [], "warnings": [],
                "inputSchema": {"type": "object", "properties": inputs, "required": required},
                "outputSchema": {"type": "object", "properties": outputs}, "tags": []}


def S(t="string"):
    return {"type": t}


# ------------------------------------------------------------------ Collect State
def collect_wf():
    w = WF()
    job = {"device": "$var.job.device", "accessPorts": "$var.job.accessPorts", "trunkPorts": "$var.job.trunkPorts"}
    w.runcode("1001", "Build show commands", "cmds", job, SPINE, y(1), out_var="cmdsResult")
    w.send_command("1002", "Read VLANs, trunks and ports", "$var.1001.result", "stdout_json/commands", SPINE, y(2))
    w.runcode("1003", "Parse device state", "parse", {"cmds": "$var.1001.result", "raw": "$var.1002.result"},
              SPINE, y(3), out_var="stateResult")
    w.new_var("1004", "Set status collected", "status", "collected", SPINE, y(4))
    w.new_var("10f0", "Set status error", "status", "error", R, y(4))
    w.go("workflow_start", "1001")
    for a, b in (("1001", "1002"), ("1002", "1003"), ("1003", "1004")):
        w.go(a, b)
        w.go(a, "10f0", "error")
    w.go("1004", "workflow_end")
    w.go("10f0", "workflow_end")
    return w.doc(WF_COLLECT, "Read show vlan brief, show interfaces trunk and each port's running config from one device and parse them into a state object (stateResult).",
                 {"device": S(), "accessPorts": S(), "trunkPorts": S()}, ["device", "accessPorts", "trunkPorts"],
                 {"stateResult": S("object"), "status": S()}, y(5))


# ------------------------------------------------------------------ Apply and Verify
def apply_wf():
    w = WF()
    w.runcode("2001", "Build config for this phase", "cfg", {"plan": "$var.job.plan", "phase": "$var.job.phase"},
              SPINE, y(1), out_var="cfgResult")
    w.send_config("2002", "Push configuration", "$var.2001.result", SPINE, y(2), out_var="pushResult")
    w.child("2003", "Read device state after push", WF_COLLECT,
            {"device": {"task": "job", "value": "device"}, "accessPorts": {"task": "job", "value": "accessPorts"},
             "trunkPorts": {"task": "job", "value": "trunkPorts"}}, SPINE, y(3))
    w.runcode("2004", "Verify against expected state", "verify",
              {"plan": "$var.job.plan", "phase": "$var.job.phase", "collect": "$var.2003.job_details",
               "push": "$var.2002.result"}, SPINE, y(4), out_var="verifyResult")
    w.new_var("2005", "Set status verified", "status", "verified", SPINE, y(5))
    w.new_var("20f0", "Set status error", "status", "error", R, y(5))
    w.go("workflow_start", "2001")
    for a, b in (("2001", "2002"), ("2002", "2003"), ("2003", "2004"), ("2004", "2005")):
        w.go(a, b)
        w.go(a, "20f0", "error")
    w.go("2005", "workflow_end")
    w.go("20f0", "workflow_end")
    return w.doc(WF_APPLY, "Push the plan's deploy or rollback lines to the device, read the state back and check it against the expected state (verifyResult).",
                 {"device": S(), "accessPorts": S(), "trunkPorts": S(), "plan": S("object"), "phase": S()},
                 ["device", "accessPorts", "trunkPorts", "plan", "phase"],
                 {"verifyResult": S("object"), "status": S()}, y(6))


# ------------------------------------------------------------------ Orchestrator
def main_wf():
    w = WF()
    P = "$var.a002.result"
    C = "$var.a006.result"
    J = lambda v: {"task": "job", "value": v}
    w.new_var("a000", "Constant true", "trueStr", "true", SPINE, y(1))
    w.new_var("a020", "Init deployCheck", "deployCheck", "none", SPINE, y(2))
    w.new_var("a021", "Init rollbackCheck", "rollbackCheck", "none", SPINE, y(3))
    w.new_var("a022", "Init saveResult", "saveResult", "none", SPINE, y(4))
    w.child("a001", "Capture baseline", WF_COLLECT,
            {"device": J("device"), "accessPorts": J("accessPorts"), "trunkPorts": J("trunkPorts")}, SPINE, y(5))
    w.runcode("a002", "Validate request and build plan", "plan",
              {"operation": "$var.job.operation", "vlanId": "$var.job.vlanId", "vlanName": "$var.job.vlanName",
               "device": "$var.job.device", "accessPorts": "$var.job.accessPorts", "trunkPorts": "$var.job.trunkPorts",
               "justification": "$var.job.justification", "collect": "$var.a001.job_details"},
              SPINE, y(6), out_var="plan")
    w.query("a003", "Is request valid", P, "stdout_json.validStr", SPINE, y(7))
    w.is_true("a004", "Valid?", "a003", "a000", SPINE, y(8))
    # rejected
    w.query("b001", "Rejection report", P, "stdout_json.rejectReport", R, y(9), out_var="report")
    w.new_var("b005", "Status rejected", "status", "rejected", R, y(10))
    # change request
    w.snow("a005", "createChangeRequest", "Open change request", L, y(9), P, "stdout_json/crBody", out_var="crCreate")
    w.runcode("a006", "Prepare change request updates and approval", "crprep",
              {"plan": P, "cr": "$var.a005.response"}, L, y(10), out_var="crPrep")
    w.snow("a007", "updateChangeRequest", "Add baseline work note to CR", L, y(11), C, "stdout_json/baselineBody", C)
    w.approval("a008", "Approve VLAN change", "Approve VLAN change", C, "stdout_json/html", "Approve", "Reject", L, y(12))
    w.snow("a00a", "updateChangeRequest", "Cancel change request", L - 264, y(13), C, "stdout_json/cancelBody", C)
    w.new_var("b002", "Status rejected by approver", "status", "rejected_by_approver", L - 264, y(14))
    w.snow("a009", "updateChangeRequest", "CR to Scheduled (approved)", L, y(13), C, "stdout_json/scheduleBody", C)
    w.snow("a025", "updateChangeRequest", "CR to Implement", L, y(13) + 54, C, "stdout_json/implementBody", C)
    # deploy
    w.child("a00b", "Push and verify", WF_APPLY,
            {"device": J("device"), "accessPorts": J("accessPorts"), "trunkPorts": J("trunkPorts"),
             "plan": {"task": "a002", "value": "result"}, "phase": {"task": "a000", "value": "value"}}, L, y(14))
    w.runcode("a00c", "Deploy result", "applied", {"jd": "$var.a00b.job_details"}, L, y(15), out_var="deployCheck")
    w.query("a00d", "Deploy passed", "$var.a00c.result", "stdout_json.passedStr", L, y(16))
    w.is_true("a00e", "Passed?", "a00d", "a000", L, y(17))
    w.send_command("a010", "Save config (write memory)", P, "stdout_json/saveCommands", L, y(18), out_var="saveResult")
    w.new_var("b003", "Save failed", "saveError", "write memory failed", L - 264, y(19))
    # rollback
    w.child("a011", "Roll back and verify", WF_APPLY,
            {"device": J("device"), "accessPorts": J("accessPorts"), "trunkPorts": J("trunkPorts"),
             "plan": {"task": "a002", "value": "result"}, "phase": {"task": "a023", "value": "value"}}, SPINE, y(18))
    w.new_var("a023", "Phase rollback", "rollbackPhase", "rollback", SPINE, y(17))
    w.new_var("b004", "Rollback child errored", "rollbackError", "rollback child job errored", SPINE + 264, y(19))
    w.runcode("a012", "Rollback result", "applied", {"jd": "$var.a011.job_details"}, SPINE, y(20), out_var="rollbackCheck")
    # close out
    w.runcode("a013", "Build evidence report", "report",
              {"plan": P, "crprep": C, "deploy": "$var.job.deployCheck", "rollback": "$var.job.rollbackCheck",
               "save": "$var.job.saveResult"}, L, y(21), out_var="reportResult")
    w.snow("a014", "updateChangeRequest", "CR to Review with evidence", L, y(22), "$var.a013.result", "stdout_json/reviewBody", C)
    w.snow("a015", "updateChangeRequest", "Close change request", L, y(23), "$var.a013.result", "stdout_json/closeBody", C)
    w.query("a016", "Final status", "$var.a013.result", "stdout_json.status", L, y(24), out_var="status")
    w.query("a017", "Final report", "$var.a013.result", "stdout_json.report", L, y(25), out_var="report")
    # failures
    w.new_var("f001", "Failed before change", "status", "failed_before_change", R + 264, y(9))
    w.new_var("f002", "Failed to open change request", "status", "failed_cr_create", R + 264, y(10))
    w.new_var("f003", "Failed to update change request", "status", "failed_cr_update", R + 264, y(12))
    w.new_var("f004", "Failed to move CR to Implement", "status", "failed_cr_implement", R + 264, y(14))
    w.new_var("f005", "Change done, CR close-out failed", "status", "completed_cr_update_failed", R + 264, y(23))

    g = w.go
    g("workflow_start", "a000"); g("a000", "a020"); g("a020", "a021"); g("a021", "a022"); g("a022", "a001")
    g("a001", "a002"); g("a001", "f001", "error")
    g("a002", "a003"); g("a002", "f001", "error")
    g("a003", "a004"); g("a003", "f001", "failure"); g("a003", "f002", "error")
    g("a004", "a005"); g("a004", "b001", "failure")
    g("b001", "b005"); g("b001", "f001", "failure"); g("b005", "workflow_end")
    g("a005", "a006"); g("a005", "f002", "error")
    g("a006", "a007"); g("a006", "f003", "error")
    g("a007", "a008"); g("a007", "f003", "error")
    g("a008", "a009"); g("a008", "a00a", "failure")
    g("a00a", "b002"); g("a00a", "f003", "error"); g("b002", "workflow_end")
    g("a009", "a025"); g("a009", "f004", "error")
    g("a025", "a00b"); g("a025", "f004", "error")
    g("a00b", "a00c"); g("a00b", "a023", "error")
    g("a00c", "a00d"); g("a00c", "a023", "error")
    g("a00d", "a00e"); g("a00d", "a023", "failure")
    g("a00e", "a010"); g("a00e", "a023", "failure")
    g("a010", "a013"); g("a010", "b003", "error"); g("b003", "a013")
    g("a023", "a011")
    g("a011", "a012"); g("a011", "b004", "error"); g("b004", "a012")
    g("a012", "a013")
    g("a013", "a014"); g("a013", "f005", "error")
    g("a014", "a015"); g("a014", "f005", "error")
    g("a015", "a016"); g("a015", "f005", "error")
    g("a016", "a017"); g("a017", "workflow_end")
    for f in ("f001", "f002", "f003", "f004", "f005"):
        g(f, "workflow_end")
    # deploy phase constant: the childJob needs "deploy"; reuse a dedicated newVariable
    w.new_var("a024", "Phase deploy", "deployPhase", "deploy", SPINE, y(5) - 54)
    w.tasks["a00b"]["variables"]["incoming"]["variables"]["phase"] = {"task": "a024", "value": "value"}
    w.tr["a022"] = {"a024": {"type": "standard", "state": "success"}}
    w.tr["a024"] = {"a001": {"type": "standard", "state": "success"}}
    inputs = {
        "operation": {"type": "string", "enum": ["create", "modify"]},
        "vlanId": {"type": "integer"},
        "vlanName": S(), "device": S(), "accessPorts": S(), "trunkPorts": S(), "justification": S(),
    }
    return w.doc(WF_MAIN, "Create or modify a VLAN on a lab IOS-XE device: validate, open a ServiceNow change request, approve in Work Center, push, verify, roll back on failure, report and close the change request.",
                 inputs, list(inputs), {"status": S(), "report": S("object"), "plan": S("object")}, y(27))


def component(i, wf):
    doc = dict(wf)
    for k in ("description", "errors", "warnings"):
        doc.pop(k, None)
    doc.update({"errorHandler": None, "preAutomationTime": 0, "sla": 0})
    sa = {"provenance": "Service Account", "username": "service-account", "firstname": "service-account",
          "inactive": False, "isServiceAccount": True}
    doc["created_by"], doc["last_updated_by"] = sa, sa
    u = IDS[wf["name"]]
    doc.update({"uuid": u, "created": "2026-10-15T00:00:00.000Z", "last_updated": "2026-10-15T00:00:00.000Z",
                "createdVersion": "6.5.0", "lastUpdatedVersion": "6.5.0", "migrationVersion": 1})
    return {"iid": i, "type": "workflow", "reference": u, "folder": "/", "document": doc}


if __name__ == "__main__":
    wfs = [collect_wf(), apply_wf(), main_wf()]
    ok = True
    for wf in wfs:
        code, res = call("POST", "/workflow_engine/workflows/validate", {"asset": wf})
        errs = [e for e in (res.get("errors") or []) if "decorators" not in json.dumps(e)] if isinstance(res, dict) else res
        print(f"{wf['name']}: HTTP {code} isValid={res.get('isValid') if isinstance(res, dict) else '?'} "
              f"errors(non-decorator)={json.dumps(errs)[:1500]} warnings={json.dumps(res.get('warnings'))[:1500] if isinstance(res, dict) else ''}")
        json.dump(wf, open(HERE / f"wf-{wf['name'].replace(' ', '').lower()}.json", "w"), indent=2)
    payload = {"project": {
        "_id": PID, "iid": 1, "name": "VLAN Provisioning (Deterministic)",
        "description": "Create or modify a VLAN on lab IOS-XE switches with a ServiceNow change request, Work Center approval, post-checks and automatic rollback.",
        "thumbnail": "", "backgroundColor": "#FFFFFF",
        "components": [component(i + 1, wf) for i, wf in enumerate(wfs)],
        "created": "2026-10-15T00:00:00.000Z",
        "createdBy": {"_id": "000000000000000000000000", "provenance": "Service Account", "username": "service-account"},
        "lastUpdated": "2026-10-15T00:00:00.000Z",
        "lastUpdatedBy": {"_id": "000000000000000000000000", "provenance": "Service Account", "username": "service-account"},
    }}
    json.dump(payload, open(HERE / "project-import.json", "w"), indent=2)
    print("project", PID, "-> project-import.json")
