@echo off
setlocal
python ksp_datagen_v8_final.py --rows 80000 --output data\karnataka_crime_dataset_grounded_v8_80k.csv.gz --stations-output data\ksp_station_registry_v8.csv --report-output reports\datagen_sanity_report_v8.json || exit /b 1
python ksp_pipeline_v8_final.py --csv data\karnataka_crime_dataset_grounded_v8_80k.csv.gz --out-dir pipeline_outputs --skip-heatmap || exit /b 1
python scripts\build_dashboard_profiles_v8.py --csv data\karnataka_crime_dataset_grounded_v8_80k.csv.gz --dashboard pipeline_outputs\dashboard_data.json --output data\dashboard_data_v8.json || exit /b 1
python scripts\build_release_dashboard.py --data data\dashboard_data_v8.json --output index.html || exit /b 1
python scripts\extract_inline_js.py || exit /b 1
node --check reports\dashboard_inline.js || exit /b 1
python scripts\release_sanity.py || exit /b 1
python scripts\scenario_sanity_v8.py || exit /b 1
echo Build complete. Run: python -m http.server 8000
