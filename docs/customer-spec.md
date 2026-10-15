# Use Case: VLAN Provisioning

**Status:** Approved 2026-10-15 — locked for Feasibility
**Forked from:** `spec-vlan-provisioning.md` (generic)

## 1. Problem Statement

VLAN changes are the most common network change in enterprise environments. Engineers log into switches one by one, type commands, and hope they got the trunk list right. Mistakes cause outages — a trunk allowed-list that is replaced instead of appended drops every other VLAN on that link.

**Goal:** Let an operator create or modify a VLAN on Cisco IOS-XE lab devices from a single Itential form, with input validation, a pre-change baseline, human approval before any config is pushed, post-change verification, per-device rollback, and a ServiceNow change request that tracks the change from request to closure.

---

## 2. High-Level Flow

```
Form  →  Validate  →  Open CR  →  Pre-Check  →  Approval  →  Deploy  →  Post-Check  →  Close Out
  │          │           │            │            │            │            │              │
VLAN ID,  ID range,   ServiceNow  Reachable?   WorkCenter   CR → Implement, VLAN in table, Evidence
name,     lab-device  change      Capture      shows plan   push VLAN,   ports in VLAN,  attached to CR;
operation, allow-list, request    baseline;    + CR number; access,      trunks carry   CR → Review →
devices,  exists /    (Assess)    plan + pre-  Reject →     trunk add,   it             Closed (successful /
ports     not exists,             state as     CR Canceled  save config      │          unsuccessful)
          ports exist             work note                              FAIL? → Rollback that device
```

---

## 3. Phases

### Request Intake
Operator submits an Itential form: operation (`create` | `modify`), VLAN ID, VLAN name, target devices (from the lab inventory), access ports, trunk ports, and a short business justification. The automation opens the ServiceNow change request itself — the operator does not need an existing ticket.

### Validate Input
- VLAN ID is 2–1001 or 1006–4094 (not 1, not 1002–1005 reserved).
- VLAN name follows the naming rule (Section 4).
- Every target device is on the lab allow-list.
- Create: the VLAN does not already exist on any target. Modify: it exists on every target.
- Every listed port exists on its device.

Invalid requests are **rejected with a clear reason before any config change**. (Validation may run read-only `show` commands.) A rejected request does not open a change request — there is nothing to change.

### Open Change Request
Create a ServiceNow **normal change request** for the validated request: short description (`VLAN <id> <create|modify> on <n> device(s)`), description (full request), justification, implementation plan (per-device config lines), backout plan (restore baseline), test plan (post-check steps), affected CIs / devices, assignment group, planned start/end = now / now + window. State: **Assess**. Record the CR number — every later step references it.

### Pre-Check
Confirm each target device is reachable. Capture `show vlan brief`, `show interfaces trunk`, and the running config of each listed port as the baseline / rollback reference. If a device is unreachable, **drop it from the change and report it** — do not provision partially on that device. Add the baseline summary and any dropped devices to the CR as a work note.

### Approval
A WorkCenter task shows the CR number and, per device, the baseline summary and the exact config lines to be pushed. Approver approves or rejects.
- **Approve:** record the approver in a CR work note and move the CR to **Implement** (actual start = now).
- **Reject:** move the CR to **Canceled** with the rejection reason in the close notes; end with no changes.

### Deploy Configuration
Per device:
- **Create:** `vlan <id>` / `name <name>`; access ports `switchport mode access` + `switchport access vlan <id>`; trunk ports `switchport trunk allowed vlan add <id>` (**always `add`, never replace**).
- **Modify:** rename the VLAN and/or add ports to it (same additive trunk rule).
- Save the running config (`write memory`).
- Add a CR work note per device: config pushed and result.

### Post-Check
Per device: the VLAN is in `show vlan brief` with the requested name; access ports are in the VLAN; trunk ports list the VLAN in their allowed list; trunk VLANs present in the baseline are still present. No data-plane ping test.

