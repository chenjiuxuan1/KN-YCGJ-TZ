# DS 僵尸任务级表血缘增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a task-granular DS zombie CSV that never mislabels missing dependency details as no dependency and augments candidate tasks with bounded table-lineage evidence from the DS Router.

**Architecture:** Python remains the authoritative, read-only collector for DS metadata, direct dependency edges, task SQL/resource references and task-level rows. The n8n workflow invokes the existing DS Router only for bounded candidate-task table probes, merges returned lineage evidence, then renders a Chinese task-level CSV. Workflow-level scoring remains unchanged and is repeated on every associated task row.

**Tech Stack:** Python 3, MySQL/DolphinScheduler metadata, n8n Code/Execute Workflow nodes, existing `ds-scheduler-router`, JSON/CSV, `unittest`.

---

### Task 1: Model direct dependency detail state and task rows

**Files:**
- Modify: `alert-sql-notification/governance-automation/governance_automation/ds_dependency_graph.py`
- Modify: `alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_scan.py`

- [ ] **Step 1: Write failing tests for dependency detail states and task rows**

```python
def test_nonzero_downstream_without_evidence_is_unavailable_not_none(self):
    row = build_task_row(downstream_count=2, downstream_details=[], graph_complete=True)
    self.assertEqual(row['dependency_detail_status'], 'unavailable')
    self.assertIn('已识别 2 个下游依赖', row['downstream_dependency_detail'])

def test_candidate_workflow_emits_one_row_per_task(self):
    rows = build_task_rows(workflow, [sql_task, shell_task])
    self.assertEqual([row['candidate_task_name'] for row in rows], ['load_orders', 'refresh_snapshot'])
    self.assertTrue(all(row['workflow_code'] == workflow['workflow_code'] for row in rows))
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_zombie_scan.DependencyGraphTests -v`

Expected: FAIL because task-row builders and dependency detail state do not exist.

- [ ] **Step 3: Implement direct edge and task-row output**

Add `source_task_name` to graph evidence and create scan helpers with this contract:

```python
DEPENDENCY_DETAIL_AVAILABLE = 'available'
DEPENDENCY_DETAIL_NONE = 'none'
DEPENDENCY_DETAIL_INCOMPLETE = 'incomplete'
DEPENDENCY_DETAIL_UNAVAILABLE = 'unavailable'

def dependency_detail_status(downstream_count, details, scan_complete):
    if not scan_complete:
        return DEPENDENCY_DETAIL_INCOMPLETE
    if downstream_count == 0:
        return DEPENDENCY_DETAIL_NONE
    return DEPENDENCY_DETAIL_AVAILABLE if details else DEPENDENCY_DETAIL_UNAVAILABLE
```

For every task in a non-D workflow emit a row containing `record_granularity='任务级'`, `candidate_task_code`, `candidate_task_name`, `candidate_task_type`, the repeated workflow score fields, and direct downstream details. Emit exactly one `record_granularity='工作流级兜底'` row only when no task definition exists.

- [ ] **Step 4: Run focused tests**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_zombie_scan -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_dependency_graph.py \
  alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py \
  alert-sql-notification/governance-automation/tests/test_ds_zombie_scan.py
git commit -m "feat: emit task-level DS dependency rows"
```

### Task 2: Extract conservative task SQL table evidence

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_task_lineage.py`
- Modify: `alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_task_lineage.py`

- [ ] **Step 1: Write failing extractor tests**

```python
def test_extracts_write_and_read_tables_and_excludes_cte():
    evidence = extract_task_table_evidence('WITH base AS (SELECT * FROM raw.a) INSERT OVERWRITE dw.b SELECT * FROM base JOIN dim.c')
    self.assertEqual(evidence.write_tables, ('dw.b',))
    self.assertEqual(evidence.read_tables, ('raw.a', 'dim.c'))

def test_dynamic_script_is_incomplete_not_empty():
    evidence = extract_task_table_evidence('spark.sql(sql_text)')
    self.assertEqual(evidence.status, 'incomplete')
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_task_lineage -v`

Expected: FAIL because the module is absent.

- [ ] **Step 3: Implement parser and scan integration**

Implement `TaskTableEvidence(status, write_tables, read_tables, resource_refs)` using `strip_sql_comments` and a conservative tokenizer. Support `INSERT INTO`, `INSERT OVERWRITE`, `MERGE INTO`, `CREATE TABLE ... AS`, and `REPLACE INTO` as writes; support `FROM` and `JOIN` as reads. Remove CTE aliases and do not infer dynamic variables. Read SQL/SHELL fields and `resourceList` from DS task parameters without returning raw SQL in scan output.

- [ ] **Step 4: Add task-lineage fields to scan output**

Attach `candidate_write_tables`, `task_lineage_status`, and bounded `task_resource_refs` to each task row. If parser status is incomplete, append a Chinese evidence reason and never render “未发现表血缘”.

- [ ] **Step 5: Run tests**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_task_lineage tests.test_ds_zombie_scan -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_task_lineage.py \
  alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py \
  alert-sql-notification/governance-automation/tests/test_ds_task_lineage.py
git commit -m "feat: extract DS task table evidence"
```

### Task 3: Add a bounded Router table-lineage enhancement workflow

**Files:**
- Create: `alert-sql-notification/governance-automation/tools/build_ds_zombie_lineage_workflow.py`
- Create: `alert-sql-notification/governance-automation/workflows/ds-zombie-task-lineage.workflow.json`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_lineage_workflow.py`

- [ ] **Step 1: Write failing workflow contract test**

