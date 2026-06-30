import fs from "fs";
import path from "path";

const SOURCE = "outputs/sql优化_main_execute_workflow_部门账号联系人通知_单链路读取GitHubCSV版.json";
const OUTPUT = "outputs/sql优化_main_execute_workflow_部门账号联系人通知_单链路SSH拉仓库CSV版.json";
const DOWNLOAD_OUTPUT = "/Users/jiangchuanchen/Downloads/sql优化_main_execute_workflow_部门账号联系人通知_单链路SSH拉仓库CSV版.json";
const GITHUB_OUTPUT = "/private/tmp/KN-YCGJ-TZ-alert-sync/alert-sql-notification/workflows/sql-optimizer-notify-ssh-repo-csv-single-chain.workflow.json";

const sshCommand = String.raw`=ssh root@10.20.84.176 "set -e
REPO=/root/KN-YCGJ-TZ
CSV=\$REPO/alert-sql-notification/data/alert-contact-mapping.csv
if [ -d \"\$REPO/.git\" ]; then
  cd \"\$REPO\"
  git fetch origin main >/dev/null 2>&1
  git reset --hard origin/main >/dev/null 2>&1
else
  rm -rf \"\$REPO\"
  git clone git@github.com:chenjiuxuan1/KN-YCGJ-TZ.git \"\$REPO\" >/dev/null 2>&1
fi
cat \"\$CSV\"
"`;

const workflow = JSON.parse(fs.readFileSync(SOURCE, "utf8"));
workflow.name = "sql优化_main_execute_workflow_部门账号联系人通知_单链路SSH拉仓库CSV版";

const fetchNode = workflow.nodes.find((node) => node.name === "Fetch Contact CSV");
if (!fetchNode) throw new Error("Missing Fetch Contact CSV");

fetchNode.type = "n8n-nodes-base.ssh";
fetchNode.typeVersion = 1;
fetchNode.parameters = {
  authentication: "privateKey",
  command: sshCommand,
};
fetchNode.credentials = {
  sshPrivateKey: {
    id: "REPLACE_WITH_YOUR_SSH_CREDENTIAL_ID",
    name: "巴基斯坦跳板机",
  },
};
fetchNode.notes = "SSH 到能访问 GitHub 的机器，拉取 KN-YCGJ-TZ 最新代码后 cat 出联系人 CSV。若目标机器不是 10.20.84.176，请只改 command 里的 ssh 地址。";

const mergeNode = workflow.nodes.find((node) => node.name === "Merge Notify Target");
if (!mergeNode) throw new Error("Missing Merge Notify Target");
let code = mergeNode.parameters.jsCode;
code = code.replace(
  "const body = item.data || item.body || item.response || item;",
  "const body = item.stdout || item.data || item.body || item.response || item;",
);
mergeNode.parameters.jsCode = code;

for (const node of workflow.nodes) {
  if (node.parameters && node.parameters.jsCode) new Function(node.parameters.jsCode);
}

fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
fs.writeFileSync(OUTPUT, JSON.stringify(workflow, null, 2) + "\n");
fs.writeFileSync(DOWNLOAD_OUTPUT, JSON.stringify(workflow, null, 2) + "\n");

const githubWorkflow = JSON.parse(JSON.stringify(workflow));
const serialized = JSON.stringify(githubWorkflow, null, 2)
  .replace(/Bearer sk-[A-Za-z0-9_-]+/g, "Bearer __FILL_IN_N8N__")
  .replace(/sidecarToken: '[^']*'/g, "sidecarToken: '__FILL_IN_N8N__'")
  .replace(/weiduSidecarToken: '[^']*'/g, "weiduSidecarToken: '__FILL_IN_N8N__'");
fs.writeFileSync(GITHUB_OUTPUT, serialized + "\n");

console.log(OUTPUT);
console.log(DOWNLOAD_OUTPUT);
console.log(GITHUB_OUTPUT);
