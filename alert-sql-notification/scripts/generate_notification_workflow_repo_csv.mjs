import fs from "fs";
import path from "path";

const SOURCE_WORKFLOW = "outputs/sql优化_main_execute_workflow_部门账号联系人通知版.json";
const OUTPUT_WORKFLOW = "outputs/sql优化_main_execute_workflow_部门账号联系人通知_读取仓库CSV版.json";
const GITHUB_WORKFLOW = "/private/tmp/KN-YCGJ-TZ-alert-sync/alert-sql-notification/workflows/sql-optimizer-notify-repo-csv.workflow.json";

const REPO_URL = "git@github.com:chenjiuxuan1/KN-YCGJ-TZ.git";
const REPO_DIR = "/data/KN-YCGJ-TZ";
const CONTACT_CSV_PATH = `${REPO_DIR}/alert-sql-notification/data/alert-contact-mapping.csv`;

const pullRepoCommand = `bash -lc 'set -euo pipefail
REPO_URL="${REPO_URL}"
REPO_DIR="${REPO_DIR}"
CSV_PATH="${CONTACT_CSV_PATH}"
mkdir -p "$(dirname "$REPO_DIR")"
if [ -d "$REPO_DIR/.git" ]; then
  cd "$REPO_DIR"
  git fetch origin main
  git checkout main
  git pull --rebase origin main
else
  git clone "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
  git checkout main
fi
test -f "$CSV_PATH"
echo "repo=$REPO_DIR"
echo "csv=$CSV_PATH"
'`;

const readCsvCode = String.raw`
const fs = require('fs');

const CONTACT_CSV_PATH = '/data/KN-YCGJ-TZ/alert-sql-notification/data/alert-contact-mapping.csv';

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  const input = String(text || '').replace(/^\uFEFF/, '');
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (ch === '"') {
      if (inQuotes && input[i + 1] === '"') {
        field += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      row.push(field);
      field = '';
    } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
      if (ch === '\r' && input[i + 1] === '\n') i += 1;
      row.push(field);
      if (row.some((cell) => String(cell).trim())) rows.push(row);
      row = [];
      field = '';
    } else {
      field += ch;
    }
  }
  row.push(field);
  if (row.some((cell) => String(cell).trim())) rows.push(row);
  if (!rows.length) return [];
  const headers = rows[0].map((cell) => String(cell || '').trim());
  return rows.slice(1).map((cells, index) => {
    const obj = { __rowNumber: index + 2, __source: 'repo_csv', __csvPath: CONTACT_CSV_PATH };
    headers.forEach((header, columnIndex) => {
      obj[header] = String(cells[columnIndex] || '').trim();
    });
    return obj;
  });
}

if (!fs.existsSync(CONTACT_CSV_PATH)) {
  return [{
    json: {
      __source: 'repo_csv',
      __error: 'CONTACT_CSV_NOT_FOUND',
      __csvPath: CONTACT_CSV_PATH,
    }
  }];
}

const rows = parseCsv(fs.readFileSync(CONTACT_CSV_PATH, 'utf8'))
  .filter((row) => String(row['账号'] || row.account || row.user || '').trim());

return rows.map((row) => ({ json: row }));
`;

function node(workflow, name) {
  const found = workflow.nodes.find((item) => item.name === name);
  if (!found) throw new Error(`Missing node: ${name}`);
  return found;
}

function sanitizeWorkflowForGitHub(workflow) {
  const text = JSON.stringify(workflow, null, 2)
    .replace(/Bearer sk-[A-Za-z0-9_-]+/g, "Bearer __FILL_IN_N8N__")
    .replace(/sidecarToken: '[^']*'/g, "sidecarToken: '__FILL_IN_N8N__'")
    .replace(/weiduSidecarToken: '[^']*'/g, "weiduSidecarToken: '__FILL_IN_N8N__'")
    .replace(/sidecarToken: \\"[^\\"]*\\"/g, 'sidecarToken: \\"__FILL_IN_N8N__\\"')
    .replace(/weiduSidecarToken: \\"[^\\"]*\\"/g, 'weiduSidecarToken: \\"__FILL_IN_N8N__\\"');
  return JSON.parse(text);
}

const workflow = JSON.parse(fs.readFileSync(SOURCE_WORKFLOW, "utf8"));
workflow.name = "sql优化_main_execute_workflow_部门账号联系人通知_读取仓库CSV版";

const notifyConfig = node(workflow, "Notify Config");
notifyConfig.parameters.jsCode = notifyConfig.parameters.jsCode
  .replace(/contactOverrideUrl: '[^']*'/, "contactOverrideUrl: ''")
  .replace(/\/\/ Optional: set this to a Google Form response Sheet CSV\/JSON URL or an Apps Script JSON endpoint\.\n\s*/g, "");

const pullNode = {
  parameters: { command: pullRepoCommand },
  type: "n8n-nodes-base.executeCommand",
  typeVersion: 1,
  position: [52080, 21296],
  id: "4e54ec36-714e-4a47-a696-bd32ff3aeb1f",
  name: "Pull Contact CSV Repo",
  notesInFlow: true,
  notes: `通知前拉取 ${REPO_URL}，读取 ${CONTACT_CSV_PATH}。n8n 本机需要安装 git 并配置 SSH key。`,
};

const existingPull = workflow.nodes.findIndex((item) => item.name === "Pull Contact CSV Repo");
if (existingPull >= 0) workflow.nodes[existingPull] = pullNode;
else workflow.nodes.push(pullNode);

const fetchNode = node(workflow, "Fetch Contact Overrides");
fetchNode.type = "n8n-nodes-base.code";
fetchNode.typeVersion = 2;
fetchNode.position = [52320, 21184];
fetchNode.parameters = { jsCode: readCsvCode };
fetchNode.notesInFlow = true;
fetchNode.notes = "从仓库内唯一联系人 CSV 读取映射行，并传给 Merge Notify Target。需要 NODE_FUNCTION_ALLOW_BUILTIN=fs。";

workflow.connections["Notify Config"] = {
  main: [[{ node: "Pull Contact CSV Repo", type: "main", index: 0 }]],
};
workflow.connections["Pull Contact CSV Repo"] = {
  main: [[{ node: "Fetch Contact Overrides", type: "main", index: 0 }]],
};
workflow.connections["Fetch Contact Overrides"] = {
  main: [[{ node: "Get User Info", type: "main", index: 0 }]],
};
delete workflow.connections["Has Contact Override URL?"];

for (const item of workflow.nodes) {
  if (item.parameters && item.parameters.jsCode) new Function(item.parameters.jsCode);
}

fs.writeFileSync(OUTPUT_WORKFLOW, JSON.stringify(workflow, null, 2) + "\n");

const githubWorkflow = sanitizeWorkflowForGitHub(workflow);
fs.writeFileSync(GITHUB_WORKFLOW, JSON.stringify(githubWorkflow, null, 2) + "\n");

console.log(OUTPUT_WORKFLOW);
console.log(GITHUB_WORKFLOW);
