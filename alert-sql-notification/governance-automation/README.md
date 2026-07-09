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

`tools/build_ds_match_candidate_workflow.py` 生成的 n8n 子流程采用 GitHub 拉取模式，不再把 Python 脚本 base64 内嵌到 SSH 命令里。

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

每次执行会自动：

1. 中止残留的 merge/rebase。
2. 重置本地仓库状态。
3. 如果仓库不存在或损坏，重新 clone。
4. 拉取 `main` 分支最新代码。
5. 执行 `remote_scripts/ds_match_candidate_query.py`。

## 注意事项

- n8n 导出的 workflow JSON 可能包含 API Key、DB 密码等敏感信息，本目录不提交 `outputs/`。
- 生产接入时，数据库密码、API Key、机器人 botId 等参数应通过 n8n 凭证或环境变量注入。
- 第一版可以先用于生成治理表与通知候选；自动下线动作建议在业务确认链路稳定后再开启。
