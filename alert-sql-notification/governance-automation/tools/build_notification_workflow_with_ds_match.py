#!/usr/bin/env python3
"""Inject DS task matching nodes into the current n8n notification workflow."""

from __future__ import annotations

import json
import re
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


SYSTEM_ACCOUNT_PREFIX_RE = r"/^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/"
SYSTEM_ACCOUNT_EXACT_RE = r"/^(ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)$/"


DS_MATCH_GATE_EXPRESSION = """={{ (() => {
  const base = $json || {};
  const evidence = base.evidence || {};
  const queryContext = evidence.queryContext || {};
  const alert = evidence.alert || {};
  const norm = (value) => String(value || '').trim().toLowerCase();
  const looksSystemAccount = (value) => {
    const account = norm(value);
    return /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(account)
      || /^(ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)$/.test(account);
  };
  const allowedIps = new Set([
    '10.20.47.14', '10.20.48.14', '10.20.49.14',
    '192.168.21.236',
    '172.20.228.144', '172.20.228.145', '172.20.228.146', '172.20.228.160', '172.20.228.226', '172.20.220.165',
    '10.20.84.21', '10.20.84.22', '10.20.84.23', '10.20.84.244', '10.20.84.207', '10.20.10.12',
    '10.20.84.176', '10.20.84.177', '10.20.84.178', '10.20.84.186', '10.20.11.252',
    '192.168.20.236', '192.168.102.6', '192.168.102.7', '192.168.102.8', '192.168.102.9', '192.168.101.206',
  ]);
  const collectStrings = (value, seen = new Set()) => {
    if (value === null || value === undefined) return [];
    if (typeof value === 'string' || typeof value === 'number') return [String(value)];
    if (typeof value !== 'object' || seen.has(value)) return [];
    seen.add(value);
    const out = [];
    if (Array.isArray(value)) {
      for (const item of value) out.push(...collectStrings(item, seen));
    } else {
      for (const item of Object.values(value)) out.push(...collectStrings(item, seen));
    }
    return out;
  };
  const extractIps = (value) => String(value || '').match(/\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b/g) || [];
  const hostTexts = [
    base.hostIp, base.host, base.clientIp, base.clientHost, base.queryHost, base.feIp, base.beIp,
    queryContext.hostIp, queryContext.host, queryContext.clientIp, queryContext.clientHost, queryContext.queryHost, queryContext.feIp, queryContext.beIp,
    alert.hostIp, alert.host, alert.clientIp, alert.clientHost, alert.queryHost, alert.feIp, alert.beIp,
    base.message, base.rawMessage, alert.message, alert.rawMessage,
    ...collectStrings(alert.hostInfo || alert.hosts || base.hostInfo || base.hosts || ''),
  ];
  const hostIps = Array.from(new Set(hostTexts.flatMap(extractIps)));
  const hasHostIp = hostIps.length > 0;
  const hasAllowedHostIp = hostIps.some((ip) => allowedIps.has(ip));
  const user = norm(base.user || queryContext.user || alert.user);
  return looksSystemAccount(user) && (!hasHostIp || hasAllowedHostIp);
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
  const account = String(value || '').trim().toLowerCase();
  return /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(account)
    || /^(ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)$/.test(account);
}

function shouldMatchDsForAccount(row) {
  const evidence = row.evidence || {};
  const queryContext = evidence.queryContext || {};
  const alert = evidence.alert || {};
  const user = String(row.user || queryContext.user || alert.user || '').trim().toLowerCase();
  return looksSystemAccount(user);
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

const gateSkipped = inputRows.find((row) => {
  const meta = row.meta || {};
  const info = String(row.dsTaskMatchInfo || meta.match_info || meta.ds_host_gate_reason || '').trim();
  return (meta.ds_host_gate === 'skipped' && info !== 'missing-alert-host-ip')
    || info === 'alert-host-ip-not-in-ds-allowlist';
});

if (gateSkipped) {
  const meta = gateSkipped.meta || {};
  return [{ json: {
    ...base,
    dsTaskMatchOk: false,
    dsTaskMatchRequired: false,
    dsTaskMatchMissingNeedsRecord: false,
    dsTaskMissingNotice: '',
    dsTaskMatchInfo: String(gateSkipped.dsTaskMatchInfo || meta.match_info || meta.ds_host_gate_reason || 'skip-ds-host-gate'),
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


KN_CHAT_SEND_JS = r"""const inputItems = $input.all();
const textOf = (value) => value === null || value === undefined ? '' : String(value);
const trim = (value) => textOf(value).trim();

async function postKnChat(apiBase, token, method, body) {
  return await this.helpers.httpRequest({
    method: 'POST',
    url: `${apiBase}/bot${token}/${method}`,
    headers: { 'Content-Type': 'application/json' },
    body,
    json: true,
    returnFullResponse: true,
    timeout: 15000,
    ignoreHttpStatusErrors: true,
  });
}

