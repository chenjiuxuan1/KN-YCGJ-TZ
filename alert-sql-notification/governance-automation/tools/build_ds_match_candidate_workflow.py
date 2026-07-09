#!/usr/bin/env python3
"""Build n8n child workflow that fetches DS SQL match candidates via country jump hosts."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER_INPUT_CANDIDATES = [
    Path("/Users/jiangchuanchen/Downloads/ds-scheduler-router (1).json"),
    Path("/Users/jiangchuanchen/Downloads/ds-scheduler-router.json"),
]
WATTREL_CONFIG_INPUT = Path("/Users/jiangchuanchen/Downloads/中国的智能告警生成 (1).json")
OUTPUT = ROOT / "outputs" / "DS任务匹配候选查询_execute_workflow.json"
REPO_URL = "https://github.com/chenjiuxuan1/KN-YCGJ-TZ.git"
REPO_ZIP_URL = "https://codeload.github.com/chenjiuxuan1/KN-YCGJ-TZ/zip/refs/heads/main"
REPO_BRANCH = "main"
REMOTE_REPO_DIR = "/tmp/KN-YCGJ-TZ-governance-automation"
REMOTE_SCRIPT = (
    REMOTE_REPO_DIR
    + "/alert-sql-notification/governance-automation/remote_scripts/ds_match_candidate_query.py"
)


DS_COUNTRY_CONFIG = {
    "cn": {
        "host": "rm-uf60p909s1lpp1urp.mysql.rds.aliyuncs.com",
        "port": "3306",
        "database": "cn_dolphin",
        "user": "cn_dolphin",
        "password_env": "CN_DS_DB_PASSWORD",
    },
    "ine": {
        "host": "192.168.25.249",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "e_ds",
        "password_env": "INE_DS_DB_PASSWORD",
    },
    "mx": {
        "host": "rm-2ev5479nuworkbb0x.mysql.rds.aliyuncs.com",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "e_ds",
        "password_env": "MX_DS_DB_PASSWORD",
    },
    "ph": {
        "host": "10.20.81.11",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "a_dolphinscheduler",
        "password_env": "PH_DS_DB_PASSWORD",
    },
    "pk": {
        "host": "rm-gs5zsdzr5kr0sh70p.mysql.singapore.rds.aliyuncs.com",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "e_ds",
        "password_env": "PK_DS_DB_PASSWORD",
    },
    "th": {
        "host": "rm-gs533qw7xj1e7wdp7.mysql.singapore.rds.aliyuncs.com",
        "port": "3306",
        "database": "dolphin_scheduler",
        "user": "a_dolphinscheduler",
        "password_env": "TH_DS_DB_PASSWORD",
    },
}


NORMALIZE_JS = r"""const raw = $json || {};
const cluster = String(raw.cluster || '').trim().toLowerCase();
const countryRaw = String(raw.country || '').trim().toLowerCase();
const map = {
  starrocks_cn: 'cn',
  starrocks_ine: 'ine',
  starrocks_id: 'ine',
  starrocks_mex: 'mx',
  starrocks_mx: 'mx',
  starrocks_pak: 'pk',
  starrocks_pk: 'pk',
  starrocks_ph: 'ph',
  starrocks_th: 'th',
};
let country = countryRaw || map[cluster] || '';
if (!country) {
  if (cluster.includes('mex') || cluster.includes('mx')) country = 'mx';
  else if (cluster.includes('ine') || cluster.includes('indo') || cluster.includes('id')) country = 'ine';
  else if (cluster.includes('pak') || cluster.includes('pk')) country = 'pk';
  else if (cluster.includes('ph')) country = 'ph';
  else if (cluster.includes('th')) country = 'th';
  else if (cluster.includes('cn') || cluster.includes('china')) country = 'cn';
}
const requestId = String(raw.request_id || raw.queryId || raw.query_id || Date.now()).trim();
return [{ json: { ...raw, country, request_id: requestId } }];"""


PARSE_JS = r"""const raw = $json || {};
const stdout = String(raw.stdout || '').trim();
const stderr = String(raw.stderr || '').trim();
if (Object.prototype.hasOwnProperty.call(raw, 'success') && !stdout) {
  return [{ json: raw }];
}
if (!stdout) {
  return [{ json: {
    success: false,
    data: [],
    candidate_count: 0,
    error: { code: 'EMPTY_STDOUT', message: stderr || 'empty stdout' },
  }}];
}
let parsed;
try {
  parsed = JSON.parse(stdout);
} catch (error) {
  return [{ json: {
    success: false,
    data: [],
    candidate_count: 0,
    error: { code: 'INVALID_JSON_STDOUT', message: String(error), stdout, stderr },
  }}];
}
const rows = Array.isArray(parsed.data) ? parsed.data : [];
if (!parsed.success) {
  return [{ json: { ...parsed, data: [], candidate_count: 0 } }];
}
return rows.map((row) => ({ json: {
  ...row,
  ds_match_candidate_success: true,
  ds_match_candidate_country: parsed.country || '',
  ds_match_candidate_count: rows.length,
}}));"""


INVALID_JS = r"""return [{ json: {
  success: false,
  data: [],
  candidate_count: 0,
  error: {
    code: 'INVALID_COUNTRY',
    message: 'country must be one of cn, ph, ine, mx, th, pk',
  },
}}];"""


def extract_wattrel_config() -> dict[str, str]:
    if not WATTREL_CONFIG_INPUT.exists():
        return {}
    text = WATTREL_CONFIG_INPUT.read_text(encoding="utf-8")
    config: dict[str, str] = {}
    for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        match = re.search(rf"export\s+{re.escape(key)}='([^']*)'", text)
        if match:
            config[key] = match.group(1)
    if config.get("DB_NAME") != "wattrel":
        return {}
    return config


def wattrel_export_command(config: dict[str, str]) -> str:
    if not config:
        return ""
    mapping = {
        "DB_HOST": "WATTREL_DB_HOST",
        "DB_PORT": "WATTREL_DB_PORT",
        "DB_USER": "WATTREL_DB_USER",
        "DB_PASSWORD": "WATTREL_DB_PASSWORD",
        "DB_NAME": "WATTREL_DB_NAME",
    }
    parts = []
    for source_key, target_key in mapping.items():
        value = config.get(source_key, "")
        if value:
            if source_key == "DB_PASSWORD":
                continue
            parts.append(f"export {target_key}={shlex.quote(value)}")
    return " && ".join(parts)


def ds_country_export_command(country: str) -> str:
    config = DS_COUNTRY_CONFIG[country]
    return " && ".join(
        [
            f"export DS_DB_HOST={shlex.quote(config['host'])}",
            f"export DS_DB_PORT={shlex.quote(config['port'])}",
            f"export DS_DB_NAME={shlex.quote(config['database'])}",
            f"export DS_DB_USER={shlex.quote(config['user'])}",
        ]
    )


def resolve_router_input() -> Path:
    for path in ROUTER_INPUT_CANDIDATES:
        if path.exists():
            return path
    expected = ", ".join(str(path) for path in ROUTER_INPUT_CANDIDATES)
    raise FileNotFoundError(f"Router workflow JSON not found. Expected one of: {expected}")


def checkout_command() -> str:
    return f"""set -e

