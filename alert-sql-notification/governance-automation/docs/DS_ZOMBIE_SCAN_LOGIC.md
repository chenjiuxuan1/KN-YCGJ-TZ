# DS 僵尸任务扫描完整判断逻辑

## 一、整套流程

1. n8n 保留原来的手动触发、参数配置、按国家分流和 6 个 SSH 节点。
2. SSH 节点不再把 DS 全量结果返回 n8n，而是在跳板机运行 `remote_scripts/ds_zombie_scan.py`。
3. Python 从 DS 库读取项目、工作流、任务关系、任务定义、调度和流程实例。
4. Python 按工作流聚合，构建任务级 DAG，并解析跨工作流依赖。
5. Python 根据活跃度、调度、上下游完整性及保护证据计算 A/B/C/D。
6. 完整治理明细可幂等写入治理库；stdout 只返回统计和 Top 20。
7. n8n 校验摘要，拒绝包含 `data`、`candidates` 等大数组的响应。

## 二、数据表与字段

主要读取以下 DolphinScheduler 元数据表：

- `t_ds_project`：项目编码、名称和负责人。
- `t_ds_workflow_definition`：工作流编码、版本、上线状态、更新时间。
- `t_ds_workflow_task_relation`：当前工作流版本内的前置任务和后置任务。
- `t_ds_task_definition`：任务编码、任务类型和 `task_params`。
- `t_ds_schedules`：周期调度与上线状态。
- `t_ds_process_instance`：最近运行、最近成功、最近失败和近 30 天运行次数。

所有查询均为只读。数据库密码通过远端环境变量 `DS_DB_*` 和 `GOVERNANCE_DB_*` 注入，不写入代码或 n8n JSON。

## 三、任务级 DAG

读取 `t_ds_workflow_task_relation` 后，对每条关系：

```text
pre_task_code -> post_task_code
```

同时建立两个索引：

```text
task_downstream[工作流][前置任务] = 后置任务集合
task_upstream[工作流][后置任务] = 前置任务集合
```

它用于说明工作流内部任务结构。工作流内部有下游不等于跨工作流被引用，因此不会单独阻止下线。

## 四、跨工作流下游反查

1. 找出 `task_type = DEPENDENT` 的任务。
2. 递归解析 `task_params`，兼容 `definitionCode`、`processDefinitionCode` 等字段名。
3. 当前 DEPENDENT 任务所在工作流是“下游”，参数中指向的工作流是“上游”。
4. 同时建立正向和反向索引：

```text
workflow_upstream[下游工作流] += 上游工作流
workflow_downstream[上游工作流] += 下游工作流
```

例如 B 中的 DEPENDENT 节点依赖 A，则 A 的下游包含 B，B 的上游包含 A。扫描 A 时可以通过反向索引发现 B，避免误下线 A。

依赖证据保存源工作流、目标项目、目标工作流、目标任务、解析状态。原始参数不进入 n8n 响应。

## 五、依赖不完整保护

如果 DEPENDENT 参数不是合法 JSON、没有目标工作流编码或出现未知结构：

- `dependency_scan_complete = false`
- `protected_by_uncertainty = true`
- 等级最多进入 C
- 动作为 `COLLECT_EVIDENCE`
- 禁止输出下线确认建议

这条规则保证“解析不到”不会被误判为“没有下游”。

## 六、活跃度规则

第一版 `v1` 疑似分如下：

- 超过 3 个月未更新：+10。
- 超过 6 个月未更新：+20。
- 超过 12 个月未更新：+30。
- 近 30 天零运行且实例扫描完整：+25。
- 超过 6 个月未运行且实例扫描完整：+25。
- 没有有效上线调度：+10。

近期有运行、存在下游、负责人确认保留等保护规则优先于总分。

访问、Superset 和 StarRocks 查询证据采用三态：`present`、`absent`、`unknown`。数据源尚未接入时必须是 `unknown`，不能按“没有访问”加疑似分。

## 七、A/B/C/D

### A：优先下线确认

通常需要总分不低于 60，同时满足：

- 运行实例扫描完整。
- 上下游扫描完整。
- 没有跨工作流下游。
- 没有资源/数据引用保护。
- 没有近期运行和明确保留证据。

动作仅为 `REQUEST_DECOMMISSION_CONFIRMATION`，不是自动下线。

### B：负责人重点确认

长期不活跃，但疑似分不足 A，或存在资源/数据引用等影响证据。动作为 `OWNER_CONFIRMATION`。

### C：观察或补证

证据不足、实例扫描不完整或依赖解析不完整。动作是 `COLLECT_EVIDENCE` 或 `OBSERVE`。

### D：活跃或受保护

近期有运行、存在有效跨工作流下游、负责人确认保留。动作是 `KEEP_ACTIVE`、`KEEP_CONFIRMED` 或 `RETAIN_AND_ASSESS`。

## 八、治理动作

扫描程序永远不调用 DS 下线、停调度或删除接口。它只生成候选动作。真实操作必须经过：

```text
通知负责人 -> 确认用途 -> 观察 -> 形成操作计划 -> 明确审批 -> 执行 -> 归档
```

## 九、治理库与幂等

明细以以下字段作为唯一键：

```text
country + batch_id + workflow_code + score_version
```

同一批次重跑更新原记录，不产生重复候选。每条记录保留等级、分数、原因、上下游数量、保护状态和证据摘要。

## 十、n8n 返回内容

n8n 只接收：扫描工作流数、候选数、落库数、等级分布、依赖保护数、不确定依赖数和最多 20 条预览。禁止返回全量任务明细，从而避免原来的 20MB JSON、浏览器卡顿和 502。

## 十一、上线与回滚

1. 先部署 Git 仓库到各跳板机。
2. 配置远端 `DS_DB_*`；需要落库时配置 `GOVERNANCE_DB_*`。
3. 先用单项目和 `--dry-run` 校验数量及上下游。
4. 再执行单国全量 dry-run。
5. 验证后开启 `--write-to-db`。
6. 导入新版 workflow，旧 workflow 保持停用作为回滚版本。

整个上线过程不自动执行任何生产 DS 变更。

