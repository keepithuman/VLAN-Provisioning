# Solution Design: VLAN Provisioning

**Date:** 2026-10-15 · **Status:** Approved (engineer: "make good choices", 2026-10-15)
**Inputs:** `customer-spec.md` (approved), `feasibility.md` (feasible with constraints)

## A. Environment Summary

An Itential Platform (Cloud) instance. Device access through IAG5 cluster `lab_gateway_cluster`, inventory `lab-inventory`, target **LAB-C8300-SW01** (C8300 with a switch module, IOS-XE 17.06). ServiceNow through integration `ServiceNow` (model `ServiceNow Change Management:latest`). Reshaping and decisions in `GatewayManager.runCode` on cluster `lab_gateway_cluster`; approvals in WorkCenter.

## B. Requirements Resolution

| Spec requirement | Status | Resolution |
|---|---|---|
| Show commands on IOS-XE | ✓ | `GatewayManager.sendCommand` |
| Push config | ✓ | `GatewayManager.sendConfig` |
| Parse / validate / diff | ✓ | `GatewayManager.runCode` (Python) |
| Human approval | ✓ | `WorkCenter.InteractiveHTML` (Approve / Reject) |
| Operator form | ✓ | JSON Form + Operations Manager manual trigger |
| ServiceNow change request | ✓ | `createChangeRequest` / `updateChangeRequest` on `ServiceNow` |
| Multi-device | ✗ (scoped down) | One device per request — engineer: "just one device is fine" |
| Nautobot, NX-OS, delete | ✗ | Out of scope |

## C. Design Decisions

