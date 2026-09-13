"""HTTP smoke through the Dashboard proxy (not a browser rendering test)."""

import argparse
import json
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:58200")
args = parser.parse_args()


def get(path):
    return urllib.request.urlopen(args.url + path, timeout=30)


with get("/") as response:
    assert "SiBase" in response.read().decode()
for module in ("main.tsx", "App.tsx", "api.ts"):
    with get("/" + module) as response:
        assert "javascript" in response.headers.get("Content-Type", "")
        assert "<!doctype html" not in response.read().decode().lower()
with get("/api/v1/health") as response:
    assert json.load(response)["status"] == "ready"
with get("/health/live") as response:
    assert json.load(response)["status"] == "ok"
with get("/health/ready") as response:
    assert json.load(response)["status"] == "ready"
with get("/api/v1/overview") as response:
    assert response.headers.get("X-Request-ID")
    data = json.load(response)
assert data["platform"]["status"] == "up"
assert {p["ref"] for p in data["projects"]} == {"alpha", "beta"}
assert all(p["status"] == "healthy" and len(p["services"]) == 5 for p in data["projects"])
serialized = json.dumps(data).lower()
assert all(
    secret not in serialized
    for secret in ("password", "jwt_secret", "service_key", "postgresql://")
)
with get("/api/openapi.json") as response:
    assert "/api/v1/overview" in json.load(response)["paths"]
try:
    urllib.request.urlopen(
        urllib.request.Request(args.url + "/api/v1/overview", data=b"{}"), timeout=10
    )
except urllib.error.HTTPError as error:
    assert error.code == 405
else:
    raise AssertionError("Read-only endpoint accepted POST")
print(
    "PASS: Dashboard HTML/modules, proxy, readiness, two live projects, OpenAPI, safe response and read-only contract."
)
