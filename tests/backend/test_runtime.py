import io
import json
import stat
import sys
from unittest.mock import Mock

import phase1
import pytest


def test_generation_is_idempotent_and_role_secrets_are_separated(tmp_path):
    ports = {
        "SIBASE_DASHBOARD_PORT": 58200,
        "SIBASE_API_PORT": 58210,
        "SIBASE_PROJECT_PORT_BASE": 58201,
    }
    phase1.prepare("sibase-test", tmp_path, ports)
    state = (tmp_path / "secrets.json").read_text()
    platform = (tmp_path / "platform-secrets.json").read_text()
    phase1.prepare("sibase-test", tmp_path, ports)
    assert state == (tmp_path / "secrets.json").read_text()
    assert platform == (tmp_path / "platform-secrets.json").read_text()
    values = json.loads(state)
    passwords = [
        password
        for project in values["projects"].values()
        for password in project["passwords"].values()
    ]
    assert len(passwords) == len(set(passwords)) == 12
    assert all("password" not in p for p in values["projects"].values())
    bootstrap = (tmp_path / "init.sql").read_text()
    assert "@PASSWORD@" not in bootstrap and "_PASSWORD@" not in bootstrap
    compose = json.loads((tmp_path / "compose.json").read_text())
    assert compose["name"] == "sibase-test"
    serialized = json.dumps(compose)
    assert not any(password in serialized for password in passwords)
    api = (tmp_path / "api.json").read_text()
    assert values["admin_password"] not in api
    for project in values["projects"].values():
        for role in ("auth", "rest", "owner", "storage", "realtime"):
            assert project["passwords"][role] not in api
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "secrets.json").stat().st_mode) == 0o600
    for name, service in compose["services"].items():
        if "ports" in service:
            assert all(p.startswith("127.0.0.1:") for p in service["ports"]), name
    assert "ports" not in compose["services"]["platform-db"]


def test_configuration_rejects_conflicting_ports(tmp_path, monkeypatch):
    monkeypatch.setattr(phase1, "ROOT", tmp_path)
    monkeypatch.setenv("SIBASE_DASHBOARD_PORT", "58201")
    with pytest.raises(ValueError, match="unique"):
        phase1.configuration()


