# Abnormal SQL Governance Automation

第一版异常 SQL 与 DS 治理自动化代码，包含异常 SQL 指纹聚合、A/B/C/D 评分模型、DS 任务匹配、负责人解析、通知候选生成与反馈处理。

本目录为新增模块，不修改现有联系人 CSV、主通知 workflow 或同步 workflow。

## 核心入口

- `governance_automation/level_classifier.py`: 异常 SQL 评分模型与治理等级计算。
- `governance_automation/weekly_aggregator.py`: 周度异常 SQL 按指纹聚合。
- `governance_automation/pipeline.py`: 第一版周度治理流水线。
- `governance_automation/ds_task_matcher.py`: DS 项目、工作流、任务匹配逻辑。
- `remote_scripts/ds_match_candidate_query.py`: n8n SSH 子流程远端 DS 候选查询脚本。
- `tools/run_weekly_governance.py`: 本地或调度入口。
- `tests/test_governance_automation.py`: 单元测试。
- `remote_scripts/ds_zombie_scan.py`: DS 僵尸任务 Python 扫描、上下游识别、评分和小摘要入口。
- `workflows/ds-zombie-scan-python.workflow.json`: 基于现有手动扫描流程改造的新版 n8n workflow。
- `docs/DS_ZOMBIE_SCAN_LOGIC.md`: 完整中文判断逻辑、上下游反查规则和 A/B/C/D 口径。

## DS 僵尸任务 Python 扫描

新版流程保留原 n8n 的国家分流与 SSH 凭据，但原始 DS 明细不再进入 n8n。远端需配置 `DS_DB_HOST`、`DS_DB_PORT`、`DS_DB_USER`、`DS_DB_PASSWORD`、`DS_DB_DATABASE`；启用治理落库时另配同名 `GOVERNANCE_DB_*` 环境变量。

```bash
python3 remote_scripts/ds_zombie_scan.py \
  --country th \
  --batch-id manual-20260720 \
  --project-name example_project \
  --dry-run
```

详细规则见 `docs/DS_ZOMBIE_SCAN_LOGIC.md`。扫描只读 DS 元数据库，不会自动停调度或下线。

## 本地测试

```bash
cd alert-sql-notification/governance-automation
python3 -m unittest tests/test_governance_automation.py
```

## DS 国家连接配置

DS 元数据库连接按国家内置非敏感参数，密码必须通过环境变量或 n8n 凭证注入，不提交明文密码。

| 国家 | 集群 | DS 元数据库 | 用户 | 密码环境变量 |
| --- | --- | --- | --- | --- |
| 中国 | `starrocks_cn` | `rm-uf60p909s1lpp1urp.mysql.rds.aliyuncs.com:3306/cn_dolphin` | `cn_dolphin` | `CN_DS_DB_PASSWORD` |
| 印尼 | `starrocks_ine` | `192.168.25.249:3306/dolphin_scheduler` | `e_ds` | `INE_DS_DB_PASSWORD` |
| 墨西哥 | `starrocks_mex` | `rm-2ev5479nuworkbb0x.mysql.rds.aliyuncs.com:3306/dolphin_scheduler` | `e_ds` | `MX_DS_DB_PASSWORD` |
| 菲律宾 | `starrocks_ph` | `10.20.81.11:3306/dolphin_scheduler` | `a_dolphinscheduler` | `PH_DS_DB_PASSWORD` |
| 巴基斯坦 | `starrocks_pak` | `rm-gs5zsdzr5kr0sh70p.mysql.singapore.rds.aliyuncs.com:3306/dolphin_scheduler` | `e_ds` | `PK_DS_DB_PASSWORD` |
| 泰国 | `starrocks_th` | `rm-gs533qw7xj1e7wdp7.mysql.singapore.rds.aliyuncs.com:3306/dolphin_scheduler` | `a_dolphinscheduler` | `TH_DS_DB_PASSWORD` |

`remote_scripts/ds_match_candidate_query.py` 的连接优先级：

1. 命令行参数 `--ds-db-host/--ds-db-user/--ds-db-password/--ds-db-name`。
2. 环境变量 `DS_DB_HOST/DS_DB_USER/DS_DB_PASSWORD/DS_DB_NAME`。
3. 国家内置配置 + 对应国家密码环境变量。
4. 运行中 DolphinScheduler Java 进程里的 `SPRING_DATASOURCE_*`。

## n8n SSH 子流程上线方式

`tools/build_ds_match_candidate_workflow.py` 会生成 `DS任务匹配候选查询_execute_workflow.json`。同一个 workflow 内包含两条链路：

- `Manual Trigger - Deploy Code`: 手动执行，用于在各国 SSH 节点机器拉取或更新 GitHub 代码。
- `When Executed by Another Workflow`: 被主通知流程调用，只执行已部署的 Python 脚本，不再每次运行都更新代码。

SSH 节点登录的机器需要具备：

```bash
git
python3
mysql
```

执行时会在 SSH 节点机器上维护一个临时仓库：

```text
/tmp/KN-YCGJ-TZ-governance-automation
```

手动执行 `Manual Trigger - Deploy Code` 时会自动：

1. 中止残留的 merge/rebase。
2. 重置本地仓库状态。
3. 如果仓库不存在或损坏，重新 clone。
4. 拉取 `main` 分支最新代码。
5. 校验 `remote_scripts/ds_match_candidate_query.py` 已存在。

主流程调用 `When Executed by Another Workflow` 时只会：

1. 检查远端脚本是否已部署。
2. 设置对应国家 DS 连接环境变量。
3. 执行 `remote_scripts/ds_match_candidate_query.py`。

推荐上线顺序：

1. 导入 `DS任务匹配候选查询_execute_workflow`。
2. 在该 workflow 内手动执行 `Manual Trigger - Deploy Code`，确认各国 SSH 节点机器已拉取代码。
3. 导入主通知增强版 workflow，并在主流程里选择该子 workflow。
4. 测试主流程或子流程查询入口，确认可以查询 DS 元数据库。
5. 后续只有代码更新时才重新手动执行 `Manual Trigger - Deploy Code`；普通异常 SQL 通知运行时不会执行 git 更新。

## 注意事项

- n8n 导出的 workflow JSON 可能包含 API Key、DB 密码等敏感信息，本目录不提交 `outputs/`。
- 生产接入时，数据库密码、API Key、机器人 botId 等参数应通过 n8n 凭证或环境变量注入。
- 第一版可以先用于生成治理表与通知候选；自动下线动作建议在业务确认链路稳定后再开启。
