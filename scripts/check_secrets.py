"""Check Git-visible files without printing any matched credential values."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local/sibase-control"
PATTERN = re.compile(
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    r"|sb_(?:anon|service_role)_[A-Za-z0-9_-]{30,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


def values(item, all_values=False):
    found = set()
    if isinstance(item, dict):
        for key, value in item.items():
            sensitive = (
                all_values
                or key in {"password", "key", "access_token", "refresh_token"}
                or key.endswith(("_key", "_password", "_secret"))
            )
            found |= values(value, sensitive)
    elif isinstance(item, list):
        for value in item:
            found |= values(value, all_values)
    elif isinstance(item, str) and all_values and len(item) >= 16:
        found.add(item)
    return found


def main():
    known = set()
    for path in PRIVATE.glob("*.json"):
        known |= values(json.loads(path.read_text()), path.name == "secrets.json")
    files = (
        subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    failures = []
    for name in set(files) - {""}:
        path = ROOT / name
        if path.is_symlink():
            failures.append(name + " (symlink requires review)")
            continue
        if not path.is_file():
            continue
        content = path.read_text(errors="replace")
        if PATTERN.search(content) or any(secret in content for secret in known):
            failures.append(name)
    if failures:
        print("FAIL: possible credentials in files (values suppressed):")
        print("\n".join(sorted(failures)))
        raise SystemExit(1)
    print(
        "PASS: no known local credentials, full JWTs, opaque keys or private-key blocks in Git-visible files"
    )


if __name__ == "__main__":
    main()