def test_configuration_rejects_secret_or_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(phase1, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("PASSWORD=not-supported")
    with pytest.raises(ValueError, match="non-secret"):
        phase1.configuration()


@pytest.fixture
def saved_runtime(tmp_path):
    local = tmp_path / ".local" / "sibase-fresh"
    local.mkdir(parents=True)
    compose = {
        "name": "sibase-fresh",
        "services": {
            "dashboard": {"ports": ["127.0.0.1:58300:5173"]},
            "api": {"ports": ["127.0.0.1:58310:8000"]},
            "gateway": {"ports": ["127.0.0.1:58301:8001", "127.0.0.1:58302:8002"]},
        },
    }
    (local / "compose.json").write_text(json.dumps(compose))
    return local


def test_smoke_uses_selected_stack_ports_not_current_environment(
    saved_runtime, tmp_path, monkeypatch
):
    monkeypatch.setattr(phase1, "ROOT", tmp_path)
    monkeypatch.setenv("SIBASE_DASHBOARD_PORT", "58200")
    monkeypatch.setattr(sys, "argv", ["phase1.py", "smoke", "--stack", "sibase-fresh"])
    run = Mock()
    monkeypatch.setattr(phase1.subprocess, "run", run)
    phase1.main()
    assert run.call_args.args[0][-2:] == ["--url", "http://127.0.0.1:58300"]


def test_existing_dev_keeps_saved_ports_and_waits_for_dashboard(
    saved_runtime, tmp_path, monkeypatch
):
    monkeypatch.setattr(phase1, "ROOT", tmp_path)
    for key in ("SIBASE_DASHBOARD_PORT", "SIBASE_API_PORT", "SIBASE_PROJECT_PORT_BASE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "argv", ["phase1.py", "dev", "--stack", "sibase-fresh"])
    prepare, docker, ready = Mock(), Mock(), Mock()
    monkeypatch.setattr(phase1, "prepare", prepare)
    monkeypatch.setattr(phase1, "docker", docker)
    monkeypatch.setattr(phase1, "wait_ready", ready)
    phase1.main()
    assert prepare.call_args.args[2]["SIBASE_DASHBOARD_PORT"] == 58300
    docker.assert_called_once_with("sibase-fresh", saved_runtime, "up", "-d", "--build")
    ready.assert_called_once_with(58310, 58300)


def test_explicit_port_override_can_update_saved_configuration(
    saved_runtime, tmp_path, monkeypatch
):
    monkeypatch.setattr(phase1, "ROOT", tmp_path)
    for key in ("SIBASE_API_PORT", "SIBASE_PROJECT_PORT_BASE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SIBASE_DASHBOARD_PORT", "58400")
    saved = phase1.runtime_configuration("sibase-fresh", saved_runtime)
    assert phase1.configuration(saved) == {**saved, "SIBASE_DASHBOARD_PORT": 58400}


def test_runtime_configuration_rejects_wrong_stack(saved_runtime):
    with pytest.raises(ValueError, match="selected stack"):
        phase1.runtime_configuration("sibase-another", saved_runtime)


@pytest.mark.parametrize(
    ("service", "bindings"),
    [
        ("dashboard", ["0.0.0.0:58300:5173"]),
        ("api", ["127.0.0.1:58300:8000"]),
        ("gateway", ["127.0.0.1:58301:8001", "127.0.0.1:58402:8002"]),
    ],
)
def test_runtime_configuration_rejects_invalid_bindings(saved_runtime, service, bindings):
    path = saved_runtime / "compose.json"
    compose = json.loads(path.read_text())
    compose["services"][service]["ports"] = bindings
    path.write_text(json.dumps(compose))
    with pytest.raises(ValueError):
        phase1.runtime_configuration("sibase-fresh", saved_runtime)


def response(body, content_type="application/json"):
    result = io.BytesIO(body.encode())
    result.headers = {"Content-Type": content_type}
    return result


@pytest.mark.parametrize("broken", [None, "/", "/api.ts", "/api/v1/health"])
def test_dashboard_readiness_requires_html_modules_and_proxy(monkeypatch, broken):
    def get(url, **kwargs):
        path = url.removeprefix("http://127.0.0.1:58300")
        if path == "/":
            return response("unrelated app" if broken == path else "SiBase", "text/html")
        if path == "/api/v1/health":
            return response(json.dumps({"status": "not_ready" if broken == path else "ready"}))
        return response("export {}", "text/html" if broken == path else "text/javascript")

    monkeypatch.setattr(phase1.urllib.request, "urlopen", get)
    assert phase1.dashboard_ready(58300) is (broken is None)


def test_wait_ready_retries_until_dashboard_is_ready(monkeypatch):
    overview = {"platform": {"status": "up"}, "projects": [{"status": "healthy"}]}
    monkeypatch.setattr(
        phase1.urllib.request, "urlopen", lambda *a, **k: response(json.dumps(overview))
    )
    dashboard = Mock(side_effect=[OSError("not listening"), False, True])
    monkeypatch.setattr(phase1, "dashboard_ready", dashboard)
    sleep = Mock()
    monkeypatch.setattr(phase1.time, "sleep", sleep)
    phase1.wait_ready(58310, 58300)
    assert dashboard.call_count == 3
    assert all(call.args == (58300,) for call in dashboard.call_args_list)
    assert sleep.call_count == 2


def test_available_api_cannot_hide_dashboard_timeout(monkeypatch):
    overview = {"platform": {"status": "up"}, "projects": [{"status": "healthy"}]}
    monkeypatch.setattr(
        phase1.urllib.request, "urlopen", lambda *a, **k: response(json.dumps(overview))
    )
    monkeypatch.setattr(phase1, "dashboard_ready", Mock(side_effect=OSError("offline")))
    monkeypatch.setattr(phase1.time, "monotonic", Mock(side_effect=[0, 1, 241]))
    monkeypatch.setattr(phase1.time, "sleep", Mock())
    with pytest.raises(RuntimeError, match="Readiness timed out"):
        phase1.wait_ready(58310, 58300)


@pytest.mark.parametrize("projects", [[], [{"status": "degraded"}]])
def test_wait_ready_rejects_empty_or_unhealthy_projects(monkeypatch, projects):
    overview = {"platform": {"status": "up"}, "projects": projects}
    monkeypatch.setattr(
        phase1.urllib.request, "urlopen", lambda *a, **k: response(json.dumps(overview))
    )
    dashboard = Mock(return_value=True)
    monkeypatch.setattr(phase1, "dashboard_ready", dashboard)
    monkeypatch.setattr(phase1.time, "monotonic", Mock(side_effect=[0, 1, 241]))
    monkeypatch.setattr(phase1.time, "sleep", Mock())
    with pytest.raises(RuntimeError, match="Readiness timed out"):
        phase1.wait_ready(58310, 58300)
    dashboard.assert_not_called()
