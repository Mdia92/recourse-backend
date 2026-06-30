# Recourse — Intelligent Microinsurance Claims Orchestration

**UiPath Devpost Hackathon Submission**

| | |
|---|---|
| **Project** | Recourse |
| **Repository** | https://github.com/Mdia92/recourse-backend |
| **Stack** | Python, FastAPI, UiPath Maestro Case, UiPath Cloud Orchestrator |
| **Try it out** | Start the server per `DEPLOYMENT.md`, then open `/docs` on your ngrok or local URL |

---

## The Problem

Microinsurance carriers process high volumes of small claims with lean operations teams. When a claimant submits photos, free-text descriptions, and receipt amounts through a digital channel, adjusters must quickly answer three questions:

1. **Is this claim eligible?** (damage type, loss amount, policy coverage)
2. **Is this claim trustworthy?** (duplicate photos, inflated amounts, fraud signals)
3. **What action should we take?** (auto-approve, deny, or escalate to a human)

Manual review does not scale. Fully automated approval without fraud checks creates liability. The gap is an **intelligent orchestration layer** that sits between the UiPath Maestro Case blueprint and human adjusters — classifying claims, detecting fraud, applying policy rules, and routing exceptions to Action Center without breaking the customer experience.

---

## The Solution (Recourse)

**Recourse** is a Python-based intelligent agent backend that plugs into the **UiPath Maestro Case** blueprint. It receives claim payloads via webhook, runs a sequential three-agent pipeline, authenticates against UiPath Cloud, and returns a structured decision — escalating high-risk claims for human review when needed.

### The three agents

| Agent | Role |
|-------|------|
| **Intake Clerk** | Extracts claim text, classifies microinsurance damage type (water, fire, theft, wind), and pulls metadata such as loss amount and location |
| **Detective** | Cross-references evidence URLs and amounts against a mock claim-history database; computes a dynamic fraud risk score (0.0–1.0) |
| **Judge** | Applies microinsurance policy thresholds and returns an explicit **APPROVED** or **DENIED** outcome with a written rationale |

### Policy thresholds (Judge)

- Damage type must be covered (`water`, `fire`, `theft`, `wind`)
- Fraud risk score must be **strictly below 0.3**
- Loss amount must be **strictly under $5,000**

### Human-review escalation

When the Judge returns **DENIED** or fraud risk is **≥ 0.3**, Recourse:

1. Sets `pipeline_status` to `paused_for_human_review`
2. Attempts to create an Action Center task via UiPath Orchestrator `CreateTask`
3. Returns **HTTP 202** with the full pipeline payload so demo and frontend flows remain unbroken even if UiPath task creation is unavailable

### Architecture

```
Maestro Case UI  →  POST /webhook/claims  →  UiPath OAuth
                              ↓
                    Intake → Detective → Judge
                              ↓
              paused_for_human_review (if flagged)
                              ↓
              UiPath Action Center (optional)
```

---

## How We Built It

### Backend framework

- **FastAPI** application (`orchestration/app.py`) with CORS, request logging, and startup validation of `.env` via `load_uipath_config()`
- **Uvicorn** ASGI server on port `8000`
- **Pydantic** schemas for inbound `ClaimPayload` validation

### Configuration layer

- `config/uipath_config.py` — typed UiPath credentials, OAuth2 client-credentials token acquisition
- `configuration/uipath_api.py` — `UiPathOrchestratorClient` for Action Center `CreateTask` with `TaskMetadata` (claim ID, fraud findings, loss summary)
- Environment-driven URL assembly: `{UIPATH_MAESTRO_BASE_URL}/{org}/{tenant}/orchestrator_/tasks/GenericTasks/CreateTask`

### Core agent modules

- `core/intake.py` — `IntakeClerk` with LLM (`gpt-4o-mini`) or heuristic fallback
- `core/detective.py` — `DetectiveAgent` with duplicate photo/receipt detection and fraud scoring
- `core/judge.py` — `JudgeAgent` with explicit APPROVED/DENIED adjudication

### Orchestration

- `orchestration/routes.py` — `POST /webhook/claims`, sequential `execute_claim_pipeline()`, graceful `UiPathOrchestratorError` handling for demo resilience

### Testing

- `tests/test_pipeline.py` — async httpx integration test against the FastAPI app
- Fraud payload with duplicate photos and inflated loss verifies `202`, `paused_for_human_review`, and Judge fraud-threshold rationale

