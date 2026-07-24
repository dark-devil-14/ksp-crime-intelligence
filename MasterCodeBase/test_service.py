#!/usr/bin/env python3
"""Static and API sanity checks for the Catalyst service package."""
from __future__ import annotations
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
checks = {}

for rel in [
    "server.py",
    "Dockerfile",
    "index.html",
    "ksp_pipeline_v8_final.py",
    "ksp_datagen_v8_final.py",
    "data/dashboard_data_v8.json",
    "data/karnataka_crime_dataset_grounded_v8_80k.csv.gz",
    "assets/cytoscape.min.js",
]:
    checks[f"present:{rel}"] = (ROOT / rel).is_file()

for rel in ["server.py", "ksp_pipeline_v8_final.py", "ksp_datagen_v8_final.py"]:
    try:
        py_compile.compile(str(ROOT / rel), doraise=True)
        checks[f"python_syntax:{rel}"] = True
    except Exception:
        checks[f"python_syntax:{rel}"] = False

try:
    dashboard = json.loads((ROOT / "data/dashboard_data_v8.json").read_text(encoding="utf-8"))
    checks["dashboard_json"] = isinstance(dashboard, dict)
    checks["dashboard_has_zones"] = len(dashboard.get("zones", [])) > 0
    checks["dashboard_has_network"] = bool(dashboard.get("cyber_network"))
except Exception:
    checks["dashboard_json"] = False

html = (ROOT / "index.html").read_text(encoding="utf-8", errors="replace")
checks["cytoscape_loader_fallback"] = "cdn.jsdelivr.net/npm/cytoscape" in html and "assets/cytoscape.min.js" in html
checks["embedded_dashboard"] = 'id="embedded-data"' in html
checks["all_passed"] = all(checks.values())

output = ROOT / "reports" / "catalyst_package_sanity.json"
output.write_text(json.dumps(checks, indent=2), encoding="utf-8")
print(json.dumps(checks, indent=2))
raise SystemExit(0 if checks["all_passed"] else 1)
