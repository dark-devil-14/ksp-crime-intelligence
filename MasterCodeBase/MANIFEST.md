# Release manifest

## Run immediately

- `index.html` - final dashboard
- `data/dashboard_data_v8.json` - enriched verified dashboard data
- `reports/final_findings_report.html` - complete findings report

## Reproduce

- `ksp_datagen_v8_final.py`
- `ksp_pipeline_v8_final.py`
- `scripts/build_dashboard_profiles_v8.py`
- `scripts/build_release_dashboard.py`
- `scripts/release_sanity.py`
- `scripts/scenario_sanity_v8.py`

## Verified inputs and outputs

- `data/karnataka_crime_dataset_grounded_v8_80k.csv.gz`
- `data/ksp_station_registry_v8.csv`
- `pipeline_outputs/*.json`
- `reports/datagen_sanity_report_v8.json`
- `reports/release_sanity_v8.json`
- `reports/scenario_sanity_v8.json`

## Deployment

- `.github/workflows/pages.yml`
- `README.md`
- `requirements.txt`
- `run_all.sh`
- `run_all.bat`