REPO={shlex.quote(REMOTE_REPO_DIR)}
ZIP_URL={shlex.quote(REPO_ZIP_URL)}
BRANCH={shlex.quote(REPO_BRANCH)}
ZIP_FILE=/tmp/KN-YCGJ-TZ-governance-automation-main.zip
UNZIP_DIR=/tmp/KN-YCGJ-TZ-governance-automation-unzip
EXTRACTED_DIR="\\$UNZIP_DIR/KN-YCGJ-TZ-\\$BRANCH"

rm -rf "\\$UNZIP_DIR" "\\$ZIP_FILE"
mkdir -p "\\$UNZIP_DIR"

if command -v curl >/dev/null 2>&1; then
  curl -fL --retry 3 --connect-timeout 20 --max-time 180 -o "\\$ZIP_FILE" "\\$ZIP_URL"
elif command -v wget >/dev/null 2>&1; then
  wget -O "\\$ZIP_FILE" "\\$ZIP_URL"
else
  echo "NO_DOWNLOADER: curl or wget is required" >&2
  exit 32
fi

if [ ! -s "\\$ZIP_FILE" ]; then
  echo "REPO_ZIP_DOWNLOAD_EMPTY: \\$ZIP_FILE" >&2
  exit 33
fi

if command -v unzip >/dev/null 2>&1; then
  unzip -q "\\$ZIP_FILE" -d "\\$UNZIP_DIR"
