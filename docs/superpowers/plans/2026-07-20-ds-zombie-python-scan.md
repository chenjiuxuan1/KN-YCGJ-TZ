# DS Zombie Python Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the large n8n JSON pipeline with a Python DS zombie scanner that discovers upstream/downstream dependencies, applies SOP-safe grading, persists governance evidence, and returns only a bounded summary.

**Architecture:** A small CLI orchestrates a read-only DS repository, workflow aggregation, dependency graph construction, scoring, and an optional transactional governance writer. The n8n workflow invokes the CLI over each existing country SSH route and validates the bounded stdout contract; it never receives raw DS metadata arrays.

**Tech Stack:** Python 3 standard library, MySQL CLI subprocess adapter, `unittest`, n8n workflow JSON, Git.

---

## File structure

- Create `governance_automation/ds_zombie_models.py`: typed records and three-state evidence helpers.
- Create `governance_automation/ds_dependency_graph.py`: task DAG and cross-workflow dependency graph.
- Create `governance_automation/ds_zombie_classifier.py`: SOP scoring, levels, protection, and action selection.
- Create `governance_automation/ds_zombie_repository.py`: DS schema discovery and paged read-only queries.
- Create `governance_automation/ds_zombie_store.py`: idempotent transactional governance persistence.
- Create `governance_automation/ds_zombie_pipeline.py`: bounded-memory orchestration and summary contract.
- Create `remote_scripts/ds_zombie_scan.py`: environment-backed CLI and single JSON stdout.
- Create `tools/build_ds_zombie_scan_workflow.py`: secret-free n8n workflow generator.
- Create `workflows/ds-zombie-scan-python.workflow.json`: generated importable workflow.
- Create `docs/DS_ZOMBIE_SCAN_LOGIC.md`: complete Chinese decision and lineage documentation.
- Create `tests/test_ds_dependency_graph.py`, `tests/test_ds_zombie_classifier.py`, `tests/test_ds_zombie_pipeline.py`, `tests/test_ds_zombie_repository.py`, `tests/test_ds_zombie_store.py`, `tests/test_ds_zombie_cli.py`, and `tests/test_ds_zombie_workflow.py`.
- Modify `README.md`: operation, environment, dry-run, and rollout instructions.

### Task 1: Domain records and three-state evidence

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_zombie_models.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_models.py`

- [ ] **Step 1: Write the failing model tests**

```python
def test_unknown_evidence_is_not_absent():
    assert EvidenceState.UNKNOWN != EvidenceState.ABSENT

def test_workflow_key_is_country_project_workflow():
    row = WorkflowSnapshot(country="th", project_code="10", workflow_code="20")
    assert row.key == "th:10:20"
```

- [ ] **Step 2: Run the model tests and verify missing-module failure**

Run: `python3 -m unittest tests.test_ds_zombie_models -v`
Expected: FAIL because `ds_zombie_models` does not exist.

- [ ] **Step 3: Implement enums and dataclasses**

Implement `EvidenceState(PRESENT, ABSENT, UNKNOWN)`, `WorkflowSnapshot`, `DependencyEvidence`, `ScoreResult`, and `ScanSummary`. `ScanSummary.to_dict()` must emit only the documented n8n fields.

- [ ] **Step 4: Run the model tests**

Run: `python3 -m unittest tests.test_ds_zombie_models -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_zombie_models.py alert-sql-notification/governance-automation/tests/test_ds_zombie_models.py
git commit -m "feat: add DS zombie scan domain records"
```

### Task 2: Internal DAG and cross-workflow dependency graph

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_dependency_graph.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_dependency_graph.py`

- [ ] **Step 1: Write failing graph tests**

```python
def test_task_relations_build_internal_upstream_and_downstream():
    graph = build_internal_graph([{"workflow_code": "w1", "pre_task_code": "t1", "post_task_code": "t2"}])
    assert graph["w1"].task_downstream["t1"] == {"t2"}
    assert graph["w1"].task_upstream["t2"] == {"t1"}

def test_dependent_task_builds_reverse_workflow_downstream():
    deps = parse_cross_workflow_dependencies([dependent_task(source="w2", target="w1")])
    assert deps.workflow_downstream["w1"] == {"w2"}
    assert deps.workflow_upstream["w2"] == {"w1"}

def test_unparseable_dependency_protects_workflow():
    deps = parse_cross_workflow_dependencies([{"workflow_code": "w2", "task_type": "DEPENDENT", "task_params": "{"}])
    assert deps.scan_complete["w2"] is False
```

