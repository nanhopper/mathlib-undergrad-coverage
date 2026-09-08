from pathlib import Path

import yaml


def test_pull_requests_do_not_replace_pending_publication():
    workflow_path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "dashboard.yml"
    )
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    concurrency = workflow["concurrency"]
    refs = ["refs/heads/main", "refs/pull/42/merge", "refs/pull/43/merge"]
    groups = {
        concurrency["group"].replace("${{ github.ref }}", ref)
        for ref in refs
    }

    assert len(groups) == len(refs), "PR validation must not share the publication queue"
    assert concurrency["cancel-in-progress"] is False
