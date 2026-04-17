from __future__ import annotations

import json

from agentic_forex.runtime.models import WorkflowDefinition
from agentic_forex.utils.paths import ProjectPaths


class WorkflowRepository:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def load(self, workflow_id: str) -> WorkflowDefinition:
        workflow_path = self.paths.workflows_dir / f"{workflow_id}.json"
        payload = json.loads(workflow_path.read_text(encoding="utf-8"))
        return WorkflowDefinition.model_validate(payload)
