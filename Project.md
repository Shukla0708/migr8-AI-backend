# MIGR8 AI Backend — Validation API

> Living document for the FastAPI service in this package. Update when routes, models, services, or env config change.

---

## Overview

| Field | Value |
| --- | --- |
| Project name | MIGR8 AI — Validation API |
| Path | `migr8-validation-package/backend/` |
| Purpose | Auth + validation runs for the MIGR8 AI frontend (Excel upload, rule config, execute, results, download) |
| Status | Hackathon demo-ready |
| Default port | `8000` |
| OpenAPI | `http://localhost:8000/docs` |

---

## Tech Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Framework | **FastAPI** `0.115` | Uvicorn |
| ORM | **SQLAlchemy** `2.0` | Declarative models in `db/models.py` |
| DB | **PostgreSQL** | Via `psycopg2-binary`; URL from `.env` |
| Auth | **JWT** (`python-jose`) + **bcrypt** (direct; not passlib) | Bearer token |
| Files | **boto3** → S3 (or MinIO) | Source + result workbooks — real AWS keys required for upload |
| Excel | **openpyxl** | Headers, red-fill failures, reason column |
| AI rules | **Groq** `llama-3.3-70b-versatile` | Plain English → regex |
| Config | **pydantic-settings** | Loads `.env` |
| Schemas | **Pydantic v2** | Package under `schemas/` |
| Python | **3.13 tested on Windows** | Needs `psycopg2-binary>=2.9.11`, `httpx==0.27.2` (Groq compat) |

---

## Project Structure

```
backend/
├── main.py                 # FastAPI app, CORS, startup create_all, /health
├── config.py               # Settings from .env
├── auth.py                 # hash/verify password, JWT, get_current_user
├── schema.sql              # Canonical Postgres DDL (preferred over auto-create)
├── requirements.txt
├── .env.example
├── Project.md              # This file
├── db/
│   ├── database.py         # engine, SessionLocal, get_db
│   └── models.py           # User, ValidationProject, ValidationRun, Field, Exception
├── schemas/
│   ├── __init__.py         # Re-exports for `from schemas import ...`
│   ├── auth.py
│   ├── projects.py
│   └── validation.py
├── routers/
│   ├── auth.py             # /api/auth/*
│   ├── projects.py         # /api/projects/*
│   └── validation.py       # /api/runs/*
└── services/
    ├── s3_service.py
    ├── excel_service.py
    ├── rules_engine.py
    └── regex_generator.py
```

---

## Environment

Copy `.env.example` → `.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | e.g. `postgresql://postgres:pass@localhost:5432/migr8` |
| `JWT_SECRET` | yes | Signing key for access tokens |
| `JWT_ALGORITHM` | no | Default `HS256` |
| `JWT_EXPIRE_MINUTES` | no | Default `1440` (24h) |
| `AWS_ACCESS_KEY_ID` | for S3 | Can stay `your-key` — then storage uses local disk |
| `AWS_SECRET_ACCESS_KEY` | for S3 | Same |
| `AWS_REGION` | no | Default `ap-south-1` |
| `S3_BUCKET` | no | Default `migr8-ai-validation` |
| `STORAGE_BACKEND` | no | `auto` (default) \| `local` \| `s3` |
| `PUBLIC_API_BASE_URL` | no | Default `http://localhost:8000` — used for local download URLs |
| `GROQ_API_KEY` | for Rule 5 | Checkbox rules work without it; generate-regex needs Groq |

CORS allows `http://localhost:3000` (frontend).

---

## Data model

```
users 1──* validation_projects 1──* validation_runs
                                      ├──* validation_fields
                                      └──* validation_exceptions
```

| Table | Role |
| --- | --- |
| `users` | Register / login; JWT `sub` = user id |
| `validation_projects` | Scopes “previous runs” list; FK for runs |
| `validation_runs` | One upload → configure → execute cycle + aggregate stats |
| `validation_fields` | Per-column rule flags/config for a run |
| `validation_exceptions` | Capped failure samples (~60) for results UI |

**Run status:** `draft` → `rules_configured` → `running` → `completed` | `failed`

**S3 keys:**

- Source: `validations/{run_id}/source/{filename}`
- Result: `validations/{run_id}/result/{filename}`

Prefer applying `schema.sql` in pgAdmin/`psql`. On startup, `Base.metadata.create_all` also creates missing tables (hackathon shortcut; weaker constraints than SQL).

---

## API map

### Auth — `/api/auth`

| Method | Path | Auth | Body / notes | Response |
| --- | --- | --- | --- | --- |
| POST | `/register` | no | `fullName`, `email`, `password` | `{ token, user }` |
| POST | `/login` | no | `email`, `password` | `{ token, user }` |
| GET | `/me` | Bearer | — | `UserOut` |

### Projects — `/api/projects`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/` | Bearer | `{ name }` → `ProjectOut` |
| GET | `/` | Bearer | List current user’s projects |
| GET | `/{project_id}/runs` | Bearer | Runs list shaped for frontend cards |