- [ ] **Step 2: Run graph tests and verify failure**

Run: `python3 -m unittest tests.test_ds_dependency_graph -v`
Expected: FAIL because graph functions do not exist.

- [ ] **Step 3: Implement graph construction**

Implement adjacency maps from task relation rows. Parse DS `DEPENDENT` task JSON recursively for project/process/task codes, record a `DependencyEvidence` per edge, and build the reverse index so a target workflow can list every downstream workflow that references it. Parse failures set `scan_complete=False` and retain a hashed/truncated evidence message.

- [ ] **Step 4: Run graph tests**

Run: `python3 -m unittest tests.test_ds_dependency_graph -v`
Expected: PASS, including reverse downstream and malformed JSON cases.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_dependency_graph.py alert-sql-notification/governance-automation/tests/test_ds_dependency_graph.py
git commit -m "feat: resolve DS workflow dependencies"
```

### Task 3: SOP classifier and dependency safety gate

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_zombie_classifier.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_classifier.py`

- [ ] **Step 1: Write failing scoring tests**

```python
def test_stale_inactive_complete_workflow_is_a_confirmation_candidate():
    result = classify(snapshot(stale_months=12, runs_30d=0, scan_complete=True, downstream=[]))
    assert result.level == "A"
    assert result.action == "REQUEST_DECOMMISSION_CONFIRMATION"

def test_downstream_dependency_blocks_decommission_action():
    result = classify(snapshot(stale_months=12, runs_30d=0, scan_complete=True, downstream=["w2"]))
    assert result.protected_by_dependency is True
    assert result.action == "RETAIN_AND_ASSESS"

def test_incomplete_dependency_scan_requires_more_evidence():
    result = classify(snapshot(stale_months=12, runs_30d=0, scan_complete=False, downstream=[]))
    assert result.level == "C"
    assert result.action == "COLLECT_EVIDENCE"

def test_recent_success_is_active_d():
    result = classify(snapshot(last_success_days=2, runs_30d=4))
    assert result.level == "D"
```

- [ ] **Step 2: Run classifier tests and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_classifier -v`
Expected: FAIL because `classify` does not exist.

- [ ] **Step 3: Implement explainable rules**

Implement a versioned rule table. Suspicion points come from stale update, stale/absent recent runs, and disabled schedules only when the associated scan is complete. Protection overrides come from recent activity, cross-workflow downstream, resource/data references, confirmed retention, and unknown dependency evidence. Return itemized `score_detail`; never return a DS mutation action.

- [ ] **Step 4: Run classifier tests**

Run: `python3 -m unittest tests.test_ds_zombie_classifier -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_zombie_classifier.py alert-sql-notification/governance-automation/tests/test_ds_zombie_classifier.py
git commit -m "feat: classify DS zombie governance candidates"
```

### Task 4: Read-only paged DS repository

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_zombie_repository.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_repository.py`

- [ ] **Step 1: Write failing repository tests**

```python
def test_repository_uses_limit_keyset_pages():
    client = RecordingClient(pages=[[{"id": 1}], [{"id": 2}], []])
    rows = list(DsZombieRepository(client).iter_workflows(page_size=1))
    assert rows == [{"id": 1}, {"id": 2}]
    assert all("LIMIT" in call.sql and "id >" in call.sql for call in client.calls)

def test_repository_queries_are_read_only():
    for sql in DsZombieRepository.query_templates():
        assert sql.lstrip().upper().startswith(("SELECT", "SHOW", "DESCRIBE"))
```

- [ ] **Step 2: Run repository tests and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_repository -v`
Expected: FAIL because repository does not exist.

- [ ] **Step 3: Implement schema capabilities and queries**

Use `information_schema` to discover DS table/column capabilities. Add keyset-paged queries for projects, process definitions, task definitions, task relations, schedules, process instances, task instances, and dependent task parameters. Support known DS naming variants through an explicit capability map. Bind filter values and reject non-read-only statements.

- [ ] **Step 4: Run repository tests**

Run: `python3 -m unittest tests.test_ds_zombie_repository -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_zombie_repository.py alert-sql-notification/governance-automation/tests/test_ds_zombie_repository.py
git commit -m "feat: add paged DS zombie metadata repository"
```

### Task 5: Idempotent governance store

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_zombie_store.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_store.py`

