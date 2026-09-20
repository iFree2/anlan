"""Install a pinned, unofficial pgvector build into the project-only Windows PG17."""

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import psycopg
from psycopg.conninfo import conninfo_to_dict

SOURCE = (
    "https://github.com/andreiramani/pgvector_pgsql_windows/releases/"
    "download/0.8.6_17/vector.v0.8.6-pg17.zip"
)
RELEASE = "https://github.com/andreiramani/pgvector_pgsql_windows/releases/tag/0.8.6_17"
SHA256 = "420388e9e9f05d92f06d6967ce8772483629b27a66ca9255925fa0fdd445438e"
ARCHIVE_SIZE = 169689
VERSION = "0.8.6"
COSINE_SQL = """SELECT label, embedding OPERATOR(public.<=>) '[1,0,0]'::public.vector
    AS cosine_distance
FROM (VALUES ('same', '[1,0,0]'::public.vector),
             ('orthogonal', '[0,1,0]'::public.vector),
             ('opposite', '[-1,0,0]'::public.vector)) AS samples(label, embedding)
ORDER BY cosine_distance, label"""


class SetupError(Exception):
    """A classified failure with a non-sensitive, fixed message."""

    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def require(condition, category, message):
    if not condition:
        raise SetupError(category, message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def runtime_root():
    require(os.name == "nt", "unsupported_platform", "This helper requires Windows x64.")
    require("LOCALAPPDATA" in os.environ, "unsafe_target", "LOCALAPPDATA is unavailable.")
    expected = (Path(os.environ["LOCALAPPDATA"]) / "Anlan2Runtime/postgres-17.11/pgsql").absolute()
    # MSIX may virtualize LOCALAPPDATA into the Codex LocalCache without a junction.
    # Resolve this one fixed root and reject actual links in its project-owned ancestors.
    for directory in (expected, expected.parent, expected.parent.parent):
        require(
            not directory.is_symlink() and not directory.is_junction(),
            "unsafe_target",
            "Project runtime uses a symbolic link or junction.",
        )
    require(
        (expected / "bin/postgres.exe").is_file(),
        "runtime_missing",
        "Install the project PostgreSQL 17.11 runtime first.",
    )
    return expected.resolve()


def archive_payload(project, report):
    archive = project / ".runtime/pgvector/vector.v0.8.6-pg17.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        with urllib.request.urlopen(SOURCE, timeout=45) as response:
            data = response.read(ARCHIVE_SIZE + 1)
        require(
            len(data) == ARCHIVE_SIZE and sha256(data) == SHA256,
            "archive_integrity",
            "Downloaded archive failed pinned size/SHA256 verification.",
        )
        with archive.open("xb") as output:
            output.write(data)
    data = archive.read_bytes()
    require(
        len(data) == ARCHIVE_SIZE and sha256(data) == SHA256,
        "archive_integrity",
        "Cached archive failed pinned size/SHA256 verification.",
    )
    report["archive_verified"] = True
    payload = {}
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        names = [item.filename for item in members]
        require(len(names) == len(set(names)), "unsafe_archive", "Duplicate ZIP members.")
        report["archive_members"] = names
        for item in members:
            path = PurePosixPath(item.filename)
            require(
                not path.is_absolute()
                and ".." not in path.parts
                and "\\" not in item.filename
                and ":" not in item.filename,
                "unsafe_archive",
                "Unsafe ZIP member path.",
            )
            require(
                (item.external_attr >> 16) & 0o170000 != 0o120000,
                "unsafe_archive",
                "ZIP symlinks are not supported.",
            )
            name = item.filename
            selected = name in {"lib/vector.dll", "share/extension/vector.control"} or bool(
                re.fullmatch(r"share/extension/vector(?:--[0-9.]+(?:--[0-9.]+)?)?\.sql", name)
            )
            if selected and not item.is_dir():
                payload[name] = zipped.read(item)
        readme = zipped.read("readme.txt").decode("utf-8")
        report["archive_readme"] = readme
        report["readme_review"] = (
            "Targets PostgreSQL 17 Windows x64. Broad extraction, overwrite and service restart "
            "instructions are deliberately not used; only allowlisted extension files are copied "
            "to the dedicated project runtime without overwriting different content."
        )
    require(
        {"lib/vector.dll", "share/extension/vector.control", "share/extension/vector--0.8.6.sql"}
        <= payload.keys(),
        "archive_layout",
        "Required extension files are absent.",
    )
    control = payload["share/extension/vector.control"].decode("utf-8")
    require(
        "default_version = '0.8.6'" in control and "module_pathname = '$libdir/vector'" in control,
        "archive_version",
        "Unexpected extension control version or library.",
    )
    dll = payload["lib/vector.dll"]
    pe_offset = struct.unpack_from("<I", dll, 0x3C)[0]
    require(
        dll[:2] == b"MZ"
        and dll[pe_offset : pe_offset + 4] == b"PE\0\0"
        and struct.unpack_from("<H", dll, pe_offset + 4)[0] == 0x8664,
        "binary_architecture",
        "Extension DLL is not a Windows x64 PE binary.",
    )
    report["binary_architecture"] = "PE AMD64"
    return payload


def project_connection(project, root):
    dsn = os.environ.get("ANLAN_DATABASE_URL")
    require(bool(dsn), "connection_missing", "Run dev-postgres.ps1 -Action Env first.")
    info = conninfo_to_dict(dsn)
    config = json.loads((project / ".runtime/postgres-dev/connection.json").read_text("utf-8-sig"))
    require(
        info.get("host") == "127.0.0.1"
        and info.get("dbname") == "anlan_dev"
        and info.get("user") == "anlan_dev"
        and info.get("port") == str(config["port"])
        and not info.get("service")
        and not info.get("hostaddr"),
        "database_target",
        "Connection must target the dedicated project development database.",
    )
    conn = psycopg.connect(dsn, connect_timeout=10)
    try:
        version, data_dir, database, user, address, port = conn.execute(
            "SELECT current_setting('server_version_num'), current_setting('data_directory'), "
            "current_database(), current_user, host(inet_server_addr()), inet_server_port()"
        ).fetchone()
        require(version == "170011", "postgres_version", "Expected PostgreSQL 17.11 server.")
        require(
            Path(data_dir).resolve() == (root.parent / "anlan2-data").resolve()
            and database == "anlan_dev"
            and user == "anlan_dev"
            and address == "127.0.0.1"
            and port == config["port"],
            "database_target",
            "Server identity does not match the project development cluster.",
        )
        existing = conn.execute(
            "SELECT e.extversion, n.nspname FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'"
        ).fetchone()
        require(
            existing is None or existing == (VERSION, "public"),
            "extension_conflict",
            "Existing vector extension has another version or schema; no automatic upgrade.",
        )
    except Exception:
        conn.close()
        raise
    return conn


def install_files(root, payload, report):
    plan = []
    # Preflight the entire plan before the first write; no extractall or path supplied by callers.
    for name, data in sorted(payload.items()):
        candidate = root / name
        target = candidate.resolve()
        require(target.is_relative_to(root), "unsafe_target", "Target escapes project runtime.")
        require(
            target == candidate and not candidate.is_symlink(),
            "unsafe_target",
            "Extension target uses a symbolic link or junction.",
        )
        require(target.parent.is_dir(), "runtime_layout", "Expected runtime directory is absent.")
        exists = target.exists()
        require(
            not exists or (target.is_file() and sha256(target.read_bytes()) == sha256(data)),
            "file_conflict",
            "An extension target already contains different data; not overwritten.",
        )
        plan.append((name, target, data, exists))
    report["installed_files"] = []
    for name, target, data, exists in plan:
        if not exists:
            with target.open("xb") as output:
                output.write(data)
        require(
            sha256(target.read_bytes()) == sha256(data),
            "installed_integrity",
            "Installed file failed SHA256 verification.",
        )
        report["installed_files"].append(
            {
                "path": name,
                "sha256": sha256(data),
                "action": "verified_existing" if exists else "installed",
            }
        )


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=project / ("docs/phases/phase-02-tools-rag/evidence/wp03/pgvector-setup.json"),
    )
    args = parser.parse_args()
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "failed",
        "source": {
            "release": RELEASE,
            "download": SOURCE,
            "official": False,
            "description": "Community Windows build, not an official pgvector binary",
            "sha256": SHA256,
            "size_bytes": ARCHIVE_SIZE,
        },
        "expected_extension_version": VERSION,
        "data_origin": "SYNTHETIC",
        "scope": "Project user PostgreSQL 17.11 only; no service changes or model calls",
    }
    stage = "runtime_preflight"
    try:
        root = runtime_root()
        report["runtime"] = "%LOCALAPPDATA%/Anlan2Runtime/postgres-17.11/pgsql"
        stage = "archive_verification"
        payload = archive_payload(project, report)
        stage = "database_preflight"
        with project_connection(project, root) as conn:
            stage = "file_installation"
            install_files(root, payload, report)
            stage = "extension_creation"
            create_sql = "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"
            conn.execute(create_sql)
            version = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).fetchone()[0]
            require(
                version == VERSION, "extension_version", "Unexpected installed extension version."
            )
            stage = "cosine_verification"
            rows = conn.execute(COSINE_SQL).fetchall()
            require(
                rows == [("same", 0.0), ("orthogonal", 1.0), ("opposite", 2.0)],
                "cosine_result",
                "Cosine ordering or distances differ from expected values.",
            )
            report["database_verification"] = {
                "server_version": "17.11",
                "database": "anlan_dev",
                "schema": "public",
                "extversion": version,
                "create_sql": create_sql,
                "cosine_sql": COSINE_SQL,
                "cosine_results": [
                    {"label": label, "cosine_distance": distance} for label, distance in rows
                ],
            }
        report["status"] = "passed"
    except Exception as error:
        # Never serialize connection strings, credentials or raw driver exception messages.
        report["failure"] = {
            "stage": stage,
            "category": getattr(error, "category", stage),
            "exception_type": type(error).__name__,
        }
        if isinstance(error, SetupError):
            report["failure"]["message"] = str(error)
        if isinstance(error, psycopg.Error):
            report["failure"]["sqlstate"] = error.sqlstate
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output),
                "failure": report.get("failure"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
