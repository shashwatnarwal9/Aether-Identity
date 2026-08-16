# Aether Identity — Real-Time Identity Resolution Engine

Deterministic, auditable identity resolution across mobile / web / edge platforms.
Ingests asynchronous identity signals (face embeddings, device fingerprints,
behavioral telemetry, logins), reconciles them into unified identities with
versioned state, and supports full replay of every decision. Spec: [prd.md](prd.md),
design decisions: [docs/superpowers/specs/2026-08-16-identity-resolution-design.md](docs/superpowers/specs/2026-08-16-identity-resolution-design.md).
Frontend implements the Stitch "Aether Identity" design (4 pages, React UMD, no build step).

## Setup

```bash
pip install -r requirements.txt
```

Python 3.11+ (developed on 3.14). No other services needed — state lives in DuckDB.

## Run

```bash
uvicorn server:app --port 8000
```

Open http://localhost:8000 (pages load React/Tailwind/fonts from CDNs, so the
browser needs internet). State persists in `identity.duckdb` (override with the
`IDRES_DB` env var).

### Pages

| Route | Page |
|---|---|
| `/` | Landing page (Aether Identity) |
| `/dashboard` | Identity Resolution Dashboard — KPIs, interactive identity graph with time scrubber, identity details, signal heatmap |
| `/audit` | Audit History — searchable/filterable decision table, pagination, per-decision trace panel (signals, state diff, SHA-256 seal) |
| `/replay` | Replay Verification — event sequence timeline, run simulation, historical vs. simulated comparison, audit report download |

### API

| Endpoint | Purpose |
|---|---|
| `POST /events` | Ingest one event (JSON). `200` accepted, `409` duplicate, `422` rejected (validation / >7 days late) |
| `GET /api/identities` | All unified identity records |
| `GET /api/identities/{id}` | One identity + its full version history |
| `GET /api/audit` | Decision audit trail (event-enriched) + rejection/duplicate log |
| `GET /api/decision/{seq}` | One decision: input event, previous vs. new merged state, reason, SHA-256 integrity hash |
| `GET /api/events` | Raw accepted event log (replay input) |
| `POST /api/replay` | Re-runs the stored event log through a fresh engine; returns verification + the simulated trail |
| `GET /api/audit/export` | Full audit report as a JSON download |

Example:

```bash
curl -X POST http://localhost:8000/events -H "Content-Type: application/json" -d "{
  \"platform\": \"edge\", \"event_type\": \"face_auth\",
  \"timestamp\": \"2026-08-16T10:00:00Z\", \"user_id\": \"u1\",
  \"device_id\": \"kiosk-1\", \"embedding\": [0.1, 0.2, ...128 floats],
  \"confidence\": 0.97 }"
```

### Replay CLI

```bash
python replay.py fixtures/04_conflict_tiebreak.json            # in-memory, audit -> audit_output/
python replay.py fixtures/*.json --audit-dir audit_output      # all fixtures
python replay.py fixtures/03_biometric_merge.json --db my.duckdb
```

Each run ingests the fixture into a fresh engine, self-verifies by replaying its own
event log, and writes a decision-trace file.

## Test

```bash
python -m pytest tests/ -q
```

Covers: duplicate handling, the 7-day late-event boundary, out-of-order events, all
three tie-breaking strategies plus the deterministic fallback path, replay
determinism/idempotency, midnight transition, and the exact 2-hour temporal boundary.

**Performance:** measured ~165 events/sec single-threaded on an adversarial workload
(1000 events, all with 128-dim embeddings, ~480 candidates per 2-hour window,
constant cluster merges) — above the 100 events/sec requirement. DuckDB is the
durable log; a rebuilt-on-startup in-memory index serves the candidate scans.

## Fixtures and audit outputs

- `fixtures/*.json` — 6 edge-case datasets (duplicates, late events, cross-platform
  biometric merge, multi-cluster conflict tie-break, midnight boundary, behavioral
  linking). Regenerate with `python fixtures/make_fixtures.py`.
- `audit_output/*_audit.json` — committed decision traces produced by the replay CLI:
  per-event ingest results, status counts, the full audit trail, final identities,
  and the replay verification result.

## How resolution works

For each new event, all stored events within **±2 hours** are candidates. A candidate
matches on **biometrics** (cosine distance ≤ 0.15 between 128-dim embeddings),
**device** (same `device_id`), or **behavior** (shared numeric telemetry keys within
25% tolerance). If matches span multiple existing identities, the conflict resolves
by the PRD's priority order — edge-platform biometric match, then mobile device
match, then web behavior match, then lexicographically smallest identity id — and
the event's identity merges with the winner (canonical id = smallest linked
`user_id`). Every accepted event appends a version row: decision timestamp (the
event's own timestamp, for determinism), strategy, human-readable reason, and the
full merged record.

**Determinism/idempotency:** duplicates (same platform+user+type+timestamp) are
no-ops; lateness is measured against the max event timestamp seen (a watermark),
never wall-clock; replaying the log always reproduces the identical audit trail.

## Constraint notes

- **ONNX Runtime** is not a server dependency: embeddings arrive precomputed from the
  platforms (per the PRD scope), so there is no inference step here.
- **Airflow / AWS** are permitted but unnecessary for the MVP — batch replay is a CLI.
- No Kafka/queues, no cloud DBs, no ML in conflict resolution — pure deterministic rules.
