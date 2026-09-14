from unittest.mock import MagicMock, patch

import httpx
import pytest
from docker.errors import NotFound

from sibase.control.config import Settings
from sibase.control.provision import Driver, credentials, tokens

REF = "p_0000000000000001"


@pytest.fixture
def driver():
    settings = Settings(
        database_url="sqlite://",
        images={k: k + ":pinned" for k in ("s3", "auth", "rest", "storage", "realtime")},
    )
    with patch("sibase.control.provision.docker.from_env") as docker:
        yield Driver(settings), docker.return_value


def test_names_and_complete_service_specifications(driver):
    d, docker = driver
    secret = credentials()
    internal = tokens(secret["jwt_secret"])
    docker.containers.get.side_effect = NotFound("missing")
    docker.volumes.get.side_effect = NotFound("missing")
    d.start(REF, secret, internal)
    assert docker.containers.create.call_count == 5
    storage = next(
        c.kwargs for c in docker.containers.create.call_args_list if "storage" in c.kwargs["name"]
    )
    assert "_" not in storage["environment"]["GLOBAL_S3_BUCKET"]
    assert storage["environment"]["DATABASE_URL"].startswith("postgres://" + REF + "_storage:")
    assert all("ports" not in c.kwargs for c in docker.containers.create.call_args_list)
    with pytest.raises(ValueError):
        d.name("../../foreign", "auth")


def test_owned_container_reuse_configuration_drift_and_collision(driver):
    d, docker = driver
    container = docker.containers.get.return_value
    container.labels = {"sibase.stack": d.settings.stack, "sibase.project": REF}
    container.attrs = {"Config": {"Env": ["KEY=value"]}}
    container.status = "running"
    d.ensure_container(REF, "auth", {"KEY": "value"})
    docker.containers.create.assert_not_called()
    d.ensure_container(REF, "auth", {"KEY": "updated"})
    container.remove.assert_called_once_with(v=False)
    container.labels = {}
    with pytest.raises(RuntimeError):
        d.ensure_container(REF, "auth", {})
    with pytest.raises(RuntimeError):
        d.stop(REF)
    docker.volumes.get.return_value.attrs = {"Labels": {}}
    with pytest.raises(RuntimeError):
        d.start(REF, credentials(), {})


def test_stop_is_idempotent_and_keeps_volumes(driver):
    d, docker = driver
    container = docker.containers.get.return_value
    container.labels = {"sibase.stack": d.settings.stack, "sibase.project": REF}
    container.status = "running"
    d.stop(REF)
    assert container.stop.call_count == 5
    container.remove.assert_not_called()
    docker.volumes.remove.assert_not_called()
    docker.containers.get.side_effect = NotFound("missing")
    d.stop(REF)


def test_database_bootstrap_and_identity_marker(driver):
    d, _ = driver
    connection = MagicMock()
    with patch.object(d, "connect") as connect:
        connect.return_value.__enter__.return_value = connection
        connection.execute.return_value.fetchone.side_effect = [None, (None,)]
        d.bootstrap(REF, "project", credentials())
        statements = [str(c.args[0]) for c in connection.execute.call_args_list]
        assert any("CREATE DATABASE" in s for s in statements)
        assert any("CREATE ROLE " + REF + "_auth" in s for s in statements)
        connection.execute.return_value.fetchone.side_effect = [(1,), ("marker",), ("project",)]
        d.bootstrap(REF, "project", credentials())
        connection.execute.return_value.fetchone.side_effect = [(1,), ("marker",), ("foreign",)]
        with pytest.raises(RuntimeError):
            d.bootstrap(REF, "project", credentials())
        connection.execute.return_value.fetchone.side_effect = [(1,), (None,)]
        bad = credentials()
        bad["passwords"]["auth"] = "unsafe'"
        with pytest.raises(ValueError):
            d.bootstrap(REF, "project", bad)


def test_health_checks_and_bounded_retry(driver):
    d, _ = driver
    secret = credentials()
    internal = tokens(secret["jwt_secret"])
    with (
        patch("sibase.control.provision.httpx.Client") as http,
        patch("sibase.control.provision.psycopg.connect"),
        patch("sibase.control.provision.boto3.client") as s3,
        patch("sibase.control.provision.socket.gethostbyname", return_value="172.18.0.10"),
    ):
        response = http.return_value.__enter__.return_value.get.return_value
        response.json.return_value = {"data": {"healthy": True}, "Topology": {"DataCenters": [{}]}}
        d.health(REF, secret, internal)
        s3.return_value.create_bucket.assert_called_with(Bucket="sibase-p-0000000000000001")
        response.json.return_value = {"data": {"healthy": False}}
        with pytest.raises(RuntimeError):
            d.health(REF, secret, internal)
        response.json.return_value = {"data": {"healthy": True}}
        with pytest.raises(RuntimeError):
            d.health(REF, secret, internal)
    with patch.object(d, "health") as health, patch("sibase.control.provision.time.sleep"):
        health.side_effect = [httpx.ConnectError("not ready"), None]
        d.await_health(REF, secret, internal)
        assert health.call_count == 2
        health.side_effect = RuntimeError("not ready")
        with pytest.raises(RuntimeError):
            d.await_health(REF, secret, internal)
