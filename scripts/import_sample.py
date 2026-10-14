#!/usr/bin/env python3
"""Import the shipped measured sample into local history. No network scans."""
import json
import shutil
from pathlib import Path

from app.core.config import Settings, ROOT
from app.core.store import Store

settings = Settings()
settings.prepare()
report = json.loads((ROOT/"samples"/"juice-shop-report.json").read_text())
directory = settings.data_dir/"jobs"/report["id"]
directory.mkdir(parents=True,exist_ok=True)
for file in (ROOT/"samples"/"evidence").glob("*"):
    if file.is_file():
        shutil.copy2(file,directory/file.name)
Store(settings.db_path).import_report(report)
print("Imported measured sample",report["id"])
