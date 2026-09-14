#!/usr/bin/env python3
"""Phase 3 extends the existing local control-plane stack; never deletes data."""

import argparse
import subprocess
import sys

from phase2 import ROOT, compose, prepare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["dev", "prepare", "check", "integration", "e2e", "status"]
    )
    args = parser.parse_args()
    if args.command in {"dev", "check", "status"}:
        subprocess.run([sys.executable, str(ROOT / "scripts/phase2.py"), args.command], check=True)
    if args.command in {"prepare", "integration"}:
        options = ["--prepare"] if args.command == "prepare" else []
        compose("run", "--rm", "tools", "python", "tests/integration/phase3.py", *options)
    if args.command == "integration":
        compose(
            "run",
            "--rm",
            "sdk",
            "sh",
            "-ec",
            "npm ci --ignore-scripts --no-audit --no-fund && node /workspace/tests/integration/phase3-sdk.mjs",
        )
    if args.command == "e2e":
        prepare()
        compose("run", "--rm", "browser")


if __name__ == "__main__":
    main()
