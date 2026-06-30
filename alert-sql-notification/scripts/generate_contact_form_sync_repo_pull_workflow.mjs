import fs from "fs";
import path from "path";

const FORM_SPREADSHEET_ID = "16cZaIr0YupjC2P65O6Y3YdtJmznfoOqS-gq-bk1TGQI";
const FORM_GID = "998319904";
const REPO_URL = "git@github.com:chenjiuxuan1/KN-YCGJ-TZ.git";
const REPO_DIR = "/data/KN-YCGJ-TZ";
const CONTACT_CSV_RELATIVE_PATH = "alert-sql-notification/data/alert-contact-mapping.csv";
const CONTACT_CSV_PATH = `${REPO_DIR}/${CONTACT_CSV_RELATIVE_PATH}`;

const updateCsvCode = String.raw`
const fs = require('fs');

const CONTACT_CSV_PATH = '/data/KN-YCGJ-TZ/alert-sql-notification/data/alert-contact-mapping.csv';

const countryOwners = {
  cn: { country: '中国', contacts: ['张恒阳', '宗美晨'], emails: ['owenzhang@kn.group', 'rockyzong@kn.group'] },
  ine: { country: '印尼', contacts: ['何柳琴', '翟爽'], emails: ['gretchenhe@kn.group', 'riverzhai@kn.group'] },
  th: { country: '泰国', contacts: ['黄启龙', '朱会明'], emails: ['qilonghuang@kn.group', 'brightonzhu@kn.group'] },
  ph: { country: '菲律宾', contacts: ['汤伟', '陈江川'], emails: ['simontang@kn.group', 'jiangchuanchen@kn.group'] },
  pk: { country: '巴基斯坦', contacts: ['余红叶', '穆晋杰'], emails: ['adamyu@kn.group', 'moonmu@kn.group'] },
  mx: { country: '墨西哥', contacts: ['吴奎', '邓保保'], emails: ['kuiwu@kn.group', 'enzodeng@kn.group'] },
};

function textFromHttp(item) {
  for (const key of ['data', 'body', 'response']) {
    if (typeof item[key] === 'string') return item[key];
  }
  if (typeof item === 'string') return item;
  return '';
}

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
  if (!rows.length) return { headers: [], rows: [] };
  const headers = rows[0].map((cell) => String(cell || '').trim());
  return {
    headers,
    rows: rows.slice(1).map((cells, index) => {
      const obj = { __rowNumber: index + 2 };
      headers.forEach((header, columnIndex) => {
        obj[header] = String(cells[columnIndex] || '').trim();
      });
      return obj;
    }),
  };
}

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

function toCsv(headers, rows) {
  const visibleHeaders = headers.filter((header) => header !== '__rowNumber');
  return '\uFEFF' + [
    visibleHeaders.map(csvEscape).join(','),
    ...rows.map((row) => visibleHeaders.map((header) => csvEscape(row[header])).join(',')),
  ].join('\n') + '\n';
}

function first(row, keys) {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') return String(value).trim();
  }
  return '';
}

function splitPeople(value) {
  return String(value || '')
    .split(/[、,，;；/\\|\n\r\t]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeAccount(value) {
  return String(value || '').trim().replace(/^u_/i, '').toLowerCase();
}

function canonicalSheet(value) {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return '';
  if (/中国|china|starrocks_cn|\bcn\b/.test(text)) return 'cn';
  if (/印尼|印度尼西亚|indonesia|starrocks_ine|starrocks_id|\bine\b|\bid\b/.test(text)) return 'ine';
  if (/泰国|thailand|starrocks_th|\bth\b/.test(text)) return 'th';
  if (/菲律宾|philippines|starrocks_ph|\bph\b/.test(text)) return 'ph';
  if (/巴基斯坦|pakistan|starrocks_pak|starrocks_pk|\bpak\b|\bpk\b/.test(text)) return 'pk';
  if (/墨西哥|mexico|starrocks_mex|starrocks_mx|\bmex\b|\bmx\b/.test(text)) return 'mx';
  return text;
}

function ensureColumn(headers, candidates) {
  let key = candidates.find((candidate) => headers.includes(candidate));
  if (!key) {
    key = candidates[0];
    headers.push(key);
  }
  return key;
}

if (!fs.existsSync(CONTACT_CSV_PATH)) {
  return [{
    json: {
      ok: false,
      error: 'CONTACT_CSV_NOT_FOUND_AFTER_GIT_PULL',
      contactCsvPath: CONTACT_CSV_PATH,
      updateCount: 0,
      shouldPush: false,
      message: 'GitHub 仓库已拉取，但联系人 CSV 不存在，请检查仓库路径。'
    }
  }];
}

const formRaw = $('Fetch Form Responses CSV').first().json || {};
const form = parseCsv(textFromHttp(formRaw));
const contactCsvText = fs.readFileSync(CONTACT_CSV_PATH, 'utf8');
const contactTable = parseCsv(contactCsvText);

const countryKey = ensureColumn(contactTable.headers, ['国家', 'country']);
const accountKey = ensureColumn(contactTable.headers, ['账号', 'account', 'user', '用户']);
const departmentKey = ensureColumn(contactTable.headers, ['数据开发组', '部门', 'department', 'dept']);
const contactKey = ensureColumn(contactTable.headers, ['联系人', 'contacts', 'contact']);
const emailKey = ensureColumn(contactTable.headers, ['邮箱', 'emails', 'email']);
const remarkKey = ensureColumn(contactTable.headers, ['备注', 'remark', 'remarks']);

const rowByKey = new Map();
for (const row of contactTable.rows) {
  const sheet = canonicalSheet(row[countryKey]);
  const account = normalizeAccount(row[accountKey]);
  if (sheet && account) rowByKey.set(sheet + '::' + account, row);
}

const latestByKey = new Map();
for (const row of form.rows) {
  const sheet = canonicalSheet(first(row, ['国家', 'country', 'sheet', '集群', 'cluster']));
  const account = normalizeAccount(first(row, ['账号', 'account', 'user', '用户']));
  if (!sheet || !account) continue;
  latestByKey.set(sheet + '::' + account, row);
}

const applied = [];
const skipped = [];
for (const [key, formRow] of latestByKey.entries()) {
  const [sheet, account] = key.split('::');
  const targetRow = rowByKey.get(key);
  const owner = countryOwners[sheet];
  if (!owner) {
    skipped.push({ sheet, account, reason: '国家无法识别' });
    continue;
  }
  if (!targetRow) {
    skipped.push({ sheet, account, reason: '联系人 CSV 未找到该账号，未追加，避免误写' });
    continue;
  }

  const oldDepartment = targetRow[departmentKey] || '';
  const oldContacts = targetRow[contactKey] || '';
  const oldEmails = targetRow[emailKey] || '';
  const oldRemark = targetRow[remarkKey] || '';
  const newDepartment = first(formRow, ['部门', '数据开发组', 'department', 'dept']) || oldDepartment;
  const rawContacts = first(formRow, ['修改后联系人', '联系人', 'contacts', 'contact']);
  const rawEmails = first(formRow, ['修改后邮箱', '邮箱', 'emails', 'email']);

  let contacts = splitPeople(rawContacts);
  let emails = splitPeople(rawEmails);
  let defaultedToCountryOwner = false;
  if (!contacts.length) {
    contacts = owner.contacts;
    emails = owner.emails;
    defaultedToCountryOwner = true;
  } else if (!emails.length) {
    skipped.push({ sheet, account, reason: '填写了修改后联系人但修改后邮箱为空，未更新以避免联系人和邮箱不匹配' });
    continue;
  }

  const finalContacts = contacts.join('、');
  const finalEmails = emails.join('、');
  const fallbackRemark = '表单未填写修改后联系人，已兜底通知国家负责人；请国家负责人自行确认实际负责人并通过联系人调整表单补充。';
  const finalRemark = defaultedToCountryOwner
    ? (oldRemark && !oldRemark.includes('表单未填写修改后联系人') ? oldRemark + '；' + fallbackRemark : (oldRemark || fallbackRemark))
    : oldRemark;
  const changed = newDepartment !== oldDepartment || finalContacts !== oldContacts || finalEmails !== oldEmails || finalRemark !== oldRemark;
  if (!changed) {
    skipped.push({ sheet, account, reason: '内容无变化' });
    continue;
  }

  targetRow[departmentKey] = newDepartment;
  targetRow[contactKey] = finalContacts;
  targetRow[emailKey] = finalEmails;
  targetRow[remarkKey] = finalRemark;
  applied.push({
    country: owner.country,
    sheet,
    account,
    rowNumber: targetRow.__rowNumber,
    oldDepartment,
    oldContacts,
    oldEmails,
    oldRemark,
    newDepartment,
    newContacts: finalContacts,
    newEmails: finalEmails,
    newRemark: finalRemark,
    defaultedToCountryOwner,
    formTimestamp: first(formRow, ['时间戳记', 'timestamp', 'Timestamp']),
  });
}

if (applied.length) {
  const outputCsv = toCsv(contactTable.headers, contactTable.rows);
  fs.writeFileSync(CONTACT_CSV_PATH, outputCsv, 'utf8');
}

return [{
  json: {
    ok: true,
    contactCsvPath: CONTACT_CSV_PATH,
    formRows: form.rows.length,
    latestUpdateKeys: latestByKey.size,
    updateCount: applied.length,
    shouldPush: applied.length > 0,
    skippedCount: skipped.length,
    applied,
    skipped,
    note: applied.length
      ? '已覆盖写回仓库内联系人 CSV，下一步会 git commit/push。'
      : '没有需要写入的变更，跳过 git commit/push。'
  }
}];
`;

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