async function resolveUserIdByEmail(apiBase, token, emailValue) {
  return await this.helpers.httpRequest({
    method: 'POST',
    url: `${apiBase}/bot${token}/resolveUserId?email=${encodeURIComponent(emailValue)}`,
    json: true,
    returnFullResponse: true,
    timeout: 15000,
    ignoreHttpStatusErrors: true,
  });
}

const pickChatId = (body) => {
  const seen = new Set();
  const visit = (value) => {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string' || typeof value === 'number') {
      const text = String(value).trim();
      return /^\d+$/.test(text) ? text : '';
    }
    if (typeof value !== 'object' || seen.has(value)) return '';
    seen.add(value);
    for (const key of ['user_id', 'userId', 'chat_id', 'chatId', 'id']) {
      const direct = visit(value[key]);
      if (direct) return direct;
    }
    for (const key of ['result', 'data', 'user', 'chat']) {
      const nested = visit(value[key]);
      if (nested) return nested;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        const nested = visit(item);
        if (nested) return nested;
      }
    }
    return '';
  };
  return visit(body);
};

const results = [];
for (const item of inputItems) {
  const base = (item && item.json) || {};
  const payload = base.sidecarPayload || {};
  const notifyConfig = base.notifyConfig || {};
  const apiBase = trim(notifyConfig.knChatBotApiBase || base.knChatBotApiBase || 'https://bot.kn.chat').replace(/\/+$/, '');
  const token = trim(notifyConfig.knChatBotToken || base.knChatBotToken || (typeof process !== 'undefined' && process.env ? process.env.KN_CHAT_BOT_TOKEN : ''));
  const text = trim(payload.text || payload.data || payload.message);
  const email = trim(payload.email || base.notifyEmail);
  let chatId = payload.chat_id || payload.chatId || payload.user_id || payload.userId || '';

  const resultBase = {
    ...base,
    sidecarProvider: 'kn_chat_bot',
    knChatApiBase: apiBase,
    knChatRecipientEmail: email,
    knChatRecipientChatId: chatId,
  };

  if (!base.sidecarShouldSend) {
    results.push({ json: { ...resultBase, knChatNotifyOk: false, knChatSkipped: true, knChatSkipReason: 'sidecarShouldSend=false' } });
    continue;
  }
  if (!token) {
    results.push({ json: { ...resultBase, knChatNotifyOk: false, sidecarSendOk: false, knChatError: 'KN_CHAT_BOT_TOKEN_MISSING', message: '请在 Notify Config 中配置 knChatBotToken，或在 n8n 环境变量 KN_CHAT_BOT_TOKEN 中配置 KN Chat bot token。' } });
    continue;
  }
  if (!text) {
    results.push({ json: { ...resultBase, knChatNotifyOk: false, sidecarSendOk: false, knChatError: 'KN_CHAT_TEXT_MISSING' } });
    continue;
  }

  let resolveResponse = null;
  let resolveStatusCode = null;
  if (!chatId && email) {
    resolveResponse = await resolveUserIdByEmail.call(this, apiBase, token, email);
    resolveStatusCode = resolveResponse.statusCode || resolveResponse.status || null;
    chatId = pickChatId(resolveResponse.body || '');
  }

  if (!chatId) {
    const resolveBody = resolveResponse && resolveResponse.body;
    results.push({
      json: {
        ...resultBase,
        knChatNotifyOk: false,
        sidecarSendOk: false,
        knChatError: 'KN_CHAT_CHAT_ID_MISSING',
        knChatResolveResponse: resolveBody,
        knChatResolveStatusCode: resolveStatusCode,
        knChatResolveOk: false,
        knChatResolveMode: 'query',
        message: 'KN Chat 发送失败：缺少 chat_id；个人通知需邮箱可 resolveUserId，群通知需配置群 chat_id。若 resolveUserId 返回用户不存在，通常需要该用户先和机器人对话 /start。'
      }
    });
    continue;
  }

  const sendBody = {
    chat_id: chatId,
    text,
    disable_web_page_preview: true,
  };
  const sendResponse = await postKnChat.call(this, apiBase, token, 'sendMessage', sendBody);
  const sendBodyResult = sendResponse.body || {};
  const ok = !!sendBodyResult.ok;
  const sendStatusCode = sendResponse.statusCode || sendResponse.status || null;

  results.push({
    json: {
      ...resultBase,
      sidecarChannel: base.sidecarChannel || 'kn_chat_bot',
      sidecarUrl: `${apiBase}/bot<TOKEN>/sendMessage`,
      sidecarPayload: sendBody,
      knChatRecipientChatId: chatId,
      knChatResolveResponse: resolveResponse && resolveResponse.body,
      knChatResolveStatusCode: resolveStatusCode,
      knChatResolveOk: Boolean(chatId),
      knChatResolveMode: 'query',
      knChatSendResponse: sendBodyResult,
      knChatSendStatusCode: sendStatusCode,
      knChatSendDescription: sendBodyResult.description || '',
      notifyResponse: sendBodyResult,
      knChatNotifyOk: ok,
      sidecarSendOk: ok,
      error: ok ? null : (sendBodyResult.description || sendBodyResult.error_code || 'KN_CHAT_SEND_FAILED'),
    }
  });
}
return results;"""


DEDUPE_CHECK_JS = r"""const inputItems = $input.all();
const staticData = typeof $getWorkflowStaticData === 'function'
  ? $getWorkflowStaticData('global')
  : (typeof getWorkflowStaticData === 'function' ? getWorkflowStaticData('global') : {});
