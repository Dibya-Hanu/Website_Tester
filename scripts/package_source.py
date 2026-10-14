#!/usr/bin/env python3
"""Package the source, notices, documentation and real sample; never local secrets/data."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git", ".venv", "node_modules", "dist", "build", "data", ".cache", ".pytest_cache",
    "__pycache__", ".mypy_cache", ".ruff_cache", "coverage", ".vite", ".arena",
}
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=ROOT.parent / "AI-Universal-Website-Tester.zip")
args = parser.parse_args()
files = [path for path in ROOT.rglob("*") if path.is_file()
         and not set(path.relative_to(ROOT).parts).intersection(EXCLUDED)
         and path.name not in {".env", ".DS_Store", "tsconfig.tsbuildinfo"}
         and not path.suffix in {".pyc", ".pyo", ".tsbuildinfo"}
         and path.resolve() != args.output.resolve()]
args.output.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(args.output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(files):
        archive.write(path, arcname=Path(ROOT.name) / path.relative_to(ROOT))
with ZipFile(args.output) as archive:
    assert archive.testzip() is None, "ZIP integrity check failed"
    for required in ["LICENSE", "README.md", "ARCHITECTURE.md", "TESTING.md", "docker-compose.yml",
                     "Dockerfile", "Dockerfile.ollama-cpu", "frontend/package-lock.json",
                     "samples/juice-shop-report.html", "samples/juice-shop-report.pdf",
                     "samples/juice-shop-report.json", "samples/execution-manifest.json"]:
        assert f"{ROOT.name}/{required}" in archive.namelist(), f"Missing {required}"
print(f"Packaged {len(files)} files: {args.output} ({args.output.stat().st_size/1024**2:.2f} MiB)")