### Rollback (conditional)
On any device that fails post-check, restore the baseline for the touched VLAN and ports, then re-verify. Record each rollback (and its result) as a CR work note. If rollback fails, mark the device **needs manual attention** in the report and in the CR.

### Close Out
Evidence report (job output, readable in the job view, and added to the CR as a work note): request, per-device config pushed, pre vs post state, approval decision and approver, failures and rollbacks.

Move the CR to **Review**, then **Closed** with actual end = now and a close code:
- **Successful** — every device passed post-check.
- **Successful with issues** — some devices rolled back or dropped, rollbacks verified.
- **Unsuccessful** — no device completed, or any rollback failed (CR close notes say which devices need manual attention).

The requestor sees the outcome in the job output and in the CR.

---

## 4. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Request source | Itential form / direct input | Operator starts from the form; the automation creates the ticket |
| ITSM record | One ServiceNow **normal change request** per request, created after validation and before pre-check | ITIL practice: every device change has a CR with plan, backout and test plan; invalid requests never create noise tickets |
| Change approval | Approval happens in Itential WorkCenter; the outcome is written to the CR (approver + decision) and drives the CR state | Keeps one approval point; ServiceNow CAB approval can replace it later without changing the rest of the flow |
| CR updates | Work notes at each stage (baseline, approval, per-device push, rollback, evidence); state transitions Assess → Implement → Review → Closed, or → Canceled on reject | Full audit trail in the system of record |
| CR closure | Close code reflects the real outcome (successful / successful with issues / unsuccessful) | Honest change records; failed changes are visible in ITSM reporting |
| Operations | Create and Modify only | Delete is out of scope for now |
| Human approval | WorkCenter approval before any push | Matches the other deterministic projects; people stay in control |
| Device scope | Lab allow-list only | Prevents accidental changes to production gear |
| Trunk updates | `switchport trunk allowed vlan add` only | Never overwrite existing allowed VLANs |
| Validation before change | Reject early | No partial deployments from bad input |
| Rollback granularity | Per device | A working VLAN on the good devices is kept |
| Config save | After each device's post-check passes | Persist only verified changes |
| VLAN naming rule (default — adjust if needed) | Uppercase letters, digits, `_` and `-`, max 32 chars, e.g. `MGMT_SITE1_110` | IOS-XE name limit is 32 chars; predictable names |
| Execution | Parallel per device, tracked individually | Lab sizes are small; per-device results are clear |

---

## 5. Scope

**In scope:** VLAN create and modify on Cisco IOS-XE lab devices. Access port assignment. Additive trunk allowed-list update. Input validation. Pre-check baseline. WorkCenter approval. Post-check. Per-device rollback. Evidence report in job output. ServiceNow change request: create, work-note updates, state transitions, closure.

**Out of scope:** VLAN delete. NX-OS, EOS, Junos. Production devices. ServiceNow incidents, CMDB updates and CAB approval in ServiceNow. Nautobot / IPAM lookups or updates. SVI / Layer 3 interfaces. Spanning tree, VTP/GVRP, QoS. Data-plane reachability tests. VLAN design or IP planning.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Lab IOS-XE devices are routers** (LAB-C8300-SW01 is a Catalyst 8300; LAB-C8000V-01 is a Catalyst 8000V) and may not support the VLAN database or `switchport` | Use case may not be testable as written | **Feasibility must confirm** with `show vlan brief` on each device. If unsupported: add a switch-capable IOS-XE device, or re-scope to dot1Q subinterfaces |
| VLAN ID conflict | Overwrite of an existing VLAN | Create checks the VLAN does not exist |
| Trunk allowed-list replaced | Other VLANs dropped | `add` keyword only; post-check confirms baseline VLANs still present |
| Port moved into wrong VLAN | Traffic on wrong segment | Post-check verifies each port; approver sees the exact lines |
| Device unreachable mid-change | Inconsistent state | Pre-check reachability; per-device tracking and rollback |
| Approval left pending | Job waits indefinitely; CR stuck in Assess | Approval task shows request details; operator can cancel the job (CR then moved to Canceled manually) |
| ServiceNow unreachable or CR create fails | No audit record | Stop before any device change — no change without a CR. Later update failures are reported but do not trigger device rollback |
| CR state model differs per instance (state values, mandatory fields) | Transition calls rejected | Feasibility confirms the instance's change states, mandatory fields and assignment group |