const now = Date.now();
const dedupeWindowMs = 2 * 60 * 60 * 1000;
if (!staticData.queryNotifyDedupeV2 || typeof staticData.queryNotifyDedupeV2 !== 'object') {
  staticData.queryNotifyDedupeV2 = {};
}
const store = staticData.queryNotifyDedupeV2;
for (const [key, value] of Object.entries(store)) {
  const timestamp = Number(value && value.sentAt ? value.sentAt : value);
  if (!Number.isFinite(timestamp) || now - timestamp > dedupeWindowMs) {
    delete store[key];
  }
}
return inputItems.map((item) => {
  const base = (item && item.json) || {};
  const queryId = String(base.queryId || '').trim();
  const recipientEmail = String((base.sidecarPayload || {}).email || (base.sidecarPayload || {}).chat_id || (base.sidecarPayload || {}).chatId || (base.sidecarPayload || {}).botId || base.notifyEmail || '').trim().toLowerCase();
  let duplicateNotifySuppressed = false;
  let duplicateNotifyReason = '';
  const dedupeKey = queryId && recipientEmail ? queryId + '::' + recipientEmail : queryId;
  if (dedupeKey) {
    const record = store[dedupeKey];
    const sentAt = Number(record && record.sentAt ? record.sentAt : record);
    if (Number.isFinite(sentAt) && now - sentAt <= dedupeWindowMs) {
      duplicateNotifySuppressed = true;
      duplicateNotifyReason = 'duplicate queryId/email within 2h: ' + dedupeKey;
    }
  }
  return { json: {
    ...base,
    sidecarShouldSend: Boolean(base.sidecarShouldSend) && !duplicateNotifySuppressed,
    duplicateNotifySuppressed,
    duplicateNotifyReason,
    duplicateNotifyWindowMs: dedupeWindowMs,
    duplicateNotifyKey: dedupeKey,
  }};
});"""


RECORD_SUCCESSFUL_SEND_JS = r"""const inputItems = $input.all();
const staticData = typeof $getWorkflowStaticData === 'function'
  ? $getWorkflowStaticData('global')
  : (typeof getWorkflowStaticData === 'function' ? getWorkflowStaticData('global') : {});
