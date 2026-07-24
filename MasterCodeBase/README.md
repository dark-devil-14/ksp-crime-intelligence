# KSP Crime Intelligence V8

GitHub-ready synthetic crime-intelligence demonstration with:

- leakage-aware next-week count and serious-crime forecasts;
- prospective district PAI calibration;
- dynamic holiday, month, weekday/weekend, and hourly scenario controls;
- land-safe synthetic coastal station coordinates;
- filtered bipartite cyber network with click-to-route station maps;
- concise descriptive fairness diagnostics;
- machine-readable sanity reports.

> This repository uses synthetic data. It is an engineering demonstration, not evidence of real-world policing effectiveness and not a basis for operational enforcement decisions.

## Live deployment

A verified Zoho Catalyst AppSail deployment is available at:

- Dashboard: `https://kspcrimeintelligence-50044296851.development.catalystappsail.in/`
- Health check: `https://kspcrimeintelligence-50044296851.development.catalystappsail.in/api/health`

## Upload directly to GitHub

1. Extract this ZIP.
2. Create a new empty GitHub repository.
3. Upload the **contents** of this folder, not the outer folder itself.
4. Commit the files to the default branch.
5. For GitHub Pages, open **Settings → Pages** and select **GitHub Actions**.

The repository intentionally excludes `.catalystrc`, `catalyst.json`, Docker image archives, local environments, caches, and secrets. Generate the Catalyst files locally with `catalyst init` and `catalyst appsail:add`.

## Quick start

The final verified dashboard and data are already included.

```bash
python -m http.server 8000
```

Open `http://localhost:8000`.

The graph engine is bundled locally. Leaflet and Chart.js load from public CDNs, so an internet connection is needed for the basemap and charts.

## Regenerate everything

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run:

```bash
./run_all.sh
```

Windows:

```bat
run_all.bat
```

The full 80,000-row generator sanity suite can take several minutes.

## Build stages

```bash
python ksp_datagen_v8_final.py \
  --rows 80000 \
  --output data/karnataka_crime_dataset_grounded_v8_80k.csv.gz \
  --stations-output data/ksp_station_registry_v8.csv \
  --report-output reports/datagen_sanity_report_v8.json

python ksp_pipeline_v8_final.py \
  --csv data/karnataka_crime_dataset_grounded_v8_80k.csv.gz \
  --out-dir pipeline_outputs \
  --skip-heatmap

python scripts/build_dashboard_profiles_v8.py \
  --csv data/karnataka_crime_dataset_grounded_v8_80k.csv.gz \
  --dashboard pipeline_outputs/dashboard_data.json \
  --output data/dashboard_data_v8.json

python scripts/build_release_dashboard.py \
  --data data/dashboard_data_v8.json \
  --output index.html

node --check reports/dashboard_inline.js
python scripts/release_sanity.py
```

## Cyber graph controls

The full network JSON retains 119 repeat-accused nodes, 142 station nodes, and 559 links. The page initially shows only the top five accused and links with at least three cases.

- **Top accused** expands or contracts the visible graph.
- **Minimum cases per link** removes weak links.
- **Search** creates a focused subgraph around matching people or stations.
- Clicking an **accused node** isolates its neighbourhood and maps the chronological station-level activity sequence.
- Clicking a **station node** shows linked repeat-accused records.

Route lines are station-level sequences, not exact offence, device, IP, or transaction traces.

## Coordinate safeguard

The V8 generator applies a coarse synthetic west-coast guard to Dakshina Kannada, Udupi, and Uttara Kannada. Twelve generated station centres were moved inland. The final pipeline needed no additional corrections, and all 164 markers pass the release check.

Real deployment data must use authoritative station coordinates and official administrative boundaries.

## Audit interpretation

The audit panel is deliberately descriptive. It reports observed arrest-rate spread in the synthetic records and does not claim a legal disparate-impact result. Population exposure, patrol allocation, and enforcement-opportunity denominators are unavailable.

## Reports

- `reports/final_findings_report.html`
- `reports/final_findings_report.md`
- `reports/release_sanity_v8.json`
- `reports/datagen_sanity_report_v8.json`
- `pipeline_outputs/pipeline_sanity_report.json`

## GitHub Pages

The included workflow publishes the repository root as a static site.

1. Push the repository to GitHub.
2. Open **Settings → Pages**.
3. Select **GitHub Actions** as the source.
4. Run or re-run the **Deploy dashboard to GitHub Pages** workflow.

## Zoho Catalyst AppSail deployment

This distribution also contains a Docker-based Catalyst AppSail service. Read `DEPLOY_TO_ZOHO_CATALYST.md`, test with `docker compose up --build`, then build the Linux AMD64 archive with `build_catalyst_image.sh` or `build_catalyst_image.ps1`.