else
  python3 -m zipfile -e "\\$ZIP_FILE" "\\$UNZIP_DIR"
fi

if [ ! -d "\\$EXTRACTED_DIR" ]; then
  echo "REPO_ZIP_EXTRACTED_DIR_NOT_FOUND: \\$EXTRACTED_DIR" >&2
  exit 34
fi

rm -rf "\\$REPO"
mv "\\$EXTRACTED_DIR" "\\$REPO"
rm -rf "\\$UNZIP_DIR" "\\$ZIP_FILE"

echo "deployed_from_zip branch=\\$BRANCH repo=\\$REPO"
test -s {shlex.quote(REMOTE_SCRIPT)}
"""


def candidate_query_command() -> str:
    return f"""set -e

REPO={shlex.quote(REMOTE_REPO_DIR)}
SCRIPT={shlex.quote(REMOTE_SCRIPT)}

if [ ! -s "\\$SCRIPT" ]; then
  echo "DS_MATCH_CODE_NOT_DEPLOYED: \\$SCRIPT" >&2
  echo "Please run the Manual Trigger in this workflow to deploy code first." >&2
  exit 31
fi

cd "\\$REPO"
"""


def remote_command(template: str, country: str) -> str:
    export_parts = [ds_country_export_command(country)]
    wattrel_exports = wattrel_export_command(extract_wattrel_config())
    if wattrel_exports:
        export_parts.append(wattrel_exports)
    exports = "\n".join(export_parts)
    inner = f"""{candidate_query_command()}
{exports}

