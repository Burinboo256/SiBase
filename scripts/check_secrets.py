"""Check Git-visible files without printing any matched credential values."""

import argparse
import json
import re
import subprocess
import sys
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


def main(files=None):
    known = set()
    for path in PRIVATE.glob("*.json"):
        known |= values(json.loads(path.read_text()), path.name == "secrets.json")
    if files is None:
        files = (
            subprocess.check_output(
                ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT
            )
            .decode()
            .split("\0")
        )
    if not set(files) - {""}:
        raise SystemExit("FAIL: empty Git inventory; no audit performed")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files-stdin", action="store_true", help="Read NUL-separated Git file paths from stdin"
    )
    args = parser.parse_args()
    main(sys.stdin.read().split("\0") if args.files_stdin else None)
