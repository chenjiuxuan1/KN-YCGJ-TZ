#!/usr/bin/env python3
"""Generate the compact Python-backed n8n workflow from the existing flow shape."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "workflows/ds-zombie-scan-python.workflow.json"

COUNTRIES = [
    ("中国", "cn", "wGL20YUQ7ZpN1xRA", "中国跳板机", "ssh -p 36000 root@10.20.47.14"),
    ("菲律宾", "ph", "MQWXoKIQxg8ae2Nt", "菲律宾跳板机", "ssh root@10.20.10.12"),
    ("印尼", "ine", "SyHW5nXUCnuULr2c", "印尼跳板机", "ssh -p 36000 root@192.168.21.236"),
    ("墨西哥", "mx", "7oQDoS8H2buTjr7H", "墨西哥跳板机", "ssh -p 36000 root@172.20.220.165"),
    ("泰国", "th", "SliSXhrkW6tiEFFo", "泰国跳板机", "ssh -p 36000 root@192.168.20.236"),
    ("巴基斯坦", "pk", "W8NbqcmBWoI5MZ3s", "巴基斯坦跳板机", "ssh root@10.20.84.176"),
]


def _ssh_command(code, hop):
    return """={hop} 'bash -s' <<'DS_ZOMBIE_SCAN'
set -e
REPO=/tmp/KN-YCGJ-TZ-governance-automation
SCRIPT="$REPO/alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py"
test -s "$SCRIPT" || {{ echo "DS_ZOMBIE_SCAN_CODE_NOT_DEPLOYED" >&2; exit 31; }}
cd "$REPO/alert-sql-notification/governance-automation"
# DS_DB_* and GOVERNANCE_DB_* must already exist in the remote service environment.
ARGS=(--country {code} --batch-id '{{$json.batch_id}}' --lookback-days '{{$json.lookback_days}}' --min-stale-months '{{$json.min_stale_months}}' --score-version '{{$json.score_version}}' --top-limit '{{$json.top_limit}}')
[ -z '{{$json.project_name}}' ] || ARGS+=(--project-name '{{$json.project_name}}')
[ -z '{{$json.workflow_name}}' ] || ARGS+=(--workflow-name '{{$json.workflow_name}}')
[ -z '{{$json.task_name}}' ] || ARGS+=(--task-name '{{$json.task_name}}')
[ '{{$json.write_to_db}}' != 'true' ] || ARGS+=(--write-to-db)
[ '{{$json.dry_run}}' != 'true' ] || ARGS+=(--dry-run)
python3 "$SCRIPT" "${{ARGS[@]}}"
DS_ZOMBIE_SCAN""".format(hop=hop, code=code)


def build_workflow():
    nodes = [
        {"parameters": {}, "id": "manual", "name": "Manual Trigger - Run Scan", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [-900, 300]},
        {"parameters": {"jsCode": """const c={country:'th',minStaleMonths:3,lookbackDays:30,projectName:'',workflowName:'',taskName:'',writeToDb:true,dryRun:false,scoreVersion:'v1',topLimit:0}; const id=String(Date.now()); return [{json:{request_id:id,batch_id:id,country:c.country,min_stale_months:c.minStaleMonths,lookback_days:c.lookbackDays,project_name:c.projectName,workflow_name:c.workflowName,task_name:c.taskName,write_to_db:c.writeToDb,dry_run:c.dryRun,score_version:c.scoreVersion,top_limit:Math.max(0,Number(c.topLimit)||0)}}];"""}, "id": "request", "name": "Build Manual Scan Request", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [-680, 300]},
        {"parameters": {"rules": {"values": [{"conditions": {"conditions": [{"leftValue": "={{$json.country}}", "rightValue": code, "operator": {"type": "string", "operation": "equals"}}]}} for _, code, *_ in COUNTRIES]}}, "id": "switch", "name": "按国家分流", "type": "n8n-nodes-base.switch", "typeVersion": 3, "position": [-440, 300]},
    ]
    for index, (name, code, credential_id, credential_name, hop) in enumerate(COUNTRIES):
        nodes.append({"parameters": {"command": _ssh_command(code, hop)}, "id": "ssh-" + code, "name": name, "type": "n8n-nodes-base.ssh", "typeVersion": 1, "position": [-140, 60 + index * 120], "credentials": {"sshPrivateKey": {"id": credential_id, "name": credential_name}}})
    nodes.append({"parameters": {"jsCode": """const raw=$json||{}; const out=String(raw.stdout||'').trim(); if(!out) throw new Error(String(raw.stderr||'EMPTY_STDOUT')); const p=JSON.parse(out); if(Array.isArray(p.data)||Array.isArray(p.candidates)) throw new Error('BULK_RESULT_REJECTED'); return [{json:p}];"""}, "id": "summary", "name": "Validate Python Summary", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [180, 300]})
    connections = {
        "Manual Trigger - Run Scan": {"main": [[{"node": "Build Manual Scan Request", "type": "main", "index": 0}]]},
        "Build Manual Scan Request": {"main": [[{"node": "按国家分流", "type": "main", "index": 0}]]},
        "按国家分流": {"main": [[{"node": name, "type": "main", "index": 0}] for name, *_ in COUNTRIES]},
    }
    for name, *_ in COUNTRIES:
        connections[name] = {"main": [[{"node": "Validate Python Summary", "type": "main", "index": 0}]]}
    return {"name": "DS僵尸任务扫描_Python处理_直连DS库", "nodes": nodes, "connections": connections, "active": False, "settings": {"executionOrder": "v1"}}


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_workflow(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
