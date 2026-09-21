#!/usr/bin/env python3
"""Fail publication if private-environment values or likely secrets are present."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TEXT_SUFFIXES = {".md", ".json", ".py", ".sh", ".env", ".example", ".gitignore"}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Huawei access key": re.compile(r"\b[A-Z0-9]{20}\b"),
    "bearer token": re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+(?!<|\$\{|change_me)[A-Za-z0-9._-]{16,}"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    failures: list[str] = []
    for path in args.root.rglob("*"):
        if path.name == Path(__file__).name:
            continue
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{path.relative_to(args.root)}: possible {name}")
    if failures:
        raise SystemExit("\n".join(failures))
    print("repository secret scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
