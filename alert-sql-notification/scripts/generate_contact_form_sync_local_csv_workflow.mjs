import fs from "fs";
import path from "path";

const FORM_SPREADSHEET_ID = "16cZaIr0YupjC2P65O6Y3YdtJmznfoOqS-gq-bk1TGQI";
const FORM_GID = "998319904";

const updateLocalCsvCode = String.raw`
const fs = require('fs');

const CONTACT_CSV_PATH = '/data/alert-contact-mapping.csv';

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
      error: 'CONTACT_CSV_NOT_FOUND',
      contactCsvPath: CONTACT_CSV_PATH,
      message: '请先把初始联系人 CSV 放到 n8n 本机该路径，再运行同步流程。'
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
    skipped.push({ sheet, account, reason: '本机联系人 CSV 未找到该账号，未追加，避免误写' });
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

const outputCsv = toCsv(contactTable.headers, contactTable.rows);
fs.writeFileSync(CONTACT_CSV_PATH, outputCsv, 'utf8');

return [{
  json: {
    ok: true,
    contactCsvPath: CONTACT_CSV_PATH,
    formRows: form.rows.length,
    latestUpdateKeys: latestByKey.size,
    updateCount: applied.length,
    skippedCount: skipped.length,
    applied,
    skipped,
    note: '已覆盖写回本机单个联系人 CSV。通知流程后续只需要读取这个 CSV。'
  }
}];
`;

const workflow = {
  name: "异常通知联系人表单每日同步到本机CSV",
  nodes: [
    {
      parameters: {
        rule: {
          interval: [
            {
              field: "cronExpression",
              expression: "0 0 12 * * *",
            },
          ],
        },
      },
      type: "n8n-nodes-base.scheduleTrigger",
      typeVersion: 1.2,
      position: [-600, 0],
      id: "4530c2fe-0d64-4c92-bfd8-c2fcbb718bc7",
      name: "每天12点触发",
    },
    {
      parameters: {},
      type: "n8n-nodes-base.manualTrigger",
      typeVersion: 1,
      position: [-600, 180],
      id: "0c05e09c-67ea-4cad-9e7f-0fc6e2cebdc5",
      name: "手动测试触发",
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
      position: [-320, 80],
      id: "e9b35cc2-f326-45ca-a31f-0a3b1423b44d",
      name: "Fetch Form Responses CSV",
    },
    {
      parameters: {
        jsCode: updateLocalCsvCode,
      },
      type: "n8n-nodes-base.code",
      typeVersion: 2,
      position: [-40, 80],
      id: "c9d732d1-f278-46a4-8b48-544aaac35eca",
      name: "Update Local Contact CSV",
      notesInFlow: true,
      notes: "默认读写 /data/alert-contact-mapping.csv。n8n 需要允许 Code 节点使用 fs：NODE_FUNCTION_ALLOW_BUILTIN=fs。",
    },
  ],
  connections: {
    "每天12点触发": { main: [[{ node: "Fetch Form Responses CSV", type: "main", index: 0 }]] },
    "手动测试触发": { main: [[{ node: "Fetch Form Responses CSV", type: "main", index: 0 }]] },
    "Fetch Form Responses CSV": { main: [[{ node: "Update Local Contact CSV", type: "main", index: 0 }]] },
  },
  pinData: {},
  settings: { executionOrder: "v1" },
  active: false,
  versionId: "1fc681d4-3661-4ef7-a0f6-107d47d66caa",
  id: "daily-contact-form-sync-local-csv",
  tags: [],
};

const outputDir = path.resolve("outputs");
fs.mkdirSync(outputDir, { recursive: true });
const outputPath = path.join(outputDir, "n8n_daily_contact_form_sync_local_csv.workflow.json");
fs.writeFileSync(outputPath, JSON.stringify(workflow, null, 2) + "\n");
console.log(outputPath);
