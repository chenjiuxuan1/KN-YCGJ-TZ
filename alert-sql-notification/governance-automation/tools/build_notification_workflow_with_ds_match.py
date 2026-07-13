#!/usr/bin/env python3
"""Inject DS task matching nodes into the current n8n notification workflow."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_CANDIDATES = [
    ROOT / "outputs" / "sql优化_部门账号联系人通知_DS匹配增强版.json",
    Path("/Users/jiangchuanchen/Documents/Codex/2026-07-01/n8n-sql-starrocks-sql-n8n-ai/outputs/sql优化_部门账号联系人通知_DS匹配增强版.json"),
    Path("/Users/jiangchuanchen/Downloads/sql优化_部门账号联系人通知 (3).json"),
    Path("/Users/jiangchuanchen/Downloads/sql优化_部门账号联系人通知 (2).json"),
    Path("/Users/jiangchuanchen/Downloads/sql优化_部门账号联系人通知.json"),
]
OUTPUT = ROOT / "outputs" / "sql优化_部门账号联系人通知_DS匹配增强版.json"


DS_MATCH_GATE_EXPRESSION = """={{ (() => {
  const base = $json || {};
  const evidence = base.evidence || {};
  const queryContext = evidence.queryContext || {};
  const alert = evidence.alert || {};
  const norm = (value) => String(value || '').trim().toLowerCase();
  const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(norm(value));
  const user = norm(base.user || queryContext.user || alert.user);
  if (user) return looksSystemAccount(user);
  return [base.executor, base.account, base.dbUser, queryContext.executor, queryContext.account, queryContext.dbUser, alert.executor]
    .some((value) => looksSystemAccount(value));
})() }}"""


DS_MATCH_JS = r"""const safeFirst = (nodeName) => {
  try {
    const result = $(nodeName).first();
    return result && result.json ? result.json : null;
  } catch (error) {
    return null;
  }
};

const base = safeFirst('Execute Skill Prep') || {};
const inputRows = $input.all().map((item) => item.json || {}).filter((row) => row && Object.keys(row).length > 0);

function looksSystemAccount(value) {
  return /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(String(value || '').trim().toLowerCase());
}

function shouldMatchDsForAccount(row) {
  const evidence = row.evidence || {};
  const queryContext = evidence.queryContext || {};
  const alert = evidence.alert || {};
  const user = String(row.user || queryContext.user || alert.user || '').trim().toLowerCase();
  if (user) return looksSystemAccount(user);
  return [row.executor, row.account, row.dbUser, queryContext.executor, queryContext.account, queryContext.dbUser, alert.executor]
    .some((value) => looksSystemAccount(value));
}

if (!shouldMatchDsForAccount(base)) {
  return [{ json: {
    ...base,
    dsTaskMatchOk: false,
    dsTaskMatchRequired: false,
    dsTaskMatchMissingNeedsRecord: false,
    dsTaskMissingNotice: '',
    dsTaskMatchInfo: 'skip-personal-account',
    dsTaskCandidateCount: 0,
  }}];
}