const pushRepoCommand = `bash -lc 'set -euo pipefail
REPO_DIR="${REPO_DIR}"
cd "$REPO_DIR"
git config user.name "n8n-contact-sync"
git config user.email "n8n-contact-sync@kn.group"
git add "${CONTACT_CSV_RELATIVE_PATH}"
if git diff --cached --quiet; then
  echo "no changes to commit"
  exit 0
fi
git commit -m "chore: sync alert contact mapping from form"
git push origin main
'`;

const workflow = {
  name: "异常通知联系人表单同步-拉取GitHub仓库更新CSV",
  nodes: [
    {
      parameters: {
        rule: { interval: [{ field: "cronExpression", expression: "0 0 12 * * *" }] },
      },
      type: "n8n-nodes-base.scheduleTrigger",
      typeVersion: 1.2,
      position: [-900, 0],
      id: "71e998da-ccf6-46a8-9e38-0ecdebedcdb9",
      name: "每天12点触发",
    },
    {
      parameters: {},
      type: "n8n-nodes-base.manualTrigger",
      typeVersion: 1,
      position: [-900, 180],
      id: "409ddbd3-cd5a-4bb5-86a3-95ad2f694483",
      name: "手动测试触发",
    },
    {
      parameters: { command: pullRepoCommand },
      type: "n8n-nodes-base.executeCommand",
      typeVersion: 1,
      position: [-620, 80],
      id: "4b8b10e1-07be-4f0d-aa15-72ddfc363cc7",
      name: "Pull GitHub Repo",
      notesInFlow: true,
      notes: `n8n 本机需要安装 git，并配置可读写 ${REPO_URL} 的 SSH key。仓库会放在 ${REPO_DIR}。`,
    },
    {
      parameters: {
        method: "GET",
        url: `https://docs.google.com/spreadsheets/d/${FORM_SPREADSHEET_ID}/export?format=csv&gid=${FORM_GID}`,
        responseFormat: "text",
        options: { timeout: 30000 },
      },
      type: "n8n-nodes-base.httpRequest",
      typeVersion: 4.4,
      position: [-340, 80],
      id: "dfca2a3c-7e21-45f9-854d-1864e20311a2",
      name: "Fetch Form Responses CSV",
    },
    {
      parameters: { jsCode: updateCsvCode },
      type: "n8n-nodes-base.code",
      typeVersion: 2,
      position: [-60, 80],
      id: "f1052ff0-2750-44b4-a9b8-08f65d82de73",
      name: "Update Repo Contact CSV",
      notesInFlow: true,
      notes: "需要 n8n 环境变量 NODE_FUNCTION_ALLOW_BUILTIN=fs。只覆盖仓库内单个 CSV 文件。",
    },
    {
      parameters: {
        conditions: {
          boolean: [{ value1: "={{ $json.shouldPush }}", value2: true }],
        },
        options: {},
      },
      type: "n8n-nodes-base.if",
      typeVersion: 2,
      position: [220, 80],
      id: "cf34d889-6671-4654-90ba-b7daac244fc3",
      name: "Has CSV Changes?",
    },
    {
      parameters: { command: pushRepoCommand },
      type: "n8n-nodes-base.executeCommand",
      typeVersion: 1,
      position: [500, -20],
      id: "f57051e1-b5ff-4fd4-9426-ab9b4a153474",
      name: "Commit And Push CSV",
      notesInFlow: true,
      notes: "只有 CSV 有变更时才会提交并推送到 GitHub main 分支。",
    },
  ],
  connections: {
    "每天12点触发": { main: [[{ node: "Pull GitHub Repo", type: "main", index: 0 }]] },
    "手动测试触发": { main: [[{ node: "Pull GitHub Repo", type: "main", index: 0 }]] },
    "Pull GitHub Repo": { main: [[{ node: "Fetch Form Responses CSV", type: "main", index: 0 }]] },
    "Fetch Form Responses CSV": { main: [[{ node: "Update Repo Contact CSV", type: "main", index: 0 }]] },
    "Update Repo Contact CSV": { main: [[{ node: "Has CSV Changes?", type: "main", index: 0 }]] },
    "Has CSV Changes?": { main: [[{ node: "Commit And Push CSV", type: "main", index: 0 }], []] },
  },
  pinData: {},
  settings: { executionOrder: "v1" },
  active: false,
  versionId: "50c53479-5524-4201-98f6-0cf6394a5c9a",
  id: "daily-contact-form-sync-github-repo-csv",
  tags: [],
};

const outputDir = path.resolve("outputs");
fs.mkdirSync(outputDir, { recursive: true });
const outputPath = path.join(outputDir, "n8n_daily_contact_form_sync_pull_repo_csv.workflow.json");
fs.writeFileSync(outputPath, JSON.stringify(workflow, null, 2) + "\n");
console.log(outputPath);
