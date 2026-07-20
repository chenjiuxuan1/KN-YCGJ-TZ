"""Transactional persistence for DS zombie governance evidence."""

import json
from typing import Any, Dict, Iterable


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
  country VARCHAR(16) NOT NULL,
  batch_id VARCHAR(96) NOT NULL,
  workflow_code VARCHAR(64) NOT NULL,
  score_version VARCHAR(32) NOT NULL,
  project_code VARCHAR(64), project_name VARCHAR(255), workflow_name VARCHAR(255),
  owner_name VARCHAR(255), level CHAR(1), score_total INT, action VARCHAR(64),
  protected_by_dependency TINYINT, protected_by_uncertainty TINYINT,
  upstream_count INT, downstream_count INT, reasons_json JSON, evidence_json JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY(country,batch_id,workflow_code,score_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""".strip()


def candidate_upsert_sql(table: str) -> str:
    return f"""INSERT INTO {table}
(country,batch_id,workflow_code,score_version,project_code,project_name,workflow_name,
 owner_name,level,score_total,action,protected_by_dependency,protected_by_uncertainty,
 upstream_count,downstream_count,reasons_json,evidence_json)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE level=VALUES(level),score_total=VALUES(score_total),
action=VALUES(action),protected_by_dependency=VALUES(protected_by_dependency),
protected_by_uncertainty=VALUES(protected_by_uncertainty),upstream_count=VALUES(upstream_count),
downstream_count=VALUES(downstream_count),reasons_json=VALUES(reasons_json),
evidence_json=VALUES(evidence_json)"""


class GovernanceStore:
    def __init__(self, config: Dict[str, Any], table: str = "ds_zombie_workflow_governance"):
        self.config, self.table = config, table

    def persist(self, rows: Iterable[Dict[str, Any]]) -> int:
        import pymysql
        connection = pymysql.connect(**self.config)
        values = list(rows)
        try:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA_SQL.format(table=self.table))
                sql = candidate_upsert_sql(self.table)
                for row in values:
                    cursor.execute(sql, (
                        row["country"], row["batch_id"], row["workflow_code"], row["score_version"],
                        row.get("project_code"), row.get("project_name"), row.get("workflow_name"),
                        row.get("owner_name"), row.get("level"), row.get("score_total"), row.get("action"),
                        int(bool(row.get("protected_by_dependency"))), int(bool(row.get("protected_by_uncertainty"))),
                        row.get("upstream_count", 0), row.get("downstream_count", 0),
                        json.dumps(row.get("reasons", []), ensure_ascii=False),
                        json.dumps(row.get("evidence", {}), ensure_ascii=False, default=str),
                    ))
            connection.commit()
            return len(values)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