const now = Date.now();
if (!staticData.queryNotifyDedupeV2 || typeof staticData.queryNotifyDedupeV2 !== 'object') {
  staticData.queryNotifyDedupeV2 = {};
}
const store = staticData.queryNotifyDedupeV2;
return inputItems.map((item) => {
  const base = (item && item.json) || {};
  const recipientEmail = String(base.knChatRecipientEmail || (base.sidecarPayload || {}).email || (base.sidecarPayload || {}).chat_id || (base.sidecarPayload || {}).chatId || base.notifyEmail || '').trim().toLowerCase();
  const dedupeKey = String(base.duplicateNotifyKey || (base.queryId && recipientEmail ? base.queryId + '::' + recipientEmail : base.queryId || '')).trim();
  const sendOk = Boolean(base.sidecarSendOk || base.knChatNotifyOk);
  if (dedupeKey && sendOk) {
    store[dedupeKey] = {
      sentAt: now,
      sessionId: String(base.sessionId || ''),
      email: recipientEmail,
      chatId: String(base.knChatRecipientChatId || ''),
      provider: String(base.sidecarProvider || 'kn_chat_bot'),
    };
  }
  return { json: {
    ...base,
    duplicateNotifyRecorded: Boolean(dedupeKey && sendOk),
    duplicateNotifyRecordedAt: dedupeKey && sendOk ? now : null,
  }};
});"""


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


def force_user_only_ds_account_check(js_code: str) -> str:
    """Remove legacy executor/account fallbacks from DS-match account checks."""
    replacements = {
        "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(sanitize(value).toLowerCase());":
            "const looksSystemAccount = (value) => {\n"
            "  const account = sanitize(value).toLowerCase();\n"
            "  return /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(account)\n"
            "    || /^(ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)$/.test(account);\n"
            "};",
        "const looksSystemAccount = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(textOf(value).trim().toLowerCase());":
            "const looksSystemAccount = (value) => {\n"
            "  const account = textOf(value).trim().toLowerCase();\n"
            "  return /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(account)\n"
            "    || /^(ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)$/.test(account);\n"
            "};",
        "const looks = (value) => /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(sanitize(value).toLowerCase());":
            "const looks = (value) => {\n"
            "    const account = sanitize(value).toLowerCase();\n"
            "    return /^(e|u|a|ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)_/.test(account)\n"
            "      || /^(ods|dw|dwd|dws|dwb|ads|dm|tmp|test|admin|deploy|bigdata|data|bi|ds|etl|sync|load|app)$/.test(account);\n"
            "  };",
    }
    for old, new in replacements.items():
        js_code = js_code.replace(old, new)
    legacy_helper_patterns = [
        (
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n",
            "  return looksSystemAccount(userValue);\n",
        ),
        (
            "  if (userValue) return looksSystemAccount(userValue);\n"
            "  return [row.executor, row.account, row.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looksSystemAccount(value));",
            "  return looksSystemAccount(userValue);",
        ),
        (
            "  if (userValue) return looks(userValue);\n"
            "  return [base.executor, base.account, base.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looks(value));\n",
            "  return looks(userValue);\n",
        ),
        (
            "  if (userValue) return looks(userValue);\n"
            "  return [base.executor, base.account, base.dbUser, queryContextObj.executor, queryContextObj.account, queryContextObj.dbUser, alertObj.executor]\n"
            "    .some((value) => looks(value));",
            "  return looks(userValue);",
        ),
        (
            "  if (user) return looksSystemAccount(user);\n"
            "  return [row.executor, row.account, row.dbUser, queryContext.executor, queryContext.account, queryContext.dbUser, alert.executor]\n"
            "    .some((value) => looksSystemAccount(value));\n",
            "  return looksSystemAccount(user);\n",
        ),
    ]
    for old, new in legacy_helper_patterns:
        js_code = js_code.replace(old, new)
    return js_code


def patch_sidecar_message(js_code: str) -> str:
    js_code = force_user_only_ds_account_check(js_code)
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
            "  return looksSystemAccount(userValue);\n"
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
        "  return looks(userValue);\n"
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
        "  return looks(userValue);\n"
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
            "  return looksSystemAccount(userValue);\n"
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
    if "personalWeiduSignalValues" not in js_code:
        js_code = js_code.replace(
            "const csvGroupSignalText = csvGroupSignalValues.join('\\n');",
            "const csvGroupSignalText = csvGroupSignalValues.join('\\n');\n"
            "const personalWeiduSignalValues = uniq([\n"
            "  ...(Array.isArray(base.notifyEmails) ? base.notifyEmails : []),\n"
            "  sanitize(base.notifyEmail),\n"
            "  sanitize(base.primaryEmail),\n"
            "  sanitize(base.userEmail),\n"
            "  sanitize(base.email),\n"
            "]);\n"
            "const personalWeiduSignalText = personalWeiduSignalValues.join('\\n');",
        )
    js_code = js_code.replace(
        "const isWeiduGroupAlert = Boolean(base.departmentAccountNotifyMatched)\n"
        "  && !isMexicoAifoxGroupAlert\n"
        "  && (/(^|\\n|\\s|,|，|、)唯渡($|\\n|\\s|,|，|、)/i.test(csvGroupSignalText)\n"
        "    || /@weidu\\.co\\b/i.test(csvGroupSignalText)\n"
        "    || /杜艳华|elsadu/i.test(csvGroupSignalText));",
        "const isWeiduGroupAlert = !isMexicoAifoxGroupAlert\n"
        "  && ((Boolean(base.departmentAccountNotifyMatched)\n"
        "    && (/(^|\\n|\\s|,|，|、)唯渡($|\\n|\\s|,|，|、)/i.test(csvGroupSignalText)\n"
        "      || /@weidu\\.co\\b/i.test(csvGroupSignalText)\n"
        "      || /杜艳华|elsadu/i.test(csvGroupSignalText)))\n"
        "    || /@weidu\\.co\\b/i.test(personalWeiduSignalText));",
    )
    js_code = js_code.replace(
        "reason: '精确命中 CSV 映射且部门/联系人/邮箱属于唯渡，且未命中账号级专属群规则，改为唯渡群机器人通知，不发送个人 sidecar。',\n"
        "    signals: csvGroupSignalValues,",
        "reason: '命中唯渡特殊规则（CSV 部门/联系人/邮箱，或个人邮箱 @weidu.co），且未命中账号级专属群规则，改为唯渡群机器人通知，不发送个人 sidecar。',\n"
        "    signals: [...csvGroupSignalValues, ...personalWeiduSignalValues],",
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
        return force_user_only_ds_account_check(js_code)
    return force_user_only_ds_account_check(js_code.replace(marker, insert + marker))


def patch_merge_notify_target(js_code: str) -> str:
    js_code = js_code.replace(
        'const userEmailOverrides = {"alyssali":"Alyssali@weidu.co"};',
        'const userEmailOverrides = {"alyssali":"Alyssali@weidu.co","pengchengzhou":"pengchengzhou@weidu.co"};',
    )
    if "requestForceNotifyEmails" not in js_code:
        js_code = js_code.replace(
            "const fallbackEmail = config.fallbackEmail || 'jiangchuanchen@kn.group';\n"
            "const forceTestEmail = !!config.forceTestEmail;",
            "const fallbackEmail = config.fallbackEmail || 'jiangchuanchen@kn.group';\n"
            "const splitEmails = (value) => String(value || '').split(/[\\s,;；，]+/).map(normalizeEmail).filter((email) => /@/.test(email));\n"
            "const requestForceNotifyEmails = uniq([\n"
            "  ...splitEmails(webhookBody.forceNotifyEmail),\n"
            "  ...(Array.isArray(webhookBody.forceNotifyEmails) ? webhookBody.forceNotifyEmails.flatMap(splitEmails) : []),\n"
            "]);\n"
            "const forceTestEmail = !!config.forceTestEmail;",
        )
        js_code = js_code.replace(
            "if (forceTestEmail) {\n"
            "  finalEmails = [fallbackEmail];\n"
            "  notifyTargetSource = 'force_test_email';\n"
            "} else if (mappedEmails.length) {",
            "if (requestForceNotifyEmails.length) {\n"
            "  finalEmails = requestForceNotifyEmails;\n"
            "  notifyTargetSource = 'request_force_notify_email';\n"
            "} else if (forceTestEmail) {\n"
            "  finalEmails = [fallbackEmail];\n"
            "  notifyTargetSource = 'force_test_email';\n"
            "} else if (mappedEmails.length) {",
        )
    return js_code


def patch_notify_config(js_code: str) -> str:
    legacy_replacements = [
        ("sidecarAccountId: '7660ec09-ec27-4799-8b0e-c66a5322cbc5'", "sidecarAccountId: ''"),
        ("sidecarToken: '6fc22462-da46-42a3-b3ed-fb4ab8c1573f'", "sidecarToken: ''"),
        ("weiduSidecarAccountId: 'e623d433-087b-4740-8a9d-c68a1b682cdc'", "weiduSidecarAccountId: ''"),
        ("weiduSidecarToken: 'dc978f86-8108-4135-8139-45e95010b450'", "weiduSidecarToken: ''"),
        ("weiduGroupBotId: '9ce66a04-5acf-4f84-9fc0-c213760bae05'", "weiduGroupBotId: ''"),
        ("weiduGroupUrl: 'https://tv-service-alert.kuainiu.chat/alert/v2/array'", "weiduGroupUrl: 'https://bot.kn.chat'"),
        ("operationGroupBotId: '66f4d55a-1ca1-45fc-aaf7-f7e9f4dfa302'", "operationGroupBotId: ''"),
        ("operationGroupUrl: 'https://tv-service-alert.kuainiu.chat/alert/v2/array'", "operationGroupUrl: 'https://bot.kn.chat'"),
        ("mexicoAifoxGroupBotId: 'e10c0656-a479-4053-a9cd-18b4d1fe4c87'", "mexicoAifoxGroupBotId: ''"),
        ("mexicoAifoxGroupUrl: 'https://tv-service-alert.kuainiu.chat/alert/v2/array'", "mexicoAifoxGroupUrl: 'https://bot.kn.chat'"),
    ]
    for old, new in legacy_replacements:
        js_code = js_code.replace(old, new)
    js_code = re.sub(r"knChatBotToken:\s*'[^']*'", "knChatBotToken: ''", js_code)
    if "knChatBotApiBase" not in js_code:
        js_code = js_code.replace(
            "  contactUpdateFormUrl: 'https://docs.google.com/forms/d/e/1FAIpQLSemG0t7I77-t7z0_mKit8E6UIPtz6mXEfeyTGQKrjwL-h7ykQ/viewform?usp=publish-editor',",
            "  contactUpdateFormUrl: 'https://docs.google.com/forms/d/e/1FAIpQLSemG0t7I77-t7z0_mKit8E6UIPtz6mXEfeyTGQKrjwL-h7ykQ/viewform?usp=publish-editor',\n"
            "  knChatBotApiBase: 'https://bot.kn.chat',\n"
            "  knChatBotToken: '',\n"
            "  weiduGroupChatId: '',\n"
            "  operationGroupChatId: '',\n"
            "  mexicoAifoxGroupChatId: '',",
        )
    return js_code


def patch_special_group_ds_missing_cc(js_code: str) -> str:
    """Keep special group routing, but also send DS-missing CC as a personal KN Chat message."""
    start = js_code.find("if (matchedSpecialGroupRule) {")
    end = js_code.find("\nconst payloads = notifyEmails.map((email) => {", start)
    if start < 0 or end < 0 or "sidecarChannel: row.channel" in js_code[start:end]:
        return js_code

    replacement = """if (matchedSpecialGroupRule) {
  const groupPayload = {
    chat_id: matchedSpecialGroupRule.chatId,
    text: data,
    legacyBotId: matchedSpecialGroupRule.botId,
    mentions: []
  };
  const dsMissingCcEmail = sanitize(notifyConfig.dsMissingCcEmail || notifyConfig.fallbackEmail || 'jiangchuanchen@kn.group');
  const shouldSendDsMissingCc = Boolean(base.dsTaskMatchMissingNeedsRecord && shouldMatchDsForAccount(base) && dsMissingCcEmail);
  const rows = [{
    notifyEmail: notifyEmails.join(','),
    channel: matchedSpecialGroupRule.channel,
    payload: groupPayload,
    shouldSend: Boolean(matchedSpecialGroupRule.chatId && data.trim()),
  }];
  if (shouldSendDsMissingCc) {
    rows.push({
      notifyEmail: dsMissingCcEmail,
      channel: 'ds_missing_cc',
      payload: { email: dsMissingCcEmail, text: data },
      shouldSend: Boolean(data.trim()),
    });
  }
  const groupFlags = {
    operationGroupNotify: false,
    weiduGroupNotify: false,
    mexicoAifoxGroupNotify: false,
  };
  groupFlags[matchedSpecialGroupRule.flag] = true;
  return rows.map((row) => ({
    json: {
      ...base,
      ...groupFlags,
      notifyEmail: row.notifyEmail,
      notifyEmails,
      dsTaskMatchRequired: !!base.dsTaskMatchRequired,
      dsTaskMatchMissingNeedsRecord: !!base.dsTaskMatchMissingNeedsRecord && shouldMatchDsForAccount(base),
      dsTaskMissingNotice: sanitize(base.dsTaskMissingNotice),
      sidecarShouldSend: row.shouldSend,
      sidecarChannel: row.channel,
      sidecarUrl: matchedSpecialGroupRule.url,
      sidecarPayload: row.payload,
      sidecarPayloads: rows.map((item) => item.payload),
      sidecarRecipientCount: rows.length,
      [matchedSpecialGroupRule.reasonKey]: matchedSpecialGroupRule.reason,
      [matchedSpecialGroupRule.signalsKey]: matchedSpecialGroupRule.signals,
      specialGroupRouteMatched: true,
      specialGroupRouteChannel: matchedSpecialGroupRule.channel,
    }
  }));
}
"""
    return js_code[:start] + replacement + js_code[end:]


def patch_kn_chat_sidecar_payload(js_code: str) -> str:
    js_code = js_code.replace(
        "botId: sanitize(notifyConfig.mexicoAifoxGroupBotId || 'e10c0656-a479-4053-a9cd-18b4d1fe4c87'),",
        "botId: sanitize(notifyConfig.mexicoAifoxGroupBotId || ''),",
    )
    js_code = js_code.replace(
        "botId: sanitize(notifyConfig.operationGroupBotId || '66f4d55a-1ca1-45fc-aaf7-f7e9f4dfa302'),",
        "botId: sanitize(notifyConfig.operationGroupBotId || ''),",
    )
    js_code = js_code.replace(
        "botId: sanitize(notifyConfig.weiduGroupBotId || '9ce66a04-5acf-4f84-9fc0-c213760bae05'),",
        "botId: sanitize(notifyConfig.weiduGroupBotId || ''),",
    )
    replacements = [
        (
            "botId: sanitize(notifyConfig.mexicoAifoxGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.mexicoAifoxGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
            "botId: sanitize(notifyConfig.mexicoAifoxGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.mexicoAifoxGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "botId: sanitize(notifyConfig.mexicoAifoxGroupBotId || 'e10c0656-a479-4053-a9cd-18b4d1fe4c87'),\n"
            "    url: sanitize(notifyConfig.mexicoAifoxGroupUrl || 'https://tv-service-alert.kuainiu.chat/alert/v2/array'),",
            "botId: sanitize(notifyConfig.mexicoAifoxGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.mexicoAifoxGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "botId: sanitize(notifyConfig.operationGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.operationGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
            "botId: sanitize(notifyConfig.operationGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.operationGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "botId: sanitize(notifyConfig.operationGroupBotId || '66f4d55a-1ca1-45fc-aaf7-f7e9f4dfa302'),\n"
            "    url: sanitize(notifyConfig.operationGroupUrl || 'https://tv-service-alert.kuainiu.chat/alert/v2/array'),",
            "botId: sanitize(notifyConfig.operationGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.operationGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "botId: sanitize(notifyConfig.weiduGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.weiduGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
            "botId: sanitize(notifyConfig.weiduGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.weiduGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "botId: sanitize(notifyConfig.weiduGroupBotId || '9ce66a04-5acf-4f84-9fc0-c213760bae05'),\n"
            "    url: sanitize(notifyConfig.weiduGroupUrl || 'https://tv-service-alert.kuainiu.chat/alert/v2/array'),",
            "botId: sanitize(notifyConfig.weiduGroupBotId || ''),\n"
            "    chatId: sanitize(notifyConfig.weiduGroupChatId || ''),\n"
            "    url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "const payload = {\n"
            "    botId: matchedSpecialGroupRule.botId,\n"
            "    message: data,\n"
            "    mentions: []\n"
            "  };",
            "const payload = {\n"
            "    chat_id: matchedSpecialGroupRule.chatId,\n"
            "    text: data,\n"
            "    legacyBotId: matchedSpecialGroupRule.botId,\n"
            "    mentions: []\n"
            "  };",
        ),
        (
            "sidecarShouldSend: Boolean(matchedSpecialGroupRule.botId && data.trim()),",
            "sidecarShouldSend: Boolean(matchedSpecialGroupRule.chatId && data.trim()),",
        ),
        (
            "const payload = { type: 'TEXT', email, data, accountId, token };",
            "const payload = { email, text: data };",
        ),
        (
            "url: 'https://sidecar.kuainiu.chat/conversation',",
            "url: sanitize(notifyConfig.knChatBotApiBase || 'https://bot.kn.chat'),",
        ),
        (
            "shouldSend: Boolean(email && accountId && token && data.trim())",
            "shouldSend: Boolean(email && data.trim())",
        ),
    ]
    for old, new in replacements:
        js_code = js_code.replace(old, new)
    return patch_special_group_ds_missing_cc(js_code)


def patch_dedupe_node(js_code: str) -> str:
    return DEDUPE_CHECK_JS


def patch_webhook_response(js_code: str) -> str:
    js_code = force_user_only_ds_account_check(js_code)
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
        "const notifyItems = $input.all().map((item) => item && item.json ? item.json : {}).filter(Boolean);\n"
        "const notify = notifyItems[0] || $json || {};\n"
        "const base = {\n"
        "  ...safeNodeJson('Build Langfuse Batch'),\n"
        "  ...safeNodeJson('Merge DS Task Match'),\n"
        "  ...safeNodeJson('Build Sidecar Payload'),\n"
        "  ...notify,\n"
            "};",
    )
    if "const notifyItems =" not in js_code:
        js_code = js_code.replace(
            "const notify = $json || {};\n"
            "const base = {",
            "const notifyItems = $input.all().map((item) => item && item.json ? item.json : {}).filter(Boolean);\n"
            "const notify = notifyItems[0] || $json || {};\n"
            "const base = {",
        )
    if "...notify," not in js_code:
        js_code = js_code.replace(
            "  ...safeNodeJson('Build Sidecar Payload'),\n"
            "};",
            "  ...safeNodeJson('Build Sidecar Payload'),\n"
            "  ...notify,\n"
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
            "  return looksSystemAccount(userValue);\n"
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
            "  return looksSystemAccount(userValue);\n"
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
            "  return looksSystemAccount(userValue);\n"
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
    if "knChatResolveOk:" not in js_code:
        js_code = js_code.replace(
            "  notifyResponse: notify,\n"
            "  langfuse: {",
            "  notifyResponse: notify,\n"
            "  sidecarSendOk: !!notify.sidecarSendOk,\n"
            "  sidecarProvider: textOf(notify.sidecarProvider || base.sidecarProvider),\n"
            "  knChatNotifyOk: !!notify.knChatNotifyOk,\n"
            "  knChatRecipientEmail: textOf(notify.knChatRecipientEmail || base.notifyEmail),\n"
            "  knChatRecipientChatId: textOf(notify.knChatRecipientChatId),\n"
            "  knChatResolveOk: !!notify.knChatResolveOk,\n"
            "  knChatResolveMode: textOf(notify.knChatResolveMode),\n"
            "  knChatResolveStatusCode: notify.knChatResolveStatusCode || null,\n"
            "  knChatSendStatusCode: notify.knChatSendStatusCode || null,\n"
            "  knChatSendDescription: textOf(notify.knChatSendDescription),\n"
            "  knChatError: textOf(notify.knChatError || notify.error),\n"
            "  knChatResolveResponse: notify.knChatResolveResponse || null,\n"
            "  knChatSendResponse: notify.knChatSendResponse || null,\n"
            "  langfuse: {",
        )
    if "sidecarResults:" not in js_code:
        js_code = js_code.replace(
            "  notifyResponse: notify,\n"
            "  sidecarSendOk: !!notify.sidecarSendOk,\n",
            "  notifyResponse: notify,\n"
            "  sidecarResults: notifyItems.map((row) => ({\n"
            "    email: textOf(row.knChatRecipientEmail || row.notifyEmail || (row.sidecarPayload || {}).email),\n"
            "    chatId: textOf(row.knChatRecipientChatId || (row.sidecarPayload || {}).chat_id || (row.sidecarPayload || {}).chatId),\n"
            "    sidecarSendOk: !!row.sidecarSendOk,\n"
            "    knChatNotifyOk: !!row.knChatNotifyOk,\n"
            "    knChatResolveOk: !!row.knChatResolveOk,\n"
            "    knChatResolveStatusCode: row.knChatResolveStatusCode || null,\n"
            "    knChatSendStatusCode: row.knChatSendStatusCode || null,\n"
            "    knChatError: textOf(row.knChatError || row.error),\n"
            "    duplicateNotifySuppressed: !!row.duplicateNotifySuppressed,\n"
            "    duplicateNotifyReason: textOf(row.duplicateNotifyReason),\n"
            "  })),\n"
            "  allNotifySentOk: notifyItems.length ? notifyItems.every((row) => !!row.sidecarSendOk || !!row.knChatNotifyOk || !!row.duplicateNotifySuppressed || !!row.knChatSkipped) : false,\n"
            "  failedNotifyEmails: notifyItems.filter((row) => row.sidecarShouldSend !== false && !row.sidecarSendOk && !row.knChatNotifyOk && !row.duplicateNotifySuppressed && !row.knChatSkipped).map((row) => textOf(row.knChatRecipientEmail || row.notifyEmail || (row.sidecarPayload || {}).email)).filter(Boolean),\n"
            "  sidecarSendOk: !!notify.sidecarSendOk,\n",
        )
    return force_user_only_ds_account_check(js_code)


def main() -> None:
    workflow = json.loads(resolve_input().read_text(encoding="utf-8"))
    workflow["name"] = "sql优化_部门账号联系人通知_DS匹配增强版"
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
        "notes": "提前过滤个人账号：只按 user 字段判断是否进入 DS 匹配。像 jiangchuanchen、apriljiang 这种无系统账号前缀的个人账号默认不是 DS 调度，直接跳过 DS 查询，避免被 executor 等字段误伤。",
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
                "value": "={{ { \"cluster\": $json.cluster || \"\", \"country\": $json.country || \"\", \"queryId\": $json.queryId || \"\", \"user\": $json.user || \"\", \"executor\": $json.executor || \"\", \"alertTime\": (($json.evidence || {}).alert || {}).alertTime || (($json.evidence || {}).alert || {}).startTime || (($json.evidence || {}).alert || {}).queryStartTime || (($json.evidence || {}).queryContext || {}).startTime || (($json.evidence || {}).queryContext || {}).queryStartTime || $json.alertTime || $json.startTime || $json.queryStartTime || \"\", \"hostIp\": $json.hostIp || $json.clientIp || $json.queryHost || ((($json.evidence || {}).queryContext || {}).hostIp) || ((($json.evidence || {}).queryContext || {}).clientIp) || ((($json.evidence || {}).alert || {}).hostIp) || ((($json.evidence || {}).alert || {}).clientIp) || \"\", \"message\": (($json.evidence || {}).alert || {}).message || $json.message || $json.rawMessage || \"\", \"rawMessage\": (($json.evidence || {}).alert || {}).rawMessage || $json.rawMessage || \"\", \"sqlText\": ((($json.evidence || {}).queryContext || {}).sqlText) || $json.sqlText || $json.originalSql || \"\" } }}",
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

    notify_config = node_by_name(workflow, "Notify Config")
    notify_config["parameters"]["jsCode"] = patch_notify_config(notify_config["parameters"]["jsCode"])

    sidecar = node_by_name(workflow, "Build Sidecar Payload")
    sidecar["parameters"]["jsCode"] = patch_kn_chat_sidecar_payload(
        patch_sidecar_message(sidecar["parameters"]["jsCode"])
    )

    dedupe = node_by_name(workflow, "Deduplicate Notify By QueryId")
    dedupe["parameters"]["jsCode"] = patch_dedupe_node(dedupe["parameters"]["jsCode"])

    should_send = node_by_name(workflow, "Should Send Sidecar?")
    should_send["parameters"]["conditions"]["boolean"][0]["value1"] = (
        "={{ Boolean($json.sidecarShouldSend && $json.sidecarPayload && "
        "((($json.sidecarPayload.email || $json.sidecarPayload.chat_id || $json.sidecarPayload.chatId) "
        "&& ($json.sidecarPayload.text || $json.sidecarPayload.data || $json.sidecarPayload.message)))) }}"
    )

    send_sidecar = node_by_name(workflow, "Send Sidecar Alert")
    send_sidecar["type"] = "n8n-nodes-base.code"
    send_sidecar["typeVersion"] = 2
    send_sidecar["parameters"] = {"jsCode": KN_CHAT_SEND_JS}
    send_sidecar["notesInFlow"] = True
    send_sidecar["notes"] = (
        "KN Chat Bot 发送节点。个人通知通过 resolveUserId(email) 获取 user_id 后 sendMessage；"
        "群通知需要 sidecarPayload.chat_id。当前 Bot token 从 Notify Config 读取。"
    )

    record_success_node = {
        "parameters": {"jsCode": RECORD_SUCCESSFUL_SEND_JS},
        "id": "record-successful-sidecar-send",
        "name": "Record Successful Sidecar Send",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [50880, 13824],
        "notesInFlow": True,
        "notes": "只有 KN Chat sendMessage 返回 ok=true 后，才写入 queryId+收件人 2 小时去重缓存，避免失败重试被误判为已发送。",
    }
    add_or_replace_node(workflow, record_success_node)
    connect(workflow, "Send Sidecar Alert", ["Record Successful Sidecar Send"])
    connect(workflow, "Record Successful Sidecar Send", ["Build Webhook Response"])

    merge_notify_target = node_by_name(workflow, "Merge Notify Target")
    merge_notify_target["parameters"]["jsCode"] = patch_merge_notify_target(
        merge_notify_target["parameters"]["jsCode"]
    )

    response = node_by_name(workflow, "Build Webhook Response")
    response["parameters"]["jsCode"] = patch_webhook_response(response["parameters"]["jsCode"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
