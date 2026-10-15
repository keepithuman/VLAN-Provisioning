#!/bin/sh
# Rebuild from source and import the project. Re-importing over an existing project is a full replace,
# so it aborts if the project holds components this build does not produce (e.g. the JSON form).
# Then restores membership from members.json (copy members.example.json and fill in your account/group IDs).
set -e
cd "$(dirname "$0")"
TMP=${TMPDIR:-/tmp}
python3 build.py
PID=$(jq -r .projectId ids.json)
python3 api.py GET "/automation-studio/projects/$PID" "" "$TMP/vlan-pre.json" >/dev/null || true
jq -r '.data.components[]?.reference' "$TMP/vlan-pre.json" 2>/dev/null | sort > "$TMP/vlan-pre-refs.txt" || true
jq -r '.project.components[].reference' project-import.json | sort > "$TMP/vlan-new-refs.txt"
if [ -s "$TMP/vlan-pre-refs.txt" ] && ! diff -q "$TMP/vlan-pre-refs.txt" "$TMP/vlan-new-refs.txt" >/dev/null; then
  echo "project $PID has components this build does not produce - abort"; exit 1
fi
python3 api.py POST /automation-studio/projects/import project-import.json import-response.json >/dev/null
python3 api.py PATCH "/automation-studio/projects/$PID" members.json "$TMP/vlan-patch.json" >/dev/null
jq -c '{message, failed: [.metadata.failedComponents[]? | {n: .document.name, e: .error}]}' import-response.json
