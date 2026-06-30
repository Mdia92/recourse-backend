# Recourse Backend

Python-based intelligent agent backend for the **UiPath Devpost Hackathon**. Recourse integrates with the **UiPath Maestro Case** blueprint and coordinates three specialized agents through a webhook-driven orchestration layer.

## Architecture Overview

```
recourse-backend/
├── config/                 # Environment-aware application configuration
│   ├── settings.py         # Typed settings loaded from .env + YAML
│   └── environments/       # Per-environment overrides (dev, staging, prod)
├── core/                   # Domain logic and specialized agents
│   ├── agents/
│   │   ├── intake/         # Case intake, validation, and normalization
│   │   ├── detective/      # Evidence gathering and investigation
│   │   └── judge/          # Decisioning and case resolution
│   └── models/             # Shared domain models and schemas
├── orchestration/          # UiPath webhook ingress and agent pipeline
│   ├── app.py              # FastAPI application entry point
│   ├── pipeline.py         # Agent execution workflow
│   └── webhooks/           # UiPath Maestro webhook handlers
├── tests/                  # Isolated test suite (unit + integration)
├── .env                    # Local secrets (never commit)
└── pyproject.toml          # Project metadata and dependencies
```

## Agent Responsibilities

| Agent       | Role |
|-------------|------|
| **Intake**  | Receives Maestro Case events, validates payloads, and normalizes case context for downstream agents. |
| **Detective** | Investigates the case by gathering evidence, querying external systems, and building an audit trail. |
| **Judge**   | Evaluates detective findings and produces a structured decision aligned with Maestro Case outcomes. |

## Request Flow

1. UiPath Maestro emits a Case webhook to `orchestration/webhooks/`.
2. The orchestration layer authenticates and routes the event through `pipeline.py`.
3. Agents execute in sequence: **Intake → Detective → Judge**.
4. The orchestration layer returns or posts results back to UiPath.

## Configuration

Environment-specific settings live in `config/environments/`:

- `development.yaml` — local development defaults
- `staging.yaml` — pre-production overrides
- `production.yaml` — production overrides

Secrets and credentials belong in `.env` at the project root. Copy values from your UiPath tenant and LLM provider as needed.

## Getting Started

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -e ".[dev]"

# Run the API server
uvicorn orchestration.app:app --reload
```

## Testing

Tests are isolated under `tests/` and mirror the production package layout:

```bash
pytest
```

## License

Hackathon project — UiPath Devpost Hackathon.