python3 {shlex.quote(REMOTE_SCRIPT)} --country {shlex.quote(country)}
"""
    return template.replace(
        "cd /root/ds-scheduler-gateway && python3 scripts/ds_scheduler_entry.py --country "
        + country
        + " --action '{{$json.action}}' --ds-token '{{$json.ds_token}}' --request-id '{{$json.request_id}}' --payload-b64 '{{$json.payload_b64}}'",
        inner,
    )


def node_by_name(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def ssh_node_from_router(router: dict, name: str, country: str, position: list[int]) -> dict:
    source = node_by_name(router, name)
    node = {
        "parameters": {
            "authentication": "privateKey",
            "command": remote_command(source["parameters"]["command"], country),
        },
        "id": {
            "中国": "a106a1fd-2dd4-4202-908f-4f7afbd1d420",
            "菲律宾": "c5246327-3efa-4263-b895-a3a19ddf63a6",
            "印尼": "dd58f60c-e567-4db3-8e4f-9d14c7624ab1",
            "墨西哥": "f78ad601-97e3-4627-921e-0db97b35c331",
            "泰国": "b9b65011-f1ef-45d3-b231-f54fcc4b75e7",
            "巴基斯坦": "cae6a616-33f8-4fbd-bf04-e35e25d7a2f",
        }[name],
        "name": name,
        "type": "n8n-nodes-base.ssh",
        "typeVersion": source.get("typeVersion", 1),
        "position": position,
        "credentials": source.get("credentials"),
    }
    return node


def deploy_ssh_node_from_router(router: dict, name: str, country: str, position: list[int]) -> dict:
    source = node_by_name(router, name)
    node = {
        "parameters": {
            "authentication": "privateKey",
            "command": source["parameters"]["command"].replace(
                "cd /root/ds-scheduler-gateway && python3 scripts/ds_scheduler_entry.py --country "
                + country
                + " --action '{{$json.action}}' --ds-token '{{$json.ds_token}}' --request-id '{{$json.request_id}}' --payload-b64 '{{$json.payload_b64}}'",
                checkout_command(),
            ),
        },
        "id": {
            "中国": "4659fa1d-9d81-45fb-b8c7-2e6618d2b1bc",
            "菲律宾": "7ec63611-8537-4dcc-a88c-401c1b02fecd",
            "印尼": "23b7e4a1-f282-42fb-a8b9-845c745ad84d",
            "墨西哥": "d9d7524c-e846-4e6e-a142-09c08cc9597a",
            "泰国": "8fc7c7ee-0952-4d69-aadc-64154ba9dca5",
            "巴基斯坦": "d4cf3882-0f83-4ba6-b582-1320db2b7428",
        }[name],
        "name": "部署代码-" + name,
        "type": "n8n-nodes-base.ssh",
        "typeVersion": source.get("typeVersion", 1),
        "position": position,
        "credentials": source.get("credentials"),
    }
    return node


def build_workflow() -> dict:
    router = json.loads(resolve_router_input().read_text(encoding="utf-8"))
    deploy_trigger = {
        "parameters": {},
        "id": "73a2952b-c5ac-42d5-b41a-93bcff45003a",
        "name": "Manual Trigger - Deploy Code",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": [400, -600],
        "notesInFlow": True,
        "notes": "手动执行：在各国 SSH 节点机器拉取/更新 KN-YCGJ-TZ main 分支代码。日常候选查询不会执行 git 更新。",
    }
    trigger = {
        "parameters": {},
        "id": "54cf84b4-f451-41ee-97fb-4bf597d9f612",
        "name": "When Executed by Another Workflow",
        "type": "n8n-nodes-base.executeWorkflowTrigger",
        "typeVersion": 1,
        "position": [400, 0],
    }
    normalize = {
        "parameters": {"jsCode": NORMALIZE_JS},
        "id": "a6d1ff55-d8f0-4658-8d61-1f7e2d0dd8a2",
        "name": "Normalize DS Match Request",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [640, 0],
    }
    switch = {
        "parameters": node_by_name(router, "按国家分流")["parameters"],
        "id": "d1a936b7-c883-42e5-85e6-820a0189e59a",
        "name": "按国家分流",
        "type": "n8n-nodes-base.switch",
        "typeVersion": 3,
        "position": [880, 0],
    }
    invalid = {
        "parameters": {"jsCode": INVALID_JS},
        "id": "f231e80d-2089-4ecb-9331-f126c9cc85c2",
        "name": "构造请求错误响应",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1120, 288],
    }
    parse = {
        "parameters": {"jsCode": PARSE_JS},
        "id": "a7f1de0e-67d1-4cb1-a917-d68f04c37680",
        "name": "内容解析",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [1568, 0],
    }
    country_specs = [
        ("中国", "cn", [1136, -360]),
        ("菲律宾", "ph", [1136, -216]),
        ("印尼", "ine", [1136, -72]),
        ("墨西哥", "mx", [1136, 72]),
        ("泰国", "th", [1136, 216]),
        ("巴基斯坦", "pk", [1136, 360]),
    ]
    deploy_specs = [
        ("中国", "cn", [736, -960]),
        ("菲律宾", "ph", [736, -816]),
        ("印尼", "ine", [736, -672]),
        ("墨西哥", "mx", [736, -528]),
        ("泰国", "th", [736, -384]),
        ("巴基斯坦", "pk", [736, -240]),
    ]
    nodes = [deploy_trigger, trigger, normalize, switch, invalid, parse]
    for name, country, position in deploy_specs:
        nodes.append(deploy_ssh_node_from_router(router, name, country, position))
    for name, country, position in country_specs:
        nodes.append(ssh_node_from_router(router, name, country, position))
    connections = {
        "Manual Trigger - Deploy Code": {
            "main": [[{"node": "部署代码-" + name, "type": "main", "index": 0} for name, _, _ in deploy_specs]]
        },
        "When Executed by Another Workflow": {
            "main": [[{"node": "Normalize DS Match Request", "type": "main", "index": 0}]]
        },
        "Normalize DS Match Request": {
            "main": [[{"node": "按国家分流", "type": "main", "index": 0}]]
        },
        "按国家分流": {
            "main": [
                [{"node": "中国", "type": "main", "index": 0}],
                [{"node": "菲律宾", "type": "main", "index": 0}],
                [{"node": "印尼", "type": "main", "index": 0}],
                [{"node": "墨西哥", "type": "main", "index": 0}],
                [{"node": "泰国", "type": "main", "index": 0}],
                [{"node": "巴基斯坦", "type": "main", "index": 0}],
                [{"node": "构造请求错误响应", "type": "main", "index": 0}],
            ]
        },
        "构造请求错误响应": {
            "main": [[{"node": "内容解析", "type": "main", "index": 0}]]
        },
    }
    for name, _, _ in country_specs:
        connections[name] = {"main": [[{"node": "内容解析", "type": "main", "index": 0}]]}
    return {
        "name": "DS任务匹配候选查询_execute_workflow",
        "nodes": nodes,
        "pinData": {},
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1"},
        "tags": [],
    }


def main() -> None:
    workflow = build_workflow()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
