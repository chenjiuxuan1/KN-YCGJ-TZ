import fs from "fs";

const files = [
  "outputs/sql优化_main_execute_workflow_部门账号联系人通知_读取仓库CSV版.json",
  "/private/tmp/KN-YCGJ-TZ-alert-sync/alert-sql-notification/workflows/sql-optimizer-notify-repo-csv.workflow.json",
];

const positions = {
  "Notify Config": [51880, 21296],
  "Pull Contact CSV Repo": [52100, 21296],
  "Fetch Contact Overrides": [52320, 21296],
  "Get User Info": [52540, 21296],
  "Merge Notify Target": [52760, 21296],
};

for (const file of files) {
  const workflow = JSON.parse(fs.readFileSync(file, "utf8"));
  workflow.nodes = workflow.nodes.filter((node) => node.name !== "Has Contact Override URL?");

  for (const node of workflow.nodes) {
    if (positions[node.name]) node.position = positions[node.name];
    if (node.name === "Fetch Contact Overrides") {
      node.name = "Read Contact CSV";
      node.notes = "从仓库内唯一联系人 CSV 读取映射行，并传给 Merge Notify Target。需要 NODE_FUNCTION_ALLOW_BUILTIN=fs。";
    }
  }

  const renameTarget = (connection) => {
    if (!connection || !Array.isArray(connection.main)) return connection;
    for (const branch of connection.main) {
      for (const edge of branch) {
        if (edge.node === "Fetch Contact Overrides") edge.node = "Read Contact CSV";
        if (edge.node === "Has Contact Override URL?") edge.node = "Pull Contact CSV Repo";
      }
    }
    return connection;
  };

  for (const [name, connection] of Object.entries(workflow.connections || {})) {
    renameTarget(connection);
    if (name === "Fetch Contact Overrides") {
      workflow.connections["Read Contact CSV"] = connection;
      delete workflow.connections[name];
    }
  }
  delete workflow.connections["Has Contact Override URL?"];

  workflow.connections["Notify Config"] = {
    main: [[{ node: "Pull Contact CSV Repo", type: "main", index: 0 }]],
  };
  workflow.connections["Pull Contact CSV Repo"] = {
    main: [[{ node: "Read Contact CSV", type: "main", index: 0 }]],
  };
  workflow.connections["Read Contact CSV"] = {
    main: [[{ node: "Get User Info", type: "main", index: 0 }]],
  };
  workflow.connections["Get User Info"] = {
    main: [[{ node: "Merge Notify Target", type: "main", index: 0 }]],
  };

  for (const node of workflow.nodes) {
    if (node.parameters && node.parameters.jsCode) new Function(node.parameters.jsCode);
  }

  fs.writeFileSync(file, JSON.stringify(workflow, null, 2) + "\n");
  console.log(file);
}