```python
def test_workflow_limits_router_calls_and_does_not_embed_tokens(self):
    workflow = build_workflow()
    raw = json.dumps(workflow, ensure_ascii=False)
    self.assertIn('search_resource_sql', raw)
    self.assertIn('extract_task_runtime_config', raw)
    self.assertNotIn('embeddedCountryDsTokens', raw)
    self.assertIn('MAX_WRITE_TABLES = 10', raw)
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_zombie_lineage_workflow -v`

Expected: FAIL because the builder does not exist.

- [ ] **Step 3: Implement n8n task-lineage nodes**

The generated workflow must have these nodes and contracts:

```text
Manual Trigger -> Build Manual Scan Request -> country SSH scan
  -> Validate Python Summary -> Split Candidate Task Rows
  -> Build Router Probe (max 10 write tables/task)
  -> Execute ds-scheduler-router (search_resource_sql)
  -> Normalize Resource Evidence
  -> Execute ds-scheduler-router (extract_task_runtime_config only for located task)
  -> Merge Task Lineage Evidence -> Build Chinese Task CSV
```

`Build Router Probe` receives router URL and `ds_token` only from n8n credentials or workflow input, never hard-coded in JSON. It limits each task to 10 write tables, two resource hits per table, two resource files, 5 seconds per Router request and 15 seconds aggregate elapsed time. Timeout produces `表血缘扫描状态='部分完成'`.

- [ ] **Step 4: Implement evidence merge rules**

The merge Code node emits one row per candidate task with `table_lineage_downstream_detail`, `table_lineage_confidence`, `table_lineage_source`, `table_lineage_status` and `downstream_protection_basis`. Only a bound active DS consumer task plus matching candidate write table produces high confidence. Resource/Git text-only matches remain medium or low and do not alter an A result to D automatically.

- [ ] **Step 5: Run workflow tests and JSON validation**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_zombie_lineage_workflow -v && python3 tools/build_ds_zombie_lineage_workflow.py && jq empty workflows/ds-zombie-task-lineage.workflow.json`

Expected: PASS and valid JSON.

- [ ] **Step 6: Commit**

```bash
git add alert-sql-notification/governance-automation/tools/build_ds_zombie_lineage_workflow.py \
  alert-sql-notification/governance-automation/workflows/ds-zombie-task-lineage.workflow.json \
  alert-sql-notification/governance-automation/tests/test_ds_zombie_lineage_workflow.py
git commit -m "feat: add bounded DS task lineage workflow"
```

### Task 4: Render one Chinese task-level CSV and test the end-to-end contract

**Files:**
- Modify: `outputs/DS僵尸任务扫描_六国环境内嵌版.json`
- Modify: `alert-sql-notification/governance-automation/tests/test_ds_zombie_integration.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_scan.py`

- [ ] **Step 1: Write failing CSV behavior tests**

```python
def test_task_csv_never_calls_missing_detail_no_dependency():
    row = render_row({'downstream_count': 3, 'dependency_detail_status': 'unavailable'})
    self.assertIn('已识别 3 个下游依赖', row['显式下游依赖明细'])

def test_task_csv_has_required_task_lineage_columns():
    headers = csv_headers(render_task_row())
    self.assertIn('候选任务名称', headers)
    self.assertIn('表血缘下游明细（项目/工作流/任务/读取表）', headers)
```

- [ ] **Step 2: Update the Validate Python Summary Code node**

Render a single CSV with task-level records, Chinese status/action/boolean values, `无下游依赖` only for `dependency_detail_status='none'`, and no raw SQL, task parameters, token or evidence JSON. Preserve the manual country entry and existing six SSH nodes.

- [ ] **Step 3: Run end-to-end test**

Run: `cd alert-sql-notification/governance-automation && python3 -m unittest tests.test_ds_zombie_scan tests.test_ds_zombie_integration tests.test_ds_zombie_lineage_workflow -v`

Expected: PASS.

- [ ] **Step 4: Validate exported n8n JSON with synthetic summary**

Run a Node harness that provides two tasks in one workflow, one explicit downstream and one high-confidence table consumer. Assert two CSV rows, Chinese action labels, the correct project/workflow/task names, and no `REQUEST_DECOMMISSION_CONFIRMATION`, raw SQL or `evidence` header.

- [ ] **Step 5: Commit**

```bash
git add outputs/DS僵尸任务扫描_六国环境内嵌版.json \
  alert-sql-notification/governance-automation/tests/test_ds_zombie_integration.py \
  alert-sql-notification/governance-automation/tests/test_ds_zombie_scan.py
git commit -m "feat: export task-level DS zombie CSV"
```

### Task 5: Deploy read-only and verify Philippines output

**Files:**
- Modify: `alert-sql-notification/governance-automation/docs/DS_ZOMBIE_SCAN_LOGIC.md`

- [ ] **Step 1: Document deployment order and statuses**

Add the `dependency_detail_status` and `table_lineage_status` value meanings, plus a warning that the workflow is read-only and that no-Router-response is not no-dependency.

- [ ] **Step 2: Deploy Python code before importing JSON**

Use the existing country deployment flow to update the Philippines jump host to the committed repository revision. Verify `python3 remote_scripts/ds_zombie_scan.py --help` contains the task-lineage options before running n8n.

- [ ] **Step 3: Run Philippines single-project dry-run**

Run a project containing known `DEPENDENT` edges. Check one task with direct downstream, one task with no dependency, and one task with a table-lineage probe. Confirm CSV has task rows and no false “无下游依赖”.

- [ ] **Step 4: Run Philippines full read-only scan**

Confirm output is bounded by Router budgets and no DS schedules, definitions, tasks or resources were changed. Keep `write_to_db=false` for this acceptance run.

- [ ] **Step 5: Commit documentation**

```bash
git add alert-sql-notification/governance-automation/docs/DS_ZOMBIE_SCAN_LOGIC.md
git commit -m "docs: explain task-level DS lineage scan"
```
