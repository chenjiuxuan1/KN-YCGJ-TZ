# 异常 SQL 告警通知

这个目录保存 n8n 异常 SQL 告警通知相关文件、联系人映射 CSV，以及用于生成 workflow 的脚本。

## 目录说明

- `data/alert-contact-mapping.csv`：n8n 本机运行时使用的单一联系人映射 CSV。
- `data/alert-contact-mapping.json`：由 Excel/CSV 生成的联系人映射 JSON 备份。
- `workflows/sql-optimizer-notify-google-dynamic.workflow.json`：异常 SQL 优化主流程，动态读取联系人更新源。
- `workflows/sql-optimizer-notify-hardcoded.workflow.json`：异常 SQL 优化主流程，联系人映射写死版本。
- `workflows/daily-contact-form-sync-local-csv.workflow.json`：每日读取表单响应并覆盖更新本机 CSV 的流程。
- `scripts/`：生成或迭代 workflow 的脚本。

## 本机 CSV 同步方式

推荐在 n8n 本机固定保存一个 CSV：

```text
/data/alert-contact-mapping.csv
```

导入 `daily-contact-form-sync-local-csv.workflow.json` 后，它会每天 12 点读取表单响应，然后按 `国家 + 账号` 精准定位并覆盖写回同一个 CSV。

如果表单里的“修改后联系人”为空，会自动兜底为国家负责人，并在备注中写入说明。

## n8n 运行要求

本机 CSV workflow 需要 Code 节点能使用 Node.js 内置 `fs` 模块：

```text
NODE_FUNCTION_ALLOW_BUILTIN=fs
```

如果 n8n 用 Docker 运行，请把 `/data` 挂载到宿主机持久化目录。

## 密钥说明

提交到仓库的 workflow 已清理 Sidecar token，占位符为：

```text
__FILL_IN_N8N__
```

导入 n8n 后，需要在对应 Code 节点里填回生产环境 token，或者改成从 n8n 环境变量读取。
