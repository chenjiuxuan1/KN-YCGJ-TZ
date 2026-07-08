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

## 注意事项

- n8n 导出的 workflow JSON 可能包含 API Key、DB 密码等敏感信息，本目录不提交 `outputs/`。
- 生产接入时，数据库密码、API Key、机器人 botId 等参数应通过 n8n 凭证或环境变量注入。
- 第一版可以先用于生成治理表与通知候选；自动下线动作建议在业务确认链路稳定后再开启。