### Validation runs — `/api/runs`

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/?project_id=` | Bearer | Create empty run → `{ run_id }` |
| POST | `/{run_id}/upload` | Bearer | Multipart `file`; stores S3; returns `{ fields }` |
| PUT | `/{run_id}/rules` | Bearer | `FieldRuleIn[]` → persists flags/config |
| POST | `/generate-regex` | Bearer | `{ field_name, prompt }` → `{ regex }` |
| POST | `/{run_id}/execute` | Bearer | Sync validation; updates stats + exceptions |
| GET | `/{run_id}/result` | Bearer | Payload for results page |
| GET | `/{run_id}/download-url` | Bearer | `{ url }` presigned GET |

Ownership: every run/project access checks the JWT user owns the project.

---

## Services (behavior)

### `rules_engine.validate_cell`

Per-cell checks driven by field config:

- Mandatory / literal null-N/A
- Data type: int, decimal, boolean, string/char
- Max length, decimal precision
- Case: uppercase / lowercase / camelCase
- Email, mobile, date formats, special chars
- Custom regex
- Key uniqueness (in-run `seen_keys` set)

### `excel_service`

- `extract_headers` — row 1 → column names for the rules table
- `run_validation` — annotate workbook: red fill on failing cells, append `Validation_Failure_Reason`, return stats + up to 60 exceptions

### `regex_generator`

Groq chat completion → JSON `{"regex":"..."}`; pattern compiled before return.

### `s3_service`

`upload_bytes` / `download_bytes` / `presigned_url` against `S3_BUCKET`.

---

## Pydantic schemas (`schemas/`)

| Module | Models |
| --- | --- |
| `auth.py` | `RegisterRequest`, `LoginRequest`, `UserOut`, `AuthResponse` — email is plain `str` with simple `@` / domain checks (not strict `EmailStr`) |
| `projects.py` | `ProjectCreate`, `ProjectOut` — `id` always serialized as `str` (UUID coerced) |
| `validation.py` | `FieldRuleIn`, `RegexGenerateRequest`, `RegexGenerateResponse` |

Routers import via `from schemas import ...` (`schemas/__init__.py` re-exports).

---

## Local run

```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # fill values

# Option A: auto-create tables on startup
uvicorn main:app --reload --port 8000

# Option B: apply schema.sql first, then uvicorn
# psql "$DATABASE_URL" -f schema.sql
```

Smoke checks:

- `GET /health` → `{"status":"ok"}`
- Swagger: `/docs` → register → login → create project → upload

---

## Decisions & Conventions

1. **Bearer JWT in Authorization header** — no cookie session yet.
2. **CamelCase in auth JSON** (`fullName`) to match frontend forms; field rules use snake_case on the wire.
3. **Sync execute** for demo size; large files should move to a queue + poll `status`.
4. **`schema.sql` is source of truth** for production-like constraints; SQLAlchemy models power the app + optional auto-create.
5. **Never log secrets** from `.env`; keep `.env` out of git.
6. Keep routers thin; business logic in `services/`.
7. **Hash passwords with `bcrypt` directly** — avoid passlib + bcrypt 5.x wrap-bug crash on Windows/Python 3.13.
8. **Always `str(uuid)` in API response models** — FastAPI response validation rejects raw `UUID` when the schema field is `str` (see `ProjectOut` / projects router).
9. **Valid AWS (or MinIO) credentials required** for upload/download; placeholder keys → `InvalidAccessKeyId` on `PutObject`.

---

## Open Questions / TBD

- Background job for `execute` (Celery / RQ / FastAPI BackgroundTasks)
- Password reset
- Project switcher UI (backend already supports multiple projects)
- Stricter alignment of auto-created tables with `schema.sql` CHECKs
- Server-side auth (httpOnly cookie) so results can SSR
- Drop unused `passlib` from `requirements.txt` once confirmed unused

---

## Session Log

### 2026-08-12 — Windows / Python 3.13 runtime fixes + ProjectOut UUID

- Bumped `psycopg2-binary` to `2.9.11` (wheels for cp313 Windows).
- Added `email-validator`, pinned `httpx==0.27.2` (Groq 0.11 incompatible with httpx 0.28 `proxies` kwarg).
- Replaced passlib hashing with direct `bcrypt` (`auth.py`); pin `bcrypt==4.0.1`.
- Relaxed register/login email validation (no strict `EmailStr`).
- Fixed `GET/POST /api/projects/` 500: coerce project `id` UUID → `str` in router/`ProjectOut`.
- Confirmed upload fails with `InvalidAccessKeyId` until real `AWS_*` / bucket are set in `.env`.

### 2026-08-12 — Schemas package

- Split flat `schemas.py` into `schemas/{auth,projects,validation}.py` + `__init__.py` re-exports.
- Router imports unchanged: `from schemas import ...`.

### 2026-08-12 — Project.md added

- Documented stack, structure, env, data model, API map, services, run instructions.

---

## Change Checklist

- [ ] New dependency
- [ ] New route or response shape (also update `frontend-updates/Project.md` / frontend `Project.md`)
- [ ] Model / `schema.sql` change
- [ ] New env var / `.env.example`
- [ ] Service behavior change (rules, Excel, S3, Groq)