| Decision | In this environment |
|---|---|
| Target | One device per request. Allow-list (inside the validation code): `LAB-C8300-SW01` |
| VLAN vs sub-interface | Real VLANs — the C8300 switch module supports them; no sub-interfaces |
| Operations | `create`, `modify` |
| Access ports | `switchport mode access` + `switchport access vlan <id>` |
| Trunk ports | Optional. Must already be in trunk mode (else rejected). Only `switchport trunk allowed vlan add <id>` |
| VLAN name rule | `^[A-Z0-9_-]{1,32}$` |
| VLAN ID rule | 2–1001 or 1006–4094 |
| Modify semantics | Optional rename + **add** ports to the VLAN. Ports are never removed from a VLAN |
| ServiceNow | **As built: standard change** (`type: standard`) created after validation (state New) with a baseline work note. Approve → Scheduled (-2) → Implement (-1); reject → Canceled (4); after deploy → Review (0) → Closed (3). The normal-change path was tried first and refused by the instance (`Assess → Implement: transition_available false`, feasibility C4) |
| CR close code | Successful / Successful with issues (rolled back cleanly) / Unsuccessful (rollback failed) |
| Save config | `write memory` only after post-check passes |
| Rollback | Code-generated reverse lines from the baseline (restore each port's previous mode / VLAN, `trunk allowed vlan remove`, and `no vlan` or old name) |
| Config reads | `show vlan brief`, `show interfaces trunk`, `show running-config interface <port>` per requested port |
| Demo values | VLAN **3900** `DEMO_ITENTIAL_3900`, access port **Gi1/0/39**. Modify demo: rename to `DEMO_ITENTIAL_3900_B` and add **Gi1/0/38** |
| Reshaping | `runCode` (Python, stdin JSON), never JST transformations |

## D. Modular Design

| Spec phase | Component |
|---|---|
| Read device state (validation, pre-check, post-check, rollback verify) | **Child: VLAN - Collect State** (reused 3×) |
| Validate + build plan | runCode task in orchestrator (pure logic over form + state) |
| Open / update / close CR | Tasks in orchestrator |
| Approval | Task in orchestrator |
| Push config + verify | **Child: VLAN - Apply and Verify** (used for deploy and rollback) |
| Report | runCode task in orchestrator |

### Component Inventory

| # | Component | Type | Action |
|---|---|---|---|
| 1 | Project `VLAN Provisioning (Deterministic)` | Project | Build (import) |
| 2 | VLAN - Collect State | Child workflow: sendCommand → runCode parse → `state` | Build |
| 3 | VLAN - Apply and Verify | Child workflow: sendConfig(lines) → childJob Collect State → runCode check(expect) → `result {passed, checks, post}` | Build |
| 4 | VLAN Provisioning | Orchestrator workflow | Build |
| 5 | VLAN Request | JSON Form | Build |
| 6 | VLAN Provisioning | Ops Manager automation + manual trigger (form) | Build |

### Orchestrator flow

```
start(request) → Collect State (baseline) → runCode Validate & Plan
  invalid → set status=rejected, report → end           (no CR, no change)
  valid   → createChangeRequest (normal, Assess, plans from code)
              error → status=failed "CR create failed" → end   (no change)
          → update CR: work note "baseline captured"
          → InteractiveHTML approval (plan, CR number, baseline)
              reject → update CR Canceled (4) + close notes → end
              approve → update CR Implement (-1) + approver note  (fallback: standard)
          → Apply and Verify (plan.configLines, plan.expect)
              passed → sendCommand write memory → close code Successful
              failed → Apply and Verify (plan.rollbackLines, plan.baselineExpect)
                         passed → Successful with issues ; failed → Unsuccessful (manual attention)
          → runCode report → update CR: Review (0) + evidence note → update CR: Closed (3) + close code → end
```

Every adapter / gateway task has an error transition to a `newVariable` failure handler → report → end.

### JSON Form fields

`operation` (enum create/modify), `vlanId` (integer), `vlanName` (string), `device` (enum `LAB-C8300-SW01`), `accessPorts` (comma list), `trunkPorts` (comma list, optional), `justification` (string).

## E. Implementation Plan

| Step | Build | Test |
|---|---|---|
| 1 | Fetch task schemas (sendCommand, sendConfig, runCode, InteractiveHTML, CR tasks, childJob) | — |
| 2 | Collect State child | Run against C8300 with ports Gi1/0/39 → parsed VLANs/trunks/ports match CLI |
| 3 | Validate & Plan code | Unit-run locally with captured state: bad ID, bad name, non-allowed device, VLAN exists, unknown port, non-trunk trunk port, happy create/modify |
| 4 | Apply and Verify child | Push VLAN 3900 + Gi1/0/39, verify, then push rollback lines, verify baseline restored |
| 5 | Orchestrator + form + trigger, import project atomically, PATCH membership | Validate workflows (`/workflow_engine/workflows/validate`) |
| 6 | Hand to `/qa-agent` | Acceptance tests (section F) |

## F. Acceptance Criteria → Tests

| AC | Test |
|---|---|
| 1 Invalid rejected early | Jobs with VLAN 1, name `bad name`, VLAN 10 (exists) on create, port Gi9/9/9, trunk port Gi1/0/39 → `status=rejected`, reason listed, no CR created, no sendConfig task ran |
| 2 Baseline captured | Job variable `baseline` contains VLAN table, trunks and port configs |
| 3 CR before change; no CR → no push | Happy path: CR number exists before approval task; CR-create error path (bad adapter response simulated by forced error) → no Apply task ran |
| 4 Approval gate | Reject run → CR state Canceled, no Apply task ran; approve run → CR Implement before push |
| 5 Create | VLAN 3900 `DEMO_ITENTIAL_3900` in `show vlan brief` after job |
| 6 Modify | Rename to `DEMO_ITENTIAL_3900_B` + add Gi1/0/38 → both visible |
| 7 Access ports | Gi1/0/39 (and Gi1/0/38) in VLAN 3900 |
| 8 Trunks additive | No trunk on device → covered by validation (non-trunk rejected) + rollback-line unit test; live only if a trunk is configured |
| 9 Rollback | Apply-and-Verify child run with a deliberately wrong expectation → rollback lines applied, baseline restored |
| 10 Evidence report | `report` job variable + CR work note contain request, approver, lines, pre/post, outcome |
| 11 CR lifecycle | CR final state Closed with close code; work notes for baseline, approval, push, evidence |

Cleanup after testing: remove VLAN 3900 and return Gi1/0/38–39 to VLAN 10 (rollback lines from the create run).

## As Built (2026-10-15)

| Component | ID |
|---|---|
| Project `VLAN Provisioning (Deterministic)` | `8d652c7ddac069ee93494cd2` |
| Workflow `VLAN - Collect State` | `0aced584-b716-4400-ad94-f9540aa9b1ba` |
| Workflow `VLAN - Apply and Verify` | `50a8d3d1-f18c-4882-942c-81ce1e620b80` |
| Workflow `VLAN Provisioning` (orchestrator) | `416fea37-55a8-44ee-a1c7-b00049c09765` |
| JSON Form `VLAN Request` | `6ad128e6b03e5f2c6c343ba4` (in project) |
| Ops Manager automation `VLAN Provisioning` | `6ad128eefa86b95a5959f6ab` |
| Manual trigger `VLAN Request` (`legacyWrapper: false`) | `6ad128effa86b95a5959f6ac` |

Source: `build/` (`vlan.py` = all runCode logic, `build.py` = workflow generator, `unit_test.py`, `e2e.py`, `form.py`).

**Deviations from the design**
- Standard change instead of normal (see Section C).
- The baseline is captured once, before the CR is opened (it feeds validation too); the CR gets it as a work note right after creation.
- Rejected-by-approver path sets `status` but no `report` object (the CR close notes carry the outcome).
