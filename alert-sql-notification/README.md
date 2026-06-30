# 异常 SQL 告警通知

这个目录保存 n8n 异常 SQL 告警通知相关文件、联系人映射 CSV，以及用于生成 workflow 的脚本。

## 目录说明

- `data/alert-contact-mapping.csv`：n8n 本机运行时使用的单一联系人映射 CSV。
- `data/alert-contact-mapping.json`：由 Excel/CSV 生成的联系人映射 JSON 备份。
- `workflows/sql-optimizer-notify-google-dynamic.workflow.json`：异常 SQL 优化主流程，动态读取联系人更新源。
- `workflows/sql-optimizer-notify-repo-csv.workflow.json`：推荐上线版本。异常 SQL 优化主流程，每次通知前先拉取本仓库，并读取仓库内单个联系人 CSV 做映射。
- `workflows/sql-optimizer-notify-github-raw-csv-single-chain.workflow.json`：推荐发通知版本。异常 SQL 优化主流程直接通过 GitHub raw URL 拉取最新联系人 CSV，保持原主链路，不需要 n8n 本机 git。
- `workflows/sql-optimizer-notify-hardcoded.workflow.json`：异常 SQL 优化主流程，联系人映射写死版本。
- `workflows/daily-contact-form-sync-local-csv.workflow.json`：每日读取表单响应并覆盖更新本机 CSV 的流程。
- `workflows/daily-contact-form-sync-pull-repo-csv.workflow.json`：推荐上线版本。每日先拉取本仓库，再覆盖更新仓库内单个 CSV，最后提交并推回 GitHub。
- `scripts/`：生成或迭代 workflow 的脚本。

## 本机 CSV 同步方式

如果只想在 n8n 本机固定保存一个 CSV，可以使用：

```text
/data/alert-contact-mapping.csv
```

导入 `daily-contact-form-sync-local-csv.workflow.json` 后，它会每天 12 点读取表单响应，然后按 `国家 + 账号` 精准定位并覆盖写回同一个 CSV。

如果表单里的“修改后联系人”为空，会自动兜底为国家负责人，并在备注中写入说明。

## 推荐上线方式：拉取仓库并推回 CSV

推荐导入两个 workflow：

```text
workflows/sql-optimizer-notify-github-raw-csv-single-chain.workflow.json
workflows/daily-contact-form-sync-pull-repo-csv.workflow.json
```

两条流程共用：

```text
/data/KN-YCGJ-TZ
```

作为 n8n 本机仓库目录，并共用同一个 CSV：

```text
alert-sql-notification/data/alert-contact-mapping.csv
```

发通知流程 `sql-optimizer-notify-github-raw-csv-single-chain.workflow.json` 每次执行：

1. 通过 GitHub raw URL 读取仓库内单个联系人 CSV。
2. 按 `国家 + 账号` 映射通知联系人。
3. 发送 Sidecar 通知。

发通知主链路保持为：

```text
Notify Config -> Fetch Contact CSV -> Get User Info -> Merge Notify Target
```

表单同步流程 `daily-contact-form-sync-pull-repo-csv.workflow.json` 每天 12 点执行：

1. `git clone` 或 `git pull --rebase` 本仓库。
2. 读取 Google 表单响应 CSV。
3. 覆盖更新仓库内单个联系人 CSV。
4. 如果 CSV 有变更，则 `git commit` 并 `git push origin main`。

如果 GitHub 仓库是 private，发通知流程中的 `Fetch Contact CSV` 需要加 GitHub token 请求头；如果仓库是 public，则不需要。

旧的 `sql-optimizer-notify-repo-csv.workflow.json` 也可用，但它依赖 n8n 本机 git。简单上线优先使用 raw CSV single-chain 版本。

表单同步版本需要 n8n 本机安装 `git`，并配置可读写本仓库的 SSH key。

## n8n 运行要求

CSV workflow 需要 Code 节点能使用 Node.js 内置 `fs` 模块：

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