---

## 7. Requirements

### What the platform must be able to do

| Capability | Required | If Not Available |
|-----------|----------|------------------|
| Run show commands on IOS-XE devices (Gateway Manager / IAG5 inventory) | Yes | Cannot proceed |
| Push config to IOS-XE devices | Yes | Cannot proceed |
| Parse VLAN / trunk output | Yes | Cannot proceed |
| Orchestrate per-device steps with tracking | Yes | Cannot proceed |
| Human approval step (WorkCenter) | Yes | Cannot proceed — approval is required |
| Create and update ServiceNow change requests (create, work notes, state, close) | Yes | Cannot proceed — no change without a CR |
| Operator input form (JSON Form + manual trigger) | Yes | Inputs via API / job start only |
| Compare pre and post state | Yes | Manual verification |
| Evidence report | No | Engineer documents manually |

### What external systems are involved

| System | Purpose | Required | If Not Available |
|--------|---------|----------|------------------|
| IAG5 gateway + inventory (`lab_gateway_cluster_2` / `itential-inventory`, `lab_gateway_cluster` / `lab-inventory`) | Device access | Yes | Cannot proceed |
| ServiceNow (`ServiceNow` or `ServiceNow Table API` integration) | Change request create / update / close | Yes | Cannot proceed |
| Nautobot | — | No (out of scope) | — |

### Discovery answers

| # | Question | Answer |
|---|----------|--------|
| 1 | Vendors / OS | Cisco IOS-XE only |
| 2 | Trunk allowed lists | Additive (`add`) only |
| 3 | VTP / GVRP | Not used; VLANs managed statically per device (assumed) |
| 4 | IPAM for VLANs | None in scope |
| 5 | Change ticket required? | Yes — the automation creates a ServiceNow normal change request per request and keeps it updated to closure; approval in WorkCenter |
| 6 | SVI creation | Out of scope |
| 7 | Naming convention | Default rule in Section 4 (adjustable) |
| 8 | Switches per change | Small — lab devices only |
| 9 | Never-touch devices | Anything not on the lab allow-list |
| 10 | Reachability test | No — VLAN table + port verification only |

---

## 8. Batch Strategy

Parallel per device, tracked individually; one approval covers all devices in the request.

---

## 9. Acceptance Criteria

1. Invalid requests (bad VLAN ID, bad name, non-lab device, VLAN exists on create / missing on modify, unknown port) are rejected before any config change, with a clear reason.
2. Pre-check captures VLAN table, trunk state and port config for every target before the change.
3. A ServiceNow change request is created for every valid request before any device contact beyond read-only validation, with implementation, backout and test plans filled; invalid requests create no CR. If the CR cannot be created, no config is pushed.
4. No config is pushed until the WorkCenter approval is approved; approval moves the CR to Implement, and a rejection moves it to Canceled and ends the job with no changes.
5. After create, the VLAN with the requested name exists on every target device.
6. After modify, the VLAN name and port assignments match the request.
7. Access ports are in the requested VLAN.
8. Trunk ports include the VLAN, and every VLAN allowed before the change is still allowed.
9. A device failing post-check is rolled back to its baseline and re-verified; a failed rollback is flagged for manual attention.
10. The evidence report lists the request, approver decision, per-device config pushed, pre vs post state, and any failures or rollbacks, and is added to the CR.
11. The CR carries work notes for baseline, approval, each device push and each rollback, and is closed with a close code matching the real outcome (successful / successful with issues / unsuccessful).
