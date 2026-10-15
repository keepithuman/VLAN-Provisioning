import json, uuid
from api import call
IDS = json.load(open("ids.json")); PID = IDS["projectId"]
F = [  # customKey, title, type, required, description, placeholder, enum, default
 ("operation", "Operation", "string", True, "create a new VLAN, or modify an existing one (rename and/or add ports)", "Select", ["create", "modify"], "create"),
 ("vlanId", "VLAN ID", "integer", True, "2-1001 or 1006-4094", "e.g. 3900", None, None),
 ("vlanName", "VLAN name", "string", False, "A-Z, 0-9, _ and -, max 32 chars. Required for create; for modify, leave empty to keep the name", "e.g. DEMO_ITENTIAL_3900", None, ""),
 ("device", "Device", "string", True, "Lab switch to change", "Select", ["LAB-C8300-SW01"], "LAB-C8300-SW01"),
 ("accessPorts", "Access ports", "string", False, "Comma-separated, e.g. Gi1/0/39, Gi1/0/38", "Gi1/0/39", None, ""),
 ("trunkPorts", "Trunk ports", "string", False, "Comma-separated existing trunks; the VLAN is only added (never replaces the allowed list)", "", None, ""),
 ("justification", "Business justification", "string", True, "Goes into the ServiceNow change request", "Why is this change needed?", None, None),
]
items, props, ui = [], {}, {}
for k, title, typ, req, desc, ph, enum, default in F:
    it = {"nodeId": str(uuid.uuid4()), "type": typ, "title": title, "description": desc, "placeholder": ph,
          "required": req, "customKey": k}
    pr = {"type": typ, "title": title, "_id": f"/properties/{k}", "description": desc}
    if enum:
        it.update({"binding": False, "rel": "collection", "targetPointer": "/enum",
                   "enum": [{"id": f"{k}{i}", "label": v, "value": v} for i, v in enumerate(enum)],
                   "enumNames": [{"id": f"{k}{i}", "label": v, "value": v} for i, v in enumerate(enum)]})
        pr.update({"enum": enum, "enumNames": enum})
    elif typ == "string":
        it.update({"binding": False, "rel": "item", "targetPointer": "/default"})
    if default is not None:
        it["default"] = default; pr["default"] = default
    items.append(it); props[k] = pr; ui[k] = {"ui:placeholder": ph}
form = {"name": "VLAN Request", "description": "Request a VLAN create or modify on a lab switch (ServiceNow change + Work Center approval).",
        "struct": {"type": "array", "items": items},
        "schema": {"title": "VLAN Request", "description": "Create or modify a VLAN. A ServiceNow change request is opened and an approver must approve before anything is pushed.",
                   "type": "object", "required": [f[0] for f in F if f[3]], "properties": props},
        "uiSchema": ui, "bindingSchema": {}, "validationSchema": {}, "tags": [], "version": "2020.1"}
c, r = call("POST", "/json-forms/forms", form); print("form", c, json.dumps(r)[:300])
