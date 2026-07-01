# Recourse Backend — Deployment Guide

Step-by-step instructions to run the Recourse API locally and expose it publicly for UiPath Maestro Case webhooks and hackathon demos.

## Prerequisites

- Python 3.11+
- [ngrok](https://ngrok.com/) installed and authenticated (`ngrok config add-authtoken <token>`)
- UiPath Cloud external application credentials (client ID + secret)
- A copy of `.env` populated from `.env.example`

## 1. Clone and configure

```bash
git clone https://github.com/Mdia92/recourse-backend.git
cd recourse-backend
```

Copy the environment template and fill in your UiPath tenant values:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

Required variables:

| Variable | Description |
|----------|-------------|
| `UIPATH_CLIENT_ID` | External application client ID |
| `UIPATH_CLIENT_SECRET` | External application client secret |
| `UIPATH_ORGANIZATION_NAME` | Cloud organization slug |
| `UIPATH_TENANT_NAME` | Cloud tenant slug |
| `UIPATH_MAESTRO_BASE_URL` | `https://cloud.uipath.com` |
| `UIPATH_ORGANIZATION_UNIT_ID` | Orchestrator folder ID (optional for Action Center tasks) |
| `OPENAI_API_KEY` | Optional — enables LLM-powered intake classification |

## 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```powershell
# Windows PowerShell
.venv\Scripts\activate
```

```bash
# macOS / Linux
source .venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -e ".[dev]"
```

## 4. Start the backend server (uvicorn)

From the project root with the virtual environment active:

```bash
uvicorn orchestration.app:app --reload --host 0.0.0.0 --port 8000
```

Expected startup logs:

```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
Recourse backend is ready to accept requests
```

Verify locally:

| Endpoint | URL |
|----------|-----|
| Health | http://localhost:8000/health |
| Swagger UI | http://localhost:8000/docs |
| Claims webhook | `POST http://localhost:8000/webhook/claims` |

Keep this terminal open while demoing.

## 5. Open a public ngrok tunnel (port 8000)

In a **second terminal** (leave uvicorn running in the first):

```bash
ngrok http 8000
```

ngrok prints a public HTTPS URL, for example:

```
Forwarding   https://xxxx.ngrok-free.app -> http://localhost:8000
```

Use these public URLs for Maestro / Devpost:

| Resource | Public URL |
|----------|------------|
| API docs | `https://xxxx.ngrok-free.app/docs` |
| Health | `https://xxxx.ngrok-free.app/health` |
| Claims webhook | `POST https://xxxx.ngrok-free.app/webhook/claims` |

> **Note:** Free ngrok URLs change each time you restart ngrok unless you use a reserved domain.

## 6. Send a test fraud claim (PowerShell)

```powershell
curl.exe -X POST http://localhost:8000/webhook/claims `
  -H "Content-Type: application/json" `
  -d '{"claim_id":"DEMO-001","raw_text":"Urgent water damage $8750 ASAP","photos_urls":["https://storage.example.com/evidence/photo-8821.png","https://storage.example.com/evidence/photo-8821.png"]}'
```

Expected response (`202 Accepted`):

```json
{
  "pipeline_status": "paused_for_human_review",
  "outcome": "DENIED",
  "uipath_task_created": false
}
```

## 7. Run the test suite

```bash
pytest tests/ -v
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `invalid_scope` on startup | Add `OR.Execution`, `OR.Jobs`, `OR.Queues` scopes to your UiPath external app |
| `502` before pipeline completes | Check `.env` credentials and cloud tenant names |
| `folder is required` / `403` on Action Center | Set `UIPATH_ORGANIZATION_UNIT_ID` to your Orchestrator folder ID; demo mode continues with `uipath_task_created: false` |
| ngrok shows 404 | Confirm uvicorn is running on port 8000 before starting ngrok |

## Production checklist

- [ ] Never commit `.env` (already in `.gitignore`)
- [ ] Use HTTPS only (ngrok or cloud host)
- [ ] Rotate UiPath client secrets after the hackathon
- [ ] Add `Tasks.Create` scope and folder ID for live Action Center task creation