### DevOps

- Public GitHub repository with `.gitignore` protecting `.env`
- `DEPLOYMENT.md` for uvicorn + ngrok setup
- MIT `LICENSE`

---

## Challenges We Overcame

### 1. UiPath OAuth scope alignment

Initial token requests failed with `invalid_scope`. We aligned `UIPATH_DEFAULT_SCOPES` to the external application's granted permissions: `OR.Execution`, `OR.Jobs`, and `OR.Queues`.

### 2. Orchestrator folder context for CreateTask

Action Center task creation required `X-UIPATH-OrganizationUnitId`. We introduced `UIPATH_ORGANIZATION_UNIT_ID` in `.env` and explicit header injection in `configuration/uipath_api.py`, with `X-UIPATH-FolderPath` fallback for shared folders.

### 3. Demo resilience vs. strict error handling

Early implementations returned `502` when UiPath task creation failed (folder access, `Tasks.Create` permissions). For live hackathon evaluation, we wrapped `create_human_validation_task` in a `try/except` that logs a warning and still returns **202** with `pipeline_status: paused_for_human_review` and `uipath_task_created: false` — preserving the full agent pipeline story for judges and frontend demos.

### 4. URL assembly for cloud tenants

We replaced hard-coded domain patching with config-driven URL construction from `UIPATH_MAESTRO_BASE_URL`, `UIPATH_ORGANIZATION_NAME`, and `UIPATH_TENANT_NAME`, with debug logging of the resolved POST URL before each Orchestrator call.

### 5. Windows / PowerShell testing friction

JSON payloads in inline curl commands broke on PowerShell escaping. We standardized on `--data-binary @file.json` and documented PowerShell-friendly examples in `DEPLOYMENT.md`.

---

## Verification Steps for Hackathon Judges

### Step 1 — Clone and install

```bash
git clone https://github.com/Mdia92/recourse-backend.git
cd recourse-backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and add UiPath credentials (or evaluate against mocked integration tests only).

### Step 2 — Run automated tests

```bash
pytest tests/test_pipeline.py -v
```

**Expected:** `test_claim_pipeline_paused_for_human_review_on_fraud_thresholds` **PASSED**

Assertions verified:

- HTTP `202`
- `pipeline_status == "paused_for_human_review"`
- Judge `reason` references fraud risk score and threshold `0.3`

### Step 3 — Start the API server

```bash
uvicorn orchestration.app:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs — confirm Swagger UI loads.

### Step 4 — Health check

```bash
curl http://localhost:8000/health
```

**Expected:** `{"status":"ok","service":"Recourse"}`

### Step 5 — Submit a fraudulent test claim

```powershell
curl.exe -X POST http://localhost:8000/webhook/claims `
  -H "Content-Type: application/json" `
  -d '{"claim_id":"DEMO-001","raw_text":"Urgent water damage $8750 ASAP","photos_urls":["https://storage.example.com/evidence/photo-8821.png","https://storage.example.com/evidence/photo-8821.png"]}'
```

**Expected response (202):**

| Field | Expected value |
|-------|----------------|
| `outcome` | `DENIED` |
| `pipeline_status` | `paused_for_human_review` |
| `reason` | Contains `fraud risk score` and `0.3` |
| `pipeline.detective.context.fraud_risk_score` | `>= 0.3` |
| `pipeline.detective.context.duplicate_photo_matches` | Non-empty array |

### Step 6 — Public demo (optional)

Follow `DEPLOYMENT.md` to start ngrok on port 8000 and open `https://<your-ngrok-host>/docs`.

### Step 7 — Review server logs

Confirm sequential pipeline execution:

```
Claim webhook received — claim_id=DEMO-001
Detective run complete — fraud_risk_score=0.850
Judge decision — outcome=DENIED
UiPath Orchestrator POST → resolved request URL: https://cloud.uipath.com/...
```

---

## What is next

- Wire Maestro Case blueprint webhooks directly to `/webhook/claims`
- Grant `Tasks.Create` and configure Orchestrator folder ID for live Action Center cards
- Replace mock claim-history database with UiPath Data Fabric or external fraud API
- Add claimant-facing status callbacks into Maestro Case

---

**Recourse** — automate the routine, escalate the exceptional, keep humans in control.
