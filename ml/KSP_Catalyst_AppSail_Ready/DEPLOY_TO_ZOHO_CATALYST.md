# Deploy KSP Crime Intelligence V8 to Zoho Catalyst AppSail

## Recommended hackathon architecture

Use one AppSail custom-runtime service. It serves the dashboard and the verified outputs immediately, exposes read-only API endpoints, and contains the complete generator and forecasting pipeline. The model refresh endpoint is disabled by default and can be enabled with AppSail environment variables.

## 1. Prerequisites

Install:

- Docker Desktop
- Node.js and npm
- Zoho Catalyst CLI: `npm install -g zcatalyst-cli`

Create a Catalyst project from the Catalyst console.

## 2. Test locally

From this folder:

```bash
docker compose up --build
```

Open:

- Dashboard: `http://localhost:9000/`
- Health: `http://localhost:9000/api/health`
- Dashboard JSON: `http://localhost:9000/api/dashboard`
- Output inventory: `http://localhost:9000/api/outputs`

## 3. Build the Linux AMD64 Docker archive

macOS/Linux:

```bash
./build_catalyst_image.sh
```

Windows PowerShell:

```powershell
./build_catalyst_image.ps1
```

This creates `ksp-crime-intelligence-v8-amd64.tar`.

## 4. Associate the local folder with Catalyst

```bash
catalyst login
catalyst init
```

Choose your organization and the Catalyst project created in the console. You can initialize without selecting another resource, then add AppSail:

```bash
catalyst appsail:add
```

Choose:

1. Docker Image
2. Docker Archive
3. The absolute path to `ksp-crime-intelligence-v8-amd64.tar`
4. Service name: `KSPCrimeIntelligenceV8`

The CLI writes the project-specific `catalyst.json` and `.catalystrc` files. Do not copy these files from another Catalyst project.

## 5. Deploy to the development environment

```bash
catalyst deploy --only appsail
```

The CLI prints the AppSail development endpoint. Check `/api/health` first, then open `/`.

## 6. AppSail settings

In the Catalyst console open AppSail -> KSPCrimeIntelligenceV8 -> Configuration.

Recommended starting values:

- Port: `9000`
- Memory: start at 2 GB for pipeline reruns; the read-only dashboard can use less
- Disk: allocate enough for the image, temporary model outputs, and refresh workspace
- Startup command: inherited from the Docker image (`python -u server.py`)

Environment variables:

| Key | Development value | Purpose |
|---|---|---|
| `ENABLE_PIPELINE_RUN` | `0` | Keeps cloud reruns disabled initially |
| `ADMIN_TOKEN` | a long random secret | Protects the pipeline refresh endpoint |
| `X_ZOHO_CATALYST_LISTEN_PORT` | `9000` | Usually provided by AppSail; the service also defaults to 9000 |

## 7. Optional model refresh

After the service is stable, set:

- `ENABLE_PIPELINE_RUN=1`
- `ADMIN_TOKEN=<strong random value>`

Trigger a refresh:

```bash
curl -X POST \
  -H "X-Admin-Token: YOUR_SECRET" \
  https://YOUR_APPSAIL_URL/api/pipeline/run
```

Track it:

```bash
curl https://YOUR_APPSAIL_URL/api/pipeline/status
```

Read the protected log:

```bash
curl -H "X-Admin-Token: YOUR_SECRET" \
  "https://YOUR_APPSAIL_URL/api/pipeline/log?lines=300"
```

The bundled, verified outputs are available immediately even when refresh is disabled.

## 8. Optional scheduled refresh

For a scheduled demonstration, configure Catalyst Job Scheduling/Cron to invoke the AppSail refresh endpoint. For durable operational refreshes, modify the service to publish generated output JSON files to Catalyst File Store rather than treating instance-local files as the permanent source of truth.

## 9. Production

CLI deployment updates the Catalyst development environment. Test the development URL, inspect AppSail logs, and then use the Catalyst console's Deploy to Production flow. Catalyst requires its production setup/payment step before the first production deployment.

## API surface

| Method | Route | Access |
|---|---|---|
| GET | `/` | Public dashboard |
| GET | `/api/health` | Public health and version |
| GET | `/api/dashboard` | Public enriched output JSON |
| GET | `/api/outputs` | Public list of pipeline JSON outputs |
| GET | `/api/pipeline/status` | Public refresh state |
| POST | `/api/pipeline/run` | Disabled by default; admin token required |
| GET | `/api/pipeline/log` | Admin token required |

## Security notes

- Never commit `ADMIN_TOKEN` to GitHub.
- Keep pipeline refresh disabled during judging unless a live rerun is required.
- The included data is synthetic and must remain labelled as such.
- For real data, use authentication, authorized station coordinates, audit logging, data retention controls, and role-based access.