- [ ] **Step 1: Write failing transaction and idempotency tests**

```python
def test_store_upserts_by_batch_workflow_and_version():
    store.persist(batch(), [candidate(workflow_code="20")], [])
    store.persist(batch(), [candidate(workflow_code="20")], [])
    assert store.count_candidates() == 1

def test_failed_candidate_write_marks_batch_failed():
    store.fail_candidate_insert = True
    with self.assertRaises(StoreError):
        store.persist(batch(), [candidate()], [])
    assert store.batch_status() == "FAILED"
```

- [ ] **Step 2: Run store tests and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_store -v`
Expected: FAIL because store does not exist.

- [ ] **Step 3: Implement explicit schema and transaction**

Provide versioned DDL for batch, workflow candidate, and dependency evidence tables. Use the idempotency key `country,batch_id,workflow_code,score_version`. Begin the batch before inserts, commit evidence and candidates together, and mark the batch failed with a sanitized error on rollback.

- [ ] **Step 4: Run store tests**

Run: `python3 -m unittest tests.test_ds_zombie_store -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_zombie_store.py alert-sql-notification/governance-automation/tests/test_ds_zombie_store.py
git commit -m "feat: persist DS zombie governance evidence"
```

### Task 6: Pipeline and bounded summary

**Files:**
- Create: `alert-sql-notification/governance-automation/governance_automation/ds_zombie_pipeline.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

```python
def test_pipeline_returns_counts_and_only_top_twenty():
    result = run_scan(repository_with_workflows(100), store=None, top_limit=20)
    assert result["scanned_workflows"] == 100
    assert len(result["top_candidates"]) == 20
    assert "data" not in result and "candidates" not in result

def test_pipeline_counts_dependency_protection():
    result = run_scan(repository_with_dependency(target="w1", source="w2"), store=None)
    assert result["dependency_protected_count"] == 1
```

- [ ] **Step 2: Run pipeline tests and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_pipeline -v`
Expected: FAIL because pipeline does not exist.

- [ ] **Step 3: Implement orchestration**

Aggregate repository streams by workflow, attach internal/cross-workflow graphs, classify every workflow, optionally persist candidates and evidence, and maintain only counters plus a bounded heap for Top N. Validate `top_limit <= 100` and emit the documented summary fields.

- [ ] **Step 4: Run pipeline tests**

Run: `python3 -m unittest tests.test_ds_zombie_pipeline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/governance_automation/ds_zombie_pipeline.py alert-sql-notification/governance-automation/tests/test_ds_zombie_pipeline.py
git commit -m "feat: orchestrate bounded DS zombie scan"
```

### Task 7: CLI, secret handling, and stdout contract

**Files:**
- Create: `alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_requires_password_from_environment_not_argument():
    help_text = run_cli("--help").stdout
    assert "--ds-db-password" not in help_text

def test_cli_stdout_is_one_small_json_document():
    result = run_fixture_cli(top_limit=20)
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert len(result.stdout.encode()) < 200_000
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_cli -v`
Expected: FAIL because CLI does not exist.

- [ ] **Step 3: Implement CLI and structured errors**

Parse the approved arguments, read connections only from environment variables, send operational logs to stderr/local log, and print exactly one JSON summary to stdout. Return stage-specific errors for connection, discovery, read, dependency, score, persistence, and output failures.

- [ ] **Step 4: Run CLI tests**

Run: `python3 -m unittest tests.test_ds_zombie_cli -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/remote_scripts/ds_zombie_scan.py alert-sql-notification/governance-automation/tests/test_ds_zombie_cli.py
git commit -m "feat: add DS zombie scan CLI"
```

### Task 8: Secret-free n8n workflow

**Files:**
- Create: `alert-sql-notification/governance-automation/tools/build_ds_zombie_scan_workflow.py`
- Create: `alert-sql-notification/governance-automation/workflows/ds-zombie-scan-python.workflow.json`
- Test: `alert-sql-notification/governance-automation/tests/test_ds_zombie_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

