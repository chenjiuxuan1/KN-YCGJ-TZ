import fs from "fs";
import path from "path";

const SOURCE = "/Users/jiangchuanchen/Downloads/sql优化_main_execute_workflow_部门账号联系人通知写死版.json";
const OUTPUT = "outputs/sql优化_main_execute_workflow_部门账号联系人通知_单链路读取GitHubCSV版.json";
const GITHUB_OUTPUT = "/private/tmp/KN-YCGJ-TZ-alert-sync/alert-sql-notification/workflows/sql-optimizer-notify-github-raw-csv-single-chain.workflow.json";
const CSV_URL = "https://raw.githubusercontent.com/chenjiuxuan1/KN-YCGJ-TZ/main/alert-sql-notification/data/alert-contact-mapping.csv";

const workflow = JSON.parse(fs.readFileSync(SOURCE, "utf8"));
workflow.name = "sql优化_main_execute_workflow_部门账号联系人通知_单链路读取GitHubCSV版";

function getNode(name) {
  const node = workflow.nodes.find((item) => item.name === name);
  if (!node) throw new Error(`Missing node: ${name}`);
  return node;
}

const notifyConfig = getNode("Notify Config");
const getUserInfo = getNode("Get User Info");
const mergeNotifyTarget = getNode("Merge Notify Target");

const fetchContactCsv = {
  parameters: {
    method: "GET",
    url: CSV_URL,
    responseFormat: "text",
    sendHeaders: false,
    options: {
      timeout: 30000,
    },
  },
  type: "n8n-nodes-base.httpRequest",
  typeVersion: 4.4,
  position: [
    notifyConfig.position[0] + 220,
    notifyConfig.position[1],
  ],
  id: "8ff21d4b-e97e-4d1f-ae1b-93d8b29276f0",
  name: "Fetch Contact CSV",
  notesInFlow: true,
  notes: "从 GitHub raw 拉取最新联系人 CSV。这个节点只读 CSV，不写文件、不 git pull。",
};

workflow.nodes = workflow.nodes.filter((node) => ![
  "Has Contact Override URL?",
  "Fetch Contact Overrides",
  "Pull Contact CSV Repo",
  "Read Contact CSV",
].includes(node.name));
workflow.nodes.push(fetchContactCsv);

fetchContactCsv.position = [notifyConfig.position[0] + 220, notifyConfig.position[1]];
getUserInfo.position = [notifyConfig.position[0] + 440, notifyConfig.position[1]];
mergeNotifyTarget.position = [notifyConfig.position[0] + 660, notifyConfig.position[1]];

workflow.connections["Notify Config"] = {
  main: [[{ node: "Fetch Contact CSV", type: "main", index: 0 }]],
};
workflow.connections["Fetch Contact CSV"] = {
  main: [[{ node: "Get User Info", type: "main", index: 0 }]],
};
workflow.connections["Get User Info"] = {
  main: [[{ node: "Merge Notify Target", type: "main", index: 0 }]],
};
delete workflow.connections["Has Contact Override URL?"];
delete workflow.connections["Fetch Contact Overrides"];
delete workflow.connections["Pull Contact CSV Repo"];
delete workflow.connections["Read Contact CSV"];

let mergeCode = mergeNotifyTarget.parameters.jsCode;
const start = mergeCode.indexOf("const accountNotifyMap = ");
const end = mergeCode.indexOf("const contactOverrideRawRows", start);
if (start < 0 || end < 0) {
  throw new Error("Cannot locate accountNotifyMap block");
}

