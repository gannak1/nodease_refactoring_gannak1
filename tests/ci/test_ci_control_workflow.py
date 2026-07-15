from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "pr-ci-control-guard.yml"


def _ci_control_job_lines(workflow_lines: list[str]) -> list[str]:
    start = workflow_lines.index("  ci_control_review:")
    end = next(
        (
            index
            for index in range(start + 1, len(workflow_lines))
            if workflow_lines[index].startswith("  ")
            and not workflow_lines[index].startswith("    ")
        ),
        len(workflow_lines),
    )
    return workflow_lines[start:end]


def test_unrelated_issue_comments_cannot_cancel_ci_control_review():
    workflow_lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    job_lines = _ci_control_job_lines(workflow_lines)

    assert "concurrency:" not in workflow_lines
    assert "    concurrency:" in job_lines
    assert (
        "      group: trusted-ci-control-${{ github.event.pull_request.number || "
        "github.event.issue.number || github.run_id }}"
        in job_lines
    )
    assert "      cancel-in-progress: true" in job_lines
    assert "       github.event.comment.body == '/recheck-ci-control')" in job_lines
