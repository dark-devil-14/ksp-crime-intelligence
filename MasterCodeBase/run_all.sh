#!/usr/bin/env bash
set -euo pipefail
python ksp_datagen_v8_final.py --rows 80000 --output data/karnataka_crime_dataset_grounded_v8_80k.csv.gz --stations-output data/ksp_station_registry_v8.csv --report-output reports/datagen_sanity_report_v8.json
python ksp_pipeline_v8_final.py --csv data/karnataka_crime_dataset_grounded_v8_80k.csv.gz --out-dir pipeline_outputs --skip-heatmap
python scripts/build_dashboard_profiles_v8.py --csv data/karnataka_crime_dataset_grounded_v8_80k.csv.gz --dashboard pipeline_outputs/dashboard_data.json --output data/dashboard_data_v8.json
python scripts/build_release_dashboard.py --data data/dashboard_data_v8.json --output index.html
python scripts/extract_inline_js.py
node --check reports/dashboard_inline.js
python scripts/release_sanity.py
python scripts/scenario_sanity_v8.py
printf '\nBuild complete. Run: python -m http.server 8000\n'
