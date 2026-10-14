#!/usr/bin/env python3
"""Install a pinned upstream Nuclei release, verifying the published SHA-256."""
import hashlib
import io
import os
import platform
import sys
import zipfile
from pathlib import Path

import httpx

VERSION = "3.4.10"
architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
if not architecture or platform.system() != "Linux":
    raise SystemExit("Use the official Nuclei installation instructions on non-Linux hosts.")
name = f"nuclei_{VERSION}_linux_{architecture}.zip"
base = f"https://github.com/projectdiscovery/nuclei/releases/download/v{VERSION}/"
with httpx.Client(follow_redirects=True, timeout=120) as client:
    archive = client.get(base + name)
    archive.raise_for_status()
    checks = client.get(base + f"nuclei_{VERSION}_checksums.txt")
    checks.raise_for_status()
expected = next(line.split()[0] for line in checks.text.splitlines() if line.split()[-1] == name)
if hashlib.sha256(archive.content).hexdigest() != expected:
    raise SystemExit("Nuclei release checksum mismatch — refusing installation.")
destination = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/local/bin/nuclei")
destination.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
    destination.write_bytes(bundle.read("nuclei"))
destination.chmod(0o755)
print(f"Installed verified Nuclei {VERSION} at {destination}")
