"""把锁定版本的 EDB 便携二进制安装到用户目录下的专用 ASCII 路径。"""

import hashlib
import os
import urllib.request
import zipfile
from pathlib import Path

SOURCE = "https://get.enterprisedb.com/postgresql/postgresql-17.11-4-windows-x64-binaries.zip"
SHA256 = "b9424ee7bc60b52450ff910a3630225df32e633f3cb29c1d126d9299d59aea28"


def main():
    if os.name != "nt":
        raise SystemExit("Windows helper only; use an isolated PostgreSQL on other OSes.")
    project = Path(__file__).resolve().parents[1]
    archive = project / ".runtime/postgres-tools/postgresql-17.11-windows.zip"
    runtime = Path(os.environ["LOCALAPPDATA"]) / "Anlan2Runtime/postgres-17.11"
    if not str(runtime).isascii():
        raise SystemExit("A non-ASCII user profile needs a custom ASCII PostgreSQL installation.")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print("Downloading pinned PostgreSQL archive (~380 MB).", flush=True)
        with urllib.request.urlopen(SOURCE, timeout=45) as response, archive.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != SHA256:
        raise SystemExit("Archive checksum mismatch; no extraction. Inspect local download.")
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            if not item.filename.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
                continue
            target = (runtime / item.filename).resolve()
            if not target.is_relative_to(runtime.resolve()):
                raise SystemExit("Unsafe archive path; extraction stopped.")
            if not target.exists():
                zipped.extract(item, runtime)
    print(f"PostgreSQL binaries ready: {runtime / 'pgsql/bin'}")


if __name__ == "__main__":
    main()
