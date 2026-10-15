# Feasibility: VLAN Provisioning

**Date:** 2026-10-15
**Platform:** https://<your-platform>
**Spec:** `customer-spec.md` (approved 2026-10-15)

## Decision: **Feasible with constraints**

Everything the spec needs exists on the platform and was checked live (read-only). Three constraints change how it gets built and tested; none block the build.

---

## 1. Capabilities

| Capability (spec §7) | Status | How |
|---|---|---|
| Run show commands on IOS-XE | ✓ | `GatewayManager.sendCommand`; also IAG5 `run-command` service on both clusters (verified live) |
| Push config to IOS-XE | ✓ | `GatewayManager.sendConfig` (used by Interface Down Troubleshooting) |
| Parse VLAN / trunk output | ✓ | `GatewayManager.runCode` (Python on the gateway) |
| Per-device orchestration | ✓ | Workflow engine, childJob loops |
| Human approval | ✓ | `WorkCenter.InteractiveHTML` (claim + complete via API) |
| Operator form | ✓ | JSON Form + Operations Manager manual trigger |
| Compare pre / post state | ✓ | `runCode` diff |
| Evidence report | ✓ | `runCode` builds it; job output + CR work note |

## 2. Integrations

| System | Status | Detail |
|---|---|---|
| IAG5 — `lab_gateway_cluster` / inventory `lab-inventory` | ✓ | LAB-C8300-SW01 reachable (show commands answered in ~3–5 s) |
| IAG5 — `lab_gateway_cluster_2` / inventory `itential-inventory` | ✓ reachable, ✗ not usable for this use case | LAB-C8000V-01 — see constraint C1 |
| ServiceNow change requests | ✓ | Integration `ServiceNow` (model `ServiceNow Change Management:latest`): `createChangeRequest`, `updateChangeRequest`, `getChangeRequest`. Already proven in Network Change Assistant (CHG0039525–27: create, Scheduled, Canceled, Closed/Successful). Response shape `response.body.result.<field>.{value, display_value}` |
| ServiceNow Table API | available, not needed | Fallback for work notes if needed |

## 3. Live device findings (read-only, 2026-10-15 19:08Z)

| Device | Model / OS | VLAN support | Ports |
|---|---|---|---|
| **LAB-C8300-SW01** | C8300-2N2S-4T2X, IOS-XE 17.06.03a, with a switch module | **Yes** — VLAN 1 and VLAN 10 `MGMT_VLAN` active | Gi1/0/0–39 access VLAN 10 (description "Test", mostly admin-disabled); Tw1/0/40–47, Te1/0/48–49 in VLAN 1. **No trunks configured today** (`show interfaces trunk` empty) |
| LAB-C8000V-01 | C8000V (virtual), IOS-XE 17.15.01a | VLAN database only (defaults 1, 1002–1005) | **No switchports** (`show interfaces switchport` empty) — routed interfaces only |

## 4. Constraints

| # | Constraint | Impact | Proposed handling |
|---|---|---|---|
| C1 | LAB-C8000V-01 has no layer-2 ports | Cannot assign access or trunk ports | Lab allow-list = **LAB-C8300-SW01 only**. Workflow stays multi-device so more switches can be added to the allow-list later |
| C2 | C8300 has no existing trunk | Trunk acceptance criterion (AC 8 — "baseline VLANs still allowed") can't be shown on a real trunk as-is | Trunk ports in a request must **already be trunks** (validation rejects non-trunk ports — the automation never converts a port to trunk mode). For testing, ask the device owner to configure one spare port (e.g. Tw1/0/47) as a trunk with a couple of allowed VLANs, or accept AC 8 tested on the reject path only |
| C3 | C8300 is physical customer lab hardware, shared with other people | Live tests change a real device | Get the device owner's OK and a spare port range + test VLAN IDs (proposed: VLAN 3900–3909, ports Gi1/0/36–39) before acceptance tests |
| C4 | ServiceNow state model for a **normal** change may block New/Assess → Implement without a ServiceNow-side approval | CR transitions could be rejected | Build tries normal change with the Itential approval written to the CR. If the instance enforces its own approval, fall back to `type: standard` (pre-approved) and record that deviation — the earlier Network Change project created standard changes |

## 5. Reuse

| Candidate | Use |
|---|---|
| Earlier deterministic Network Change project patterns | ServiceNow CR create / update bodies, state values (Scheduled -2, Implement -1, Review 0, Closed 3, Canceled 4), approval HTML + claim/complete test helper, project import + membership PATCH |
| Interface Down Troubleshooting (Deterministic) | `sendCommand` / `sendConfig` task wiring for IAG5 inventory |
| No existing VLAN workflow on the platform | New build |

## 6. Open questions for the engineer

1. OK to restrict the allow-list to **LAB-C8300-SW01** only (C1)?
2. For trunk testing (C2): ask the device owner for a pre-configured spare trunk, or test the trunk path on validation/reject only?
3. Test VLANs **3900–3909** and ports **Gi1/0/36–39** — acceptable, pending the device owner's OK (C3)?
4. OK with the normal → standard change fallback if ServiceNow blocks it (C4)?
