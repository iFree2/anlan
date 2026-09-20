"""Install the pinned official Jaeger Windows archive into this project only."""

import hashlib
import io
import json
import os
import platform
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "2.21.0"
ARCHIVE_NAME = f"jaeger-{VERSION}-windows-amd64.zip"
SOURCE = f"https://github.com/jaegertracing/jaeger/releases/download/v{VERSION}/{ARCHIVE_NAME}"
SHA256 = "197c4b42aba6983b3d9cbca3577a0e14191bcb9431fde1b6661471b6fece39fc"
ARCHIVE_SIZE = 64683817
PREFIX = f"jaeger-{VERSION}-windows-amd64/"
MEMBERS = {PREFIX: 0, PREFIX + "jaeger.exe": 111233024,
           PREFIX + "example-hotrod.exe": 28900864}


class SetupError(Exception):
    """A safe, actionable local installation failure."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    """Reject redirected directories/files and multiply linked output files."""
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise SetupError("Runtime path contains a symbolic link or junction.")
    if path.exists() and path.is_file() and path.stat().st_nlink != 1:
        raise SetupError("Runtime file has multiple hard links.")


def verify_archive(data):
    if len(data) != ARCHIVE_SIZE or digest(data) != SHA256:
        raise SetupError(
            "Archive does not match the pinned size and SHA256; refusing installation."
        )


def archive_members(archive):
    members = archive.infolist()
    names = [member.filename for member in members]
    if len(names) != len(set(names)) or set(names) != set(MEMBERS):
        raise SetupError("Archive contains missing, duplicate or unexpected members.")
    for member in members:
        mode = member.external_attr >> 16
        expected_type = stat.S_IFDIR if member.filename == PREFIX else stat.S_IFREG
        if stat.S_IFMT(mode) != expected_type or member.file_size != MEMBERS[member.filename]:
            raise SetupError("Archive member type or size differs from the allowlist.")
    return members


def write_verified(path, data):
    safe_path(path)
    if path.exists():
        if not path.is_file() or digest(path.read_bytes()) != digest(data):
            raise SetupError("Existing runtime file conflicts with the pinned installation.")
        return
    with path.open("xb") as output:
        output.write(data)


def install():
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SetupError("This installer requires Windows amd64.")
    project = Path(__file__).absolute().parent.parent
    runtime = project / ".runtime" / "jaeger"
    safe_path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    archive_path = runtime / ARCHIVE_NAME
    safe_path(archive_path)
    if archive_path.exists():
        data = archive_path.read_bytes()
    else:
        with urllib.request.urlopen(SOURCE, timeout=60) as response:
            data = response.read(ARCHIVE_SIZE + 1)
        verify_archive(data)
        write_verified(archive_path, data)
    verify_archive(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive_members(archive)
        # Map the one executable explicitly; never extract archive-controlled paths.
        executable = archive.read(PREFIX + "jaeger.exe")
    exe_path = runtime / "jaeger.exe"
    write_verified(exe_path, executable)
    manifest = {
        "version": VERSION, "source": SOURCE, "archive_size": ARCHIVE_SIZE,
        "archive_sha256": SHA256, "executable_sha256": digest(executable),
        "executable": ".runtime/jaeger/jaeger.exe",
        "installed_members": [PREFIX + "jaeger.exe"],
    }
    encoded = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    write_verified(runtime / "install.json", encoded)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    try:
        install()
    except (SetupError, OSError, zipfile.BadZipFile) as error:
        print(f"Jaeger setup failed: {error}", file=sys.stderr)
        sys.exit(1)