const DROP_PREFIX_RE = /^\s*drop\s+table\s+(?:if\s+exists\s+)?[`"]?[\w.]+\s*;\s*/i;
const ACTION_RE = /\b(create|insert|update|delete|replace|alter|drop|truncate)\b/i;
const TABLE_RE = /\b(?:from|join|into|overwrite|update|table)\s+([`"]?[a-zA-Z_][\w.]*)/ig;
const NON_TABLE = new Set(['select', 'table', 'values', 'if', 'exists', 'as', 'where']);

function normalizeSql(sql) {
  let text = String(sql || '');
  text = text.replace(/--[^\n]*/g, ' ');
  text = text.replace(/\/\*[\s\S]*?\*\//g, ' ');
  text = text.toLowerCase().split(/\s+/).filter(Boolean).join(' ');
  while (DROP_PREFIX_RE.test(text)) text = text.replace(DROP_PREFIX_RE, '');
  return text;
}

function extractActionTables(sqlNorm) {
  if (!sqlNorm) return { action: '', tables: [] };
  const actionMatch = sqlNorm.match(ACTION_RE);
  const action = actionMatch ? actionMatch[1].toLowerCase() : String(sqlNorm.split(' ', 1)[0] || '').toLowerCase();
  const tables = new Set();
  TABLE_RE.lastIndex = 0;
  let match;
  while ((match = TABLE_RE.exec(sqlNorm)) !== null) {
    const table = String(match[1] || '').replace(/^[`"]|[`"]$/g, '');
    if (table && !NON_TABLE.has(table)) tables.add(table);
  }
  return { action, tables: Array.from(tables).sort() };
}

function arraySubset(left, right) {
  const rightSet = new Set(right);
  return left.every((item) => rightSet.has(item));
}

function sameSet(left, right) {
  return left.length === right.length && arraySubset(left, right);
}

function candidateSql(row) {
  return String(
    row.sql_content
    || row.sqlContent
    || row.stmt
    || row.script_content
    || row.raw_script
    || row.sql_text
    || row.script_text
    || row.statement_text
    || row.resource_list
    || row.script
    || ''
  ).trim();
}

function countryNameFromCluster(cluster) {
  const value = String(cluster || '').toLowerCase();
  if (value.includes('starrocks_ine') || value === 'ine') return '印尼';
  if (value.includes('starrocks_pak') || value === 'pak') return '巴基斯坦';
  if (value.includes('starrocks_ph') || value === 'ph') return '菲律宾';
  if (value.includes('starrocks_th') || value === 'th') return '泰国';
  if (value.includes('starrocks_mex') || value === 'mex') return '墨西哥';
  if (value.includes('starrocks_cn') || value === 'cn') return '中国';
  return '';
}

const sourceSql = String(
  ((base.evidence || {}).queryContext || {}).sqlText
  || base.sqlText
  || base.originalSql
  || ((base.aiResult || {}).optimizedSql)
  || ''
);
const sourceNorm = normalizeSql(sourceSql);
const source = extractActionTables(sourceNorm);

const remoteBest = inputRows.find((row) => {
  if (!row) return false;
  const hasLocation = Boolean(row.project_name || row.workflow_name || row.task_name);
  const fromRemoteMatcher = Boolean(row.ds_match_candidate_success || row.ds_match_remote_info || row.ds_match_confidence);
  return hasLocation && fromRemoteMatcher;
});

if (remoteBest) {
  const dsInfo = {
    project: String(remoteBest.project_name || '').trim(),
    workflow: String(remoteBest.workflow_name || '').trim(),
    task: String(remoteBest.task_name || '').trim(),
    workflowOwner: String(remoteBest.workflow_owner || '').trim(),
    taskCreator: String(remoteBest.task_creator || '').trim(),
    countryName: countryNameFromCluster(base.cluster || base.country || remoteBest.ds_match_candidate_country),
    matchInfo: String(remoteBest.ds_match_remote_info || remoteBest.ds_match_info || 'remote-candidate').trim(),
    confidence: String(remoteBest.ds_match_confidence || '').trim(),
    action: source.action,
    tables: source.tables,
  };

  return [{ json: {
    ...base,
    dsTaskMatchOk: true,
    dsTaskMatchRequired: true,
    dsTaskMatchMissingNeedsRecord: false,
    dsTaskMissingNotice: '',
    dsTaskMatchInfo: dsInfo.matchInfo,
    dsTaskMatchConfidence: dsInfo.confidence,
    dsTaskMatchAction: source.action,
    dsTaskMatchTables: source.tables,
    dsTaskCandidateCount: Number(remoteBest.ds_match_candidate_count || inputRows.length || 1),
    dsInfo,
    dsProject: dsInfo.project,
    dsWorkflow: dsInfo.workflow,
    dsTask: dsInfo.task,
    dsWorkflowOwner: dsInfo.workflowOwner,
    dsTaskCreator: dsInfo.taskCreator,
    dsCountryName: dsInfo.countryName,
  }}];
}

const candidates = inputRows
  .filter((row) => candidateSql(row))
  .map((row) => {
    const parsed = extractActionTables(normalizeSql(candidateSql(row)));
    return { ...row, _action: parsed.action, _tables: parsed.tables };
  });

let best = null;
let matchInfo = 'no-match';
if (!source.action || !source.tables.length) {
  matchInfo = 'no-action-or-table';
} else {
  const exact = [];
  const superset = [];
  for (const candidate of candidates) {
    if (candidate._action !== source.action || !arraySubset(source.tables, candidate._tables)) continue;
    if (sameSet(candidate._tables, source.tables)) exact.push(candidate);
    else superset.push(candidate);
  }
  if (exact.length) {
    best = exact[0];
    matchInfo = 'exact(' + exact.length + ')';
  } else if (superset.length) {
    superset.sort((a, b) => {
      const extraA = a._tables.filter((table) => !source.tables.includes(table)).length;
      const extraB = b._tables.filter((table) => !source.tables.includes(table)).length;
      return extraA - extraB;
    });
    best = superset[0];
    const extra = best._tables.filter((table) => !source.tables.includes(table)).length;
    matchInfo = 'superset(+' + extra + ')';
  }
}

if (!best) {
  return [{ json: {
    ...base,
    dsTaskMatchOk: false,
    dsTaskMatchRequired: true,
    dsTaskMatchMissingNeedsRecord: true,
    dsTaskMissingNotice: '当前账号属于系统/部门/调度账号，但未匹配到对应 DS 项目 / 工作流 / 任务。需要人工确认其执行位置，如果有时间可以将执行位置发送给陈江川，本次已同步发送给江川协助跟进。',
    dsTaskMatchInfo: matchInfo,
    dsTaskMatchAction: source.action,
    dsTaskMatchTables: source.tables,
    dsTaskCandidateCount: candidates.length,
  }}];
}

const dsInfo = {
  project: String(best.project_name || '').trim(),
  workflow: String(best.workflow_name || '').trim(),
  task: String(best.task_name || '').trim(),
  workflowOwner: String(best.workflow_owner || '').trim(),
  taskCreator: String(best.task_creator || '').trim(),
  countryName: countryNameFromCluster(base.cluster || base.country),
  matchInfo,
  action: source.action,
  tables: source.tables,
};

return [{ json: {
  ...base,
  dsTaskMatchOk: true,
  dsTaskMatchRequired: true,
  dsTaskMatchMissingNeedsRecord: false,
  dsTaskMissingNotice: '',
  dsTaskMatchInfo: matchInfo,
  dsTaskMatchAction: source.action,
  dsTaskMatchTables: source.tables,
  dsTaskCandidateCount: candidates.length,
  dsInfo,
  dsProject: dsInfo.project,
  dsWorkflow: dsInfo.workflow,
  dsTask: dsInfo.task,
  dsWorkflowOwner: dsInfo.workflowOwner,
  dsTaskCreator: dsInfo.taskCreator,
  dsCountryName: dsInfo.countryName,
}}];"""


def node_by_name(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def resolve_input() -> Path:
    for path in INPUT_CANDIDATES:
        if path.exists():
            return path
    expected = ", ".join(str(path) for path in INPUT_CANDIDATES)
    raise FileNotFoundError(f"Notification workflow JSON not found. Expected one of: {expected}")


def add_or_replace_node(workflow: dict, new_node: dict) -> None:
    workflow["nodes"] = [node for node in workflow["nodes"] if node["name"] != new_node["name"]]
    workflow["nodes"].append(new_node)


def connect(workflow: dict, source: str, targets: list[str]) -> None:
    workflow.setdefault("connections", {})[source] = {
        "main": [[{"node": target, "type": "main", "index": 0} for target in targets]]
    }


def connect_if(workflow: dict, source: str, true_target: str, false_target: str) -> None:
    workflow.setdefault("connections", {})[source] = {
        "main": [
            [{"node": true_target, "type": "main", "index": 0}],
            [{"node": false_target, "type": "main", "index": 0}],
        ]
    }


def patch_sidecar_message(js_code: str) -> str:
    if "safeNodeJson('Merge DS Task Match')" not in js_code:
        js_code = js_code.replace(
            "const base = $('Build Langfuse Batch').first().json || {};",
            "const safeNodeJson = (nodeName) => {\n"
            "  try {\n"
            "    const node = $(nodeName).first();\n"
            "    return node && node.json ? node.json : {};\n"
            "  } catch (error) {\n"
            "    return {};\n"
            "  }\n"
            "};\n"
            "const base = {\n"
            "  ...safeNodeJson('Build Langfuse Batch'),\n"
            "  ...safeNodeJson('Merge DS Task Match'),\n"
            "};",
        )
    if "const looksSystemAccount = (value)" not in js_code:
        js_code = js_code.replace(
            "const countryOwnerFallbackNotice = sanitize(base.countryOwnerFallbackNotice);",
            "const countryOwnerFallbackNotice = sanitize(base.countryOwnerFallbackNotice);\n"
            "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(sanitize(value).toLowerCase());\n"
            "const shouldMatchDsForAccount = (row) => {\n"
            "  const evidenceObj = row.evidence || {};\n"
            "  const queryContextObj = evidenceObj.queryContext || {};\n"
            "  const alertObj = evidenceObj.alert || {};\n"
            "  const userValue = sanitize(row.user || queryContextObj.user || alertObj.user).toLowerCase();\n"
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n"
            "};",
        )
    js_code = js_code.replace(
        "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n  ?",
        "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n  && shouldMatchDsForAccount(base)\n  ?",
    )
    js_code = js_code.replace(
        "if (base.dsTaskMatchMissingNeedsRecord) {\n  notifyEmails = uniq([...notifyEmails, notifyConfig.dsMissingCcEmail || notifyConfig.fallbackEmail || 'jiangchuanchen@kn.group']);\n}",
        "if (base.dsTaskMatchMissingNeedsRecord && (() => {\n"
        "  const evidenceObj = base.evidence || {};\n"
        "  const queryContextObj = evidenceObj.queryContext || {};\n"
        "  const alertObj = evidenceObj.alert || {};\n"
        "  const looks = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(sanitize(value).toLowerCase());\n"
        "  const userValue = sanitize(base.user || queryContextObj.user || alertObj.user).toLowerCase();\n"
        "  if (userValue) return looks(userValue);\n"
        "  return [base.executor, base.account, base.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
        "    .some((value) => looks(value));\n"
        "})()) {\n"
        "  notifyEmails = uniq([...notifyEmails, notifyConfig.dsMissingCcEmail || notifyConfig.fallbackEmail || 'jiangchuanchen@kn.group']);\n"
        "}",
    )
    js_code = js_code.replace(
        "if (base.dsTaskMatchMissingNeedsRecord && shouldMatchDsForAccount(base)) {\n  notifyEmails = uniq([...notifyEmails, notifyConfig.dsMissingCcEmail || notifyConfig.fallbackEmail || 'jiangchuanchen@kn.group']);\n}",
        "if (base.dsTaskMatchMissingNeedsRecord && (() => {\n"
        "  const evidenceObj = base.evidence || {};\n"
        "  const queryContextObj = evidenceObj.queryContext || {};\n"
        "  const alertObj = evidenceObj.alert || {};\n"
        "  const looks = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(sanitize(value).toLowerCase());\n"
        "  const userValue = sanitize(base.user || queryContextObj.user || alertObj.user).toLowerCase();\n"
        "  if (userValue) return looks(userValue);\n"
        "  return [base.executor, base.account, base.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
        "    .some((value) => looks(value));\n"
        "})()) {\n"
        "  notifyEmails = uniq([...notifyEmails, notifyConfig.dsMissingCcEmail || notifyConfig.fallbackEmail || 'jiangchuanchen@kn.group']);\n"
        "}",
    )
    if "dsMissingCcEmail" not in js_code:
        js_code = js_code.replace(
            "const notifyEmails = uniq(Array.isArray(base.notifyEmails) && base.notifyEmails.length ? base.notifyEmails : [base.notifyEmail || 'jiangchuanchen@kn.group']);",
            "let notifyEmails = uniq(Array.isArray(base.notifyEmails) && base.notifyEmails.length ? base.notifyEmails : [base.notifyEmail || 'jiangchuanchen@kn.group']);\n"
            "if (base.dsTaskMatchMissingNeedsRecord) {\n"
            "  notifyEmails = uniq([...notifyEmails, notifyConfig.dsMissingCcEmail || notifyConfig.fallbackEmail || 'jiangchuanchen@kn.group']);\n"
            "}",
        )
    if "dsMissingNoticeText" not in js_code:
        js_code = js_code.replace(
            "const countryOwnerFallbackNotice = sanitize(base.countryOwnerFallbackNotice);",
            "const countryOwnerFallbackNotice = sanitize(base.countryOwnerFallbackNotice);\n"
            "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(sanitize(value).toLowerCase());\n"
            "const shouldMatchDsForAccount = (row) => {\n"
            "  const evidenceObj = row.evidence || {};\n"
            "  const queryContextObj = evidenceObj.queryContext || {};\n"
            "  const alertObj = evidenceObj.alert || {};\n"
            "  const userValue = sanitize(row.user || queryContextObj.user || alertObj.user).toLowerCase();\n"
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n"
            "};\n"
            "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n"
            "  && shouldMatchDsForAccount(base)\n"
            "  ? 'DS 归属缺失提醒：\\n当前账号属于系统/部门/调度账号，但未匹配到对应 DS 项目 / 工作流 / 任务。需要人工确认其执行位置，如果有时间可以将执行位置发送给陈江川，本次已同步发送给江川协助跟进。\\n\\n'\n"
            "  : '';",
        )
        js_code = js_code.replace(
            "  + '告警原因：\\n'\n",
            "  + dsMissingNoticeText\n  + '告警原因：\\n'\n",
        )
    if "dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord" not in js_code:
        js_code = js_code.replace(
            "      notifyEmail: notifyEmails.join(','),\n      sidecarShouldSend:",
            "      notifyEmail: notifyEmails.join(','),\n"
            "      notifyEmails,\n"
            "      dsTaskMatchRequired: !!base.dsTaskMatchRequired,\n"
            "      dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord && shouldMatchDsForAccount(base),\n"
            "      dsTaskMissingNotice: sanitize(base.dsTaskMissingNotice),\n"
            "      sidecarShouldSend:",
        )
        js_code = js_code.replace(
            "    notifyEmail: entry.email,\n    sidecarShouldSend:",
            "    notifyEmail: entry.email,\n"
            "    notifyEmails,\n"
            "    dsTaskMatchRequired: !!base.dsTaskMatchRequired,\n"
            "    dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord && shouldMatchDsForAccount(base),\n"
            "    dsTaskMissingNotice: sanitize(base.dsTaskMissingNotice),\n"
            "    sidecarShouldSend:",
        )
    js_code = js_code.replace(
        "dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord,",
        "dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord && shouldMatchDsForAccount(base),",
    )
    insert = (
        "  + (base.dsTaskMatchOk ? 'SQL 所属 DS 任务：\\n'"
        " + (sanitize(base.dsCountryName) ? sanitize(base.dsCountryName) + ' DS 调度' : 'DS 调度')"
        " + '「' + sanitize(base.dsProject) + '」-「' + sanitize(base.dsWorkflow) + '」-「' + sanitize(base.dsTask) + '」任务\\n'"
        " + '- 负责人：' + sanitize(base.dsWorkflowOwner) + '\\n'"
        " + '- 创建人：' + sanitize(base.dsTaskCreator) + '\\n\\n' : '')\n"
    )
    marker = "  + '告警原因：\\n'\n"
    if "SQL 所属 DS 任务" in js_code or "DS 匹配信息" in js_code:
        return js_code
    return js_code.replace(marker, insert + marker)


def patch_webhook_response(js_code: str) -> str:
    js_code = js_code.replace(
        "const base = $('Build Langfuse Batch').first().json || {};\nconst notify = $json || {};",
        "const safeNodeJson = (nodeName) => {\n"
        "  try {\n"
        "    const node = $(nodeName).first();\n"
        "    return node && node.json ? node.json : {};\n"
        "  } catch (error) {\n"
        "    return {};\n"
        "  }\n"
        "};\n"
        "const notify = $json || {};\n"
        "const base = {\n"
        "  ...safeNodeJson('Build Langfuse Batch'),\n"
        "  ...safeNodeJson('Merge DS Task Match'),\n"
        "  ...safeNodeJson('Build Sidecar Payload'),\n"
            "};",
    )
    if "const looksSystemAccount = (value)" not in js_code:
        js_code = js_code.replace(
            "const contactUpdateFormUrl = textOf(notifyConfig.contactUpdateFormUrl).trim();",
            "const contactUpdateFormUrl = textOf(notifyConfig.contactUpdateFormUrl).trim();\n"
            "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(textOf(value).trim().toLowerCase());\n"
            "const shouldMatchDsForAccount = (row) => {\n"
            "  const evidenceObj = row.evidence || {};\n"
            "  const queryContextObj = evidenceObj.queryContext || {};\n"
            "  const alertObj = evidenceObj.alert || {};\n"
            "  const userValue = textOf(row.user || queryContextObj.user || alertObj.user).trim().toLowerCase();\n"
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n"
            "};",
        )
    js_code = js_code.replace(
        "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n  ?",
        "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n  && shouldMatchDsForAccount(base)\n  ?",
    )
    if "const dsInfoText" not in js_code:
        js_code = js_code.replace(
            "const contactUpdateFormUrl = textOf(notifyConfig.contactUpdateFormUrl).trim();",
            "const contactUpdateFormUrl = textOf(notifyConfig.contactUpdateFormUrl).trim();\n"
            "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(textOf(value).trim().toLowerCase());\n"
            "const shouldMatchDsForAccount = (row) => {\n"
            "  const evidenceObj = row.evidence || {};\n"
            "  const queryContextObj = evidenceObj.queryContext || {};\n"
            "  const alertObj = evidenceObj.alert || {};\n"
            "  const userValue = textOf(row.user || queryContextObj.user || alertObj.user).trim().toLowerCase();\n"
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n"
            "};\n"
            "const dsInfoText = base.dsTaskMatchOk ? ('SQL 所属 DS 任务：\\n'\n"
            "  + (textOf(base.dsCountryName) ? textOf(base.dsCountryName) + ' DS 调度' : 'DS 调度')\n"
            "  + '「' + textOf(base.dsProject) + '」-「' + textOf(base.dsWorkflow) + '」-「' + textOf(base.dsTask) + '」任务\\n'\n"
            "  + '- 负责人：' + textOf(base.dsWorkflowOwner) + '\\n'\n"
            "  + '- 创建人：' + textOf(base.dsTaskCreator) + '\\n\\n') : '';\n"
            "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n"
            "  && shouldMatchDsForAccount(base)\n"
            "  ? 'DS 归属缺失提醒：\\n当前账号属于系统/部门/调度账号，但未匹配到对应 DS 项目 / 工作流 / 任务。需要人工确认其执行位置，如果有时间可以将执行位置发送给陈江川，本次已同步发送给江川协助跟进。\\n\\n'\n"
            "  : '';",
        )
        js_code = js_code.replace("  + '告警原因：\\n'\n", "  + dsInfoText\n  + dsMissingNoticeText\n  + '告警原因：\\n'\n")
    elif "dsMissingNoticeText" not in js_code:
        js_code = js_code.replace(
            "const backendSuggestionText = '异常查询：\\n'",
            "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(textOf(value).trim().toLowerCase());\n"
            "const shouldMatchDsForAccount = (row) => {\n"
            "  const evidenceObj = row.evidence || {};\n"
            "  const queryContextObj = evidenceObj.queryContext || {};\n"
            "  const alertObj = evidenceObj.alert || {};\n"
            "  const userValue = textOf(row.user || queryContextObj.user || alertObj.user).trim().toLowerCase();\n"
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n"
            "};\n"
            "const dsMissingNoticeText = base.dsTaskMatchMissingNeedsRecord\n"
            "  && shouldMatchDsForAccount(base)\n"
            "  ? 'DS 归属缺失提醒：\\n当前账号属于系统/部门/调度账号，但未匹配到对应 DS 项目 / 工作流 / 任务。需要人工确认其执行位置，如果有时间可以将执行位置发送给陈江川，本次已同步发送给江川协助跟进。\\n\\n'\n"
            "  : '';\n"
            "const backendSuggestionText = '异常查询：\\n'",
        )
        js_code = js_code.replace("  + dsInfoText\n  + '告警原因：\\n'\n", "  + dsInfoText\n  + dsMissingNoticeText\n  + '告警原因：\\n'\n")
    if "dsTaskMatchMissingNeedsRecord:" not in js_code:
        js_code = js_code.replace(
            "  userInfo: base.userInfo || [],",
            "  userInfo: base.userInfo || [],\n"
            "  dsTaskMatchRequired: !!base.dsTaskMatchRequired,\n"
            "  dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord,\n"
            "  dsTaskMissingNotice: textOf(base.dsTaskMissingNotice),\n"
            "  dsTaskMatchInfo: textOf(base.dsTaskMatchInfo),\n"
            "  dsTaskMatchConfidence: textOf(base.dsTaskMatchConfidence),\n"
            "  dsTaskMatchTables: base.dsTaskMatchTables || [],\n"
            "  dsTaskCandidateCount: Number(base.dsTaskCandidateCount || 0),",
        )
    if "dsTaskMatchOk:" not in js_code:
        js_code = js_code.replace(
            "  userInfo: base.userInfo || [],",
            "  userInfo: base.userInfo || [],\n"
            "  ...(base.dsTaskMatchOk ? {\n"
            "    dsTaskMatchOk: true,\n"
            "    dsProject: textOf(base.dsProject),\n"
            "    dsWorkflow: textOf(base.dsWorkflow),\n"
            "    dsTask: textOf(base.dsTask),\n"
            "    dsWorkflowOwner: textOf(base.dsWorkflowOwner),\n"
            "    dsTaskCreator: textOf(base.dsTaskCreator),\n"
            "    dsCountryName: textOf(base.dsCountryName),\n"
            "    dsTaskMatchInfo: textOf(base.dsTaskMatchInfo),\n"
            "    dsTaskMatchConfidence: textOf(base.dsTaskMatchConfidence),\n"
            "    dsTaskMatchTables: base.dsTaskMatchTables || [],\n"
            "  } : {}),",
        )
    elif "dsTaskMatchConfidence:" not in js_code:
        js_code = js_code.replace(
            "    dsTaskMatchInfo: textOf(base.dsTaskMatchInfo),\n"
            "    dsTaskMatchTables: base.dsTaskMatchTables || [],",
            "    dsTaskMatchInfo: textOf(base.dsTaskMatchInfo),\n"
            "    dsTaskMatchConfidence: textOf(base.dsTaskMatchConfidence),\n"
            "    dsTaskMatchTables: base.dsTaskMatchTables || [],",
        )
    return js_code


def main() -> None:
    workflow = json.loads(resolve_input().read_text(encoding="utf-8"))
    workflow["name"] = workflow.get("name", "") + "_DS匹配增强版"
    workflow["active"] = False

    gate_node = {
        "parameters": {
            "conditions": {
                "boolean": [
                    {
                        "value1": DS_MATCH_GATE_EXPRESSION,
                        "value2": True,
                    }
                ]
            },
            "options": {},
        },
        "id": "fb107263-c0aa-4c42-84a1-0fc0990769c2",
        "name": "Should Match DS Task?",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [45888, 13808],
        "notesInFlow": True,
        "notes": "提前过滤个人账号：只有 user/executor/account/dbUser 等字段存在类似 u_、e_、e_ds_ 这类前缀时才进入 DS 匹配。像 jiangchuanchen 这种无前缀个人账号默认不是 DS 调度，直接跳过 DS 查询，避免误匹配和无意义查询。",
    }
    match_node = {
        "parameters": {
            "workflowId": {
                "__rl": True,
                "value": "DS任务匹配候选查询_execute_workflow",
                "mode": "name",
                "cachedResultName": "DS任务匹配候选查询_execute_workflow",
            },
            "workflowInputs": {
                "mappingMode": "defineBelow",
                "value": "={{ { \"cluster\": $json.cluster || \"\", \"country\": $json.country || \"\", \"queryId\": $json.queryId || \"\", \"user\": $json.user || \"\", \"executor\": $json.executor || \"\", \"alertTime\": (($json.evidence || {}).alert || {}).alertTime || $json.alertTime || \"\", \"sqlText\": ((($json.evidence || {}).queryContext || {}).sqlText) || $json.sqlText || $json.originalSql || \"\" } }}",
            },
            "options": {},
        },
        "id": "8f75b5b1-5f2d-4b12-bf6b-6e0df6a3d3ad",
        "name": "Match DS Task Candidates",
        "type": "n8n-nodes-base.executeWorkflow",
        "typeVersion": 1.2,
        "position": [46000, 13552],
        "alwaysOutputData": True,
        "onError": "continueRegularOutput",
        "notesInFlow": True,
        "notes": "调用子 workflow：DS任务匹配候选查询_execute_workflow。子任务按国家走跳板机，在 SSH 节点机器通过 GitHub zip 拉取治理自动化代码，并查询 DS 3.4 元数据候选任务。导入后如 n8n 未自动按名称绑定，请手动选择该子 workflow。",
    }
    merge_node = {
        "parameters": {"jsCode": DS_MATCH_JS},
        "id": "a9a6b3d0-05dc-4a41-9355-8f4f61d69f23",
        "name": "Merge DS Task Match",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [46112, 13696],
        "notesInFlow": True,
        "notes": "复用 match_and_update.py 的 action + table set 匹配逻辑。匹配成功才向后续数据增加 dsProject/dsWorkflow/dsTask 等字段；匹配失败不影响原通知流程。",
    }
    add_or_replace_node(workflow, gate_node)
    add_or_replace_node(workflow, match_node)
    add_or_replace_node(workflow, merge_node)

    connect(workflow, "Execute Skill Prep", ["Should Match DS Task?"])
    connect_if(workflow, "Should Match DS Task?", "Match DS Task Candidates", "Call Qwen Chat API")
    connect(workflow, "Match DS Task Candidates", ["Merge DS Task Match"])
    connect(workflow, "Merge DS Task Match", ["Call Qwen Chat API"])
    connect(workflow, "Parse AI Result", ["Has Optimized SQL?"])

    sidecar = node_by_name(workflow, "Build Sidecar Payload")
    sidecar["parameters"]["jsCode"] = patch_sidecar_message(sidecar["parameters"]["jsCode"])

    response = node_by_name(workflow, "Build Webhook Response")
    response["parameters"]["jsCode"] = patch_webhook_response(response["parameters"]["jsCode"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
