#!/usr/bin/env python3
"""Create a reproducible source-only tarball; never include weights or credentials."""

import gzip
import hashlib
import io
import tarfile
from pathlib import Path


def main() -> None:
    package = Path(__file__).resolve().parents[1]
    output_dir = package.parent / "dist"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / "w4a8-modelarts-standard-20260929.tar.gz"
    files = sorted(
        path for path in package.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc")
    )
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for path in files:
                    payload = path.read_bytes()
                    entry = tarfile.TarInfo(f"w4a8/{path.relative_to(package).as_posix()}")
                    entry.size = len(payload)
                    entry.mtime = 0
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ""
                    entry.mode = 0o755 if path.suffix == ".sh" else 0o644
                    archive.addfile(entry, io.BytesIO(payload))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"{digest}  {output.name}")


if __name__ == "__main__":
    main()