const replacement = String.raw`const accountNotifyMap = {};
const firstField = (row, names) => {
  for (const name of names) {
    if (row && row[name] !== undefined && row[name] !== null && String(row[name]).trim() !== '') return row[name];
  }
  return '';
};
const parseCsvRows = (text) => {
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
  if (rows.length < 2) return [];
  const headers = rows[0].map((cell) => String(cell || '').trim());
  return rows.slice(1).map((cells) => Object.fromEntries(headers.map((header, index) => [header, cells[index] || ''])));
};
const normalizeOverrideRows = (rawItems) => {
  const normalized = [];
  for (const item of rawItems) {
    if (Array.isArray(item)) {
      normalized.push(...normalizeOverrideRows(item));
      continue;
    }
    const body = item.data || item.body || item.response || item;
    if (typeof body === 'string') {
      const text = body.trim();
      if (!text) continue;
      try {
        const parsed = JSON.parse(text);
        normalized.push(...normalizeOverrideRows(Array.isArray(parsed) ? parsed : [parsed]));
      } catch (error) {
        normalized.push(...parseCsvRows(text));
      }
      continue;
    }
    if (body && typeof body === 'object') {
      if (Array.isArray(body)) normalized.push(...normalizeOverrideRows(body));
      else if (Array.isArray(body.rows)) normalized.push(...normalizeOverrideRows(body.rows));
      else if (Array.isArray(body.data)) normalized.push(...normalizeOverrideRows(body.data));
      else normalized.push(body);
    }
  }
  return normalized;
};
const canonicalSheet = (value) => {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return '';
  if (/中国|china|starrocks_cn|\bcn\b/.test(text)) return 'cn';
  if (/印尼|印度尼西亚|indonesia|starrocks_ine|starrocks_id|\bine\b|\bid\b/.test(text)) return 'ine';
  if (/泰国|thailand|starrocks_th|\bth\b/.test(text)) return 'th';
  if (/菲律宾|philippines|starrocks_ph|\bph\b/.test(text)) return 'ph';
  if (/巴基斯坦|pakistan|starrocks_pak|starrocks_pk|\bpak\b|\bpk\b/.test(text)) return 'pk';
  if (/墨西哥|mexico|starrocks_mex|starrocks_mx|\bmex\b|\bmx\b/.test(text)) return 'mx';
  return text;
};
const splitPeople = (value) => String(value || '')
  .split(/[、,，;；/\\|\n\r\t]+/)
  .map((item) => item.trim())
  .filter(Boolean);
const overrideCountryOwners = {
  cn: { contacts: ['张恒阳', '宗美晨'], emails: ['owenzhang@kn.group', 'rockyzong@kn.group'] },
  ine: { contacts: ['何柳琴', '翟爽'], emails: ['gretchenhe@kn.group', 'riverzhai@kn.group'] },
  th: { contacts: ['黄启龙', '朱会明'], emails: ['qilonghuang@kn.group', 'brightonzhu@kn.group'] },
  ph: { contacts: ['汤伟', '陈江川'], emails: ['simontang@kn.group', 'jiangchuanchen@kn.group'] },
  pk: { contacts: ['余红叶', '穆晋杰'], emails: ['adamyu@kn.group', 'moonmu@kn.group'] },
  mx: { contacts: ['吴奎', '邓保保'], emails: ['kuiwu@kn.group', 'enzodeng@kn.group'] },
};
const applyContactOverrides = (rows) => {
  const applied = [];
  for (const row of rows) {
    const sheet = canonicalSheet(firstField(row, ['国家', 'country', 'sheet', '集群', 'cluster']));
    const account = normalizeAccount(firstField(row, ['账号', 'account', 'user', '用户']));
    const department = String(firstField(row, ['部门', '数据开发组', 'department', 'dept']) || '').trim();
    const note = String(firstField(row, ['备注', '备注(近2月访问)', 'note', 'remark', 'remarks']) || '').trim();
    let contacts = splitPeople(firstField(row, ['修改后联系人', '联系人', 'contacts', 'contact', 'name', 'names']));
    let emails = splitPeople(firstField(row, ['修改后邮箱', '邮箱', 'emails', 'email']));
    const action = String(firstField(row, ['操作', 'action', '是否删除', 'delete']) || '').trim().toLowerCase();
    if (!sheet || !account) continue;
    if (action === 'delete' || action === '删除' || action === 'true') {
      if (accountNotifyMap[sheet]) delete accountNotifyMap[sheet][account];
      applied.push({ sheet, account, action: 'delete' });
      continue;
    }
    let defaultedToCountryOwner = false;
    if (!contacts.length && overrideCountryOwners[sheet]) {
      contacts = overrideCountryOwners[sheet].contacts;
      emails = overrideCountryOwners[sheet].emails;
      defaultedToCountryOwner = true;
    }
    if (/未填写.*联系人|兜底.*国家负责人|国家负责人.*确认/.test(note)) {
      defaultedToCountryOwner = true;
    }
    if (!emails.length) continue;
    accountNotifyMap[sheet] = accountNotifyMap[sheet] || {};
    accountNotifyMap[sheet][account] = { department, contacts, emails, defaultedToCountryOwner, note };
    applied.push({ sheet, account, department, contacts, emails, action: 'upsert', defaultedToCountryOwner, note });
  }
  return applied;
};
`;

mergeCode = mergeCode.slice(0, start) + replacement + mergeCode.slice(end);
mergeCode = mergeCode.replace("safeAll('Fetch Contact Overrides')", "safeAll('Fetch Contact CSV')");
mergeNotifyTarget.parameters.jsCode = mergeCode;

for (const node of workflow.nodes) {
  if (node.parameters && node.parameters.jsCode) new Function(node.parameters.jsCode);
}

fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
fs.writeFileSync(OUTPUT, JSON.stringify(workflow, null, 2) + "\n");

const githubWorkflow = JSON.parse(JSON.stringify(workflow));
const serialized = JSON.stringify(githubWorkflow, null, 2)
  .replace(/Bearer sk-[A-Za-z0-9_-]+/g, "Bearer __FILL_IN_N8N__")
  .replace(/sidecarToken: '[^']*'/g, "sidecarToken: '__FILL_IN_N8N__'")
  .replace(/weiduSidecarToken: '[^']*'/g, "weiduSidecarToken: '__FILL_IN_N8N__'");
fs.writeFileSync(GITHUB_OUTPUT, serialized + "\n");

console.log(OUTPUT);
console.log(GITHUB_OUTPUT);
