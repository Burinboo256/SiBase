"""Read-only verification after a full Phase 2 stop/dev cycle."""

import json
import time
from pathlib import Path

import httpx


def main():
    local = Path(".local/sibase-control")
    fixtures = json.loads((local / "sdk-fixture.json").read_text())
    with httpx.Client(timeout=20) as client:
        for project in fixtures["projects"]:
            base = "http://gateway:8000/p/" + project["ref"]
            headers = {"apikey": project["service_key"]}
            for _ in range(90):
                response = client.get(base + "/rest/v1/phase2_probe", headers=headers)
                if response.status_code == 200:
                    break
                time.sleep(2)
            assert response.json()[0]["marker"] == project["ref"]
            buckets = client.get(base + "/storage/v1/bucket", headers=headers).json()
            bucket = next(b["id"] for b in buckets if b["id"].startswith("phase2-"))
            obj = client.get(base + "/storage/v1/object/" + bucket + "/proof.txt", headers=headers)
            assert obj.status_code == 200 and obj.text == "retained phase2 proof"
            print(
                "PASS: full-stack restart retained row and S3 object for",
                project["name"],
                flush=True,
            )
    Path("docs/evidence/phase2-restart.json").write_text(
        json.dumps(
            {
                "projects": [p["name"] for p in fixtures["projects"]],
                "rows_preserved": True,
                "objects_preserved": True,
            },
            indent=4,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
