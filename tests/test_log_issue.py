from conftest import fake_secret, load


def test_issue_round_trip(workspace, hook):
    token = fake_secret("ghp_")
    added = hook("log_issue.py", args=["add", "Flaky checkout test", "--details", f"fails 1 in 5; token={token}",
                                       "--severity", "high", "--app", "example-api", "--kind", "flaky-test"])
    assert added.returncode == 0, added.stderr
    assert "ERR-0001" in added.stdout
    hook("log_issue.py", args=["add", "Registry row missing purpose"])

    listed = hook("log_issue.py", args=["list"])
    assert "ERR-0001" in listed.stdout and "ERR-0002" in listed.stdout
    only_app = hook("log_issue.py", args=["list", "--app", "example-api"])
    assert "ERR-0001" in only_app.stdout and "ERR-0002" not in only_app.stdout

    resolved = hook("log_issue.py", args=["resolve", "err-0001", "--resolution", "Pinned the clock in tests"])
    assert resolved.returncode == 0 and "Resolved ERR-0001" in resolved.stdout
    assert "ERR-0001" not in hook("log_issue.py", args=["list"]).stdout
    assert "ERR-0001" in hook("log_issue.py", args=["list", "--all"]).stdout

    data = load(workspace / "errors.json")
    assert data["summary"]["total"] == 2 and data["summary"]["open"] == 1
    first = data["errors"][0]
    assert first["status"] == "resolved" and first["resolution"] == "Pinned the clock in tests"
    assert first["kind"] == "flaky-test" and first["source"] == "manual"
    assert token not in (workspace / "errors.json").read_text(encoding="utf-8")


def test_resolve_unknown_id_fails(workspace, hook):
    result = hook("log_issue.py", args=["resolve", "ERR-9999", "--resolution", "n/a"])
    assert result.returncode == 1
    assert "No issue" in result.stderr


def test_list_with_no_log(workspace, hook):
    result = hook("log_issue.py", args=["list"])
    assert result.returncode == 0 and "No issues logged yet" in result.stdout


def test_bad_severity_rejected(workspace, hook):
    result = hook("log_issue.py", args=["add", "x", "--severity", "urgent"])
    assert result.returncode != 0
