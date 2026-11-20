from pathlib import Path

import yaml


def test_ci_runs_checks_and_publishes_offline_docs_without_cleanup_permissions():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert "pull_request" in workflow["on"]
    assert "main" in workflow["on"]["push"]["branches"]
    assert workflow["permissions"] == {"contents": "read"}
    backend = workflow["jobs"]["backend"]["steps"]
    commands = "\n".join(step.get("run", "") for step in backend)
    assert "make type-check" in commands
    assert "make test-local-quick" in commands
    assert "scripts/export_api_docs.py" in commands
    assert any(step.get("uses", "").startswith("actions/upload-artifact@") for step in backend)
    frontend = workflow["jobs"]["frontend"]
    assert frontend["defaults"]["run"]["working-directory"] == "frontend"
    assert any("npm run build:prod" in step.get("run", "") for step in frontend["steps"])