```python
def test_generated_workflow_has_no_password_literal_or_large_parse_nodes():
    workflow = build_workflow()
    text = json.dumps(workflow)
    assert "DS_DB_PASSWORD=" not in text
    names = {node["name"] for node in workflow["nodes"]}
    assert "Build Zombie Workflow Candidates" not in names
    assert "Parse DS Metadata Result" not in names

def test_each_country_invokes_same_python_entrypoint():
    workflow = build_workflow()
    commands = ssh_commands(workflow)
    assert len(commands) == 6
    assert all("remote_scripts/ds_zombie_scan.py" in command for command in commands)
```

- [ ] **Step 2: Run workflow tests and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_workflow -v`
Expected: FAIL because generator does not exist.

- [ ] **Step 3: Implement and generate workflow**

Preserve the manual request and six country routes. Each SSH node invokes the same deployed CLI and expects connection secrets to exist in the remote environment. Add a small summary validation Code node that rejects `top_candidates > 100` or unexpected bulk fields.

- [ ] **Step 4: Run workflow tests and regenerate artifact**

Run: `python3 tools/build_ds_zombie_scan_workflow.py && python3 -m unittest tests.test_ds_zombie_workflow -v`
Expected: workflow generated and tests PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/tools/build_ds_zombie_scan_workflow.py alert-sql-notification/governance-automation/workflows/ds-zombie-scan-python.workflow.json alert-sql-notification/governance-automation/tests/test_ds_zombie_workflow.py
git commit -m "feat: generate compact DS zombie n8n workflow"
```

### Task 9: Complete Chinese logic and operations documentation

**Files:**
- Create: `alert-sql-notification/governance-automation/docs/DS_ZOMBIE_SCAN_LOGIC.md`
- Modify: `alert-sql-notification/governance-automation/README.md`

- [ ] **Step 1: Write the documentation assertions**

Add a test in `tests/test_ds_zombie_workflow.py` that requires the logic document to contain the headings `任务级 DAG`, `跨工作流下游反查`, `依赖不完整保护`, `A/B/C/D`, `治理动作`, `数据表与字段`, and `上线与回滚`.

- [ ] **Step 2: Run the assertion and verify failure**

Run: `python3 -m unittest tests.test_ds_zombie_workflow -v`
Expected: FAIL because the logic document is missing.

- [ ] **Step 3: Write complete decision documentation**

Document exact source table roles, capability fallbacks, task relation graph construction, recursive `DEPENDENT` extraction, reverse downstream index, external evidence states, point rules, protection overrides, persistence fields, summary example, dry-run commands, production environment variables, rollout, and rollback. Add README links and operation examples without secrets.

- [ ] **Step 4: Run documentation assertions**

Run: `python3 -m unittest tests.test_ds_zombie_workflow -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add alert-sql-notification/governance-automation/docs/DS_ZOMBIE_SCAN_LOGIC.md alert-sql-notification/governance-automation/README.md alert-sql-notification/governance-automation/tests/test_ds_zombie_workflow.py
git commit -m "docs: explain DS zombie scan decision logic"
```

### Task 10: Full verification and push

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run the complete governance test suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS with zero failures and zero errors.

- [ ] **Step 2: Validate JSON and secret scan**

Run: `python3 -m json.tool workflows/ds-zombie-scan-python.workflow.json >/dev/null`
Expected: exit 0.

Run: `rg -n "DS_DB_PASSWORD=|GOVERNANCE_DB_PASSWORD=|password\s*[:=]\s*['\"][^$]" remote_scripts tools workflows docs governance_automation tests`
Expected: no committed secret literal; environment-variable names in documentation are allowed and reviewed manually.

- [ ] **Step 3: Check repository state and diff**

Run: `git diff --check && git status --short && git log --oneline -12`
Expected: no whitespace errors; only planned files changed/committed.

- [ ] **Step 4: Push main**

Run: `git push origin main`
Expected: remote `main` advances to the verified local HEAD.

- [ ] **Step 5: Record handoff evidence**

Report the pushed commit, tests executed, workflow path, logic document path, environment prerequisites, and the fact that no production DS mutation or database schema change was executed during local implementation.
