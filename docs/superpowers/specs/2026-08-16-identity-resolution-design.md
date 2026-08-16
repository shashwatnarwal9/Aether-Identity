# Identity Resolution Engine — Design

Date: 2026-08-16. Source spec: `prd.md` (authoritative). This doc records only the
decisions the PRD leaves open, plus the file layout.

## Decisions the PRD leaves open

1. **Lateness reference point** — "accept events up to 7 days old" is measured against
   the **maximum event timestamp seen so far** (a watermark), not wall-clock time.
   Wall-clock would break the determinism requirement (same input → same output).
2. **Decision timestamp** — the triggering event's timestamp, not `now()`. Same reason.
3. **Canonical identity id** — when user_ids are linked into one identity, the canonical
   id is the lexicographically smallest member user_id. Deterministic, stable under replay.
4. **Conflict semantics** — if a new event matches **multiple distinct** existing
   identities, that is a conflict: exactly one target is chosen by the PRD's tie-break
   order (edge+biometric → mobile+device → web+behavior → smallest canonical id as final
   deterministic fallback). The event's own cluster merges with the chosen target only.
5. **Behavioral consistency** (PRD doesn't define it) — two `behavior_data` objects are
   consistent when they share ≥1 numeric key and every shared numeric value agrees within
   25% relative tolerance.
6. **Timestamp storage** — ISO-8601 UTC strings with fixed microsecond width, so
   lexicographic order == chronological order (safe range queries in DuckDB as TEXT).
7. **Versioning** — one version row per accepted event, numbered per canonical id.
   When identities merge, prior rows stay under their old canonical id (history is
   preserved), new rows continue under the merged canonical id.

## Not built, and why

- **ONNX Runtime** — embeddings arrive precomputed in the payload (per the PRD's own
  scope); there is no inference to run server-side.
- **Airflow / AWS** — allowed by constraints but nothing in the requirements needs
  orchestration or cloud; batch replay is a CLI.
- **Flutter** — PRD says React *or* Flutter; React chosen (single-file dashboard).
- **Bonus scope** (voice modality, confidence weighting, offline sync) — out of MVP.

## Layout

```
engine.py              # validation, resolution, DuckDB state, audit, rejection log, replay-from-log
server.py              # FastAPI: POST /events, /api/* JSON endpoints, serves the 4 Aether pages
replay.py              # CLI: replay a fixture file → DB + audit JSON
frontend/index.html    # Landing page (Stitch "Aether Identity" design)
frontend/dashboard.html# Identity graph dashboard: KPIs, SVG graph + scrubber, details, heatmap
frontend/audit.html    # Audit history: search/filters/pagination + decision trace panel
frontend/replay.html   # Replay verification: event timeline + simulation comparison
frontend/theme.js      # Stitch design tokens (tailwind config), shared by all pages
frontend/app.js        # shared data layer: api(), strategy/platform metadata, formatters
fixtures/              # make_fixtures.py + 6 generated edge-case datasets
tests/test_engine.py   # duplicate, late/7-day boundary, tie-breaks, replay determinism, midnight
audit_output/          # generated decision-trace files (committed as deliverable)
```

**Identity graph at population scale.** With ~113 identities, drawing every
cluster as a node-link diagram is a hairball that says nothing — no two
identities share an edge, so the link structure only matters *within* one
identity. The graph is therefore two views: an **overview** (one dot per
identity, area = event count, colour = resolution class, ring = merged, with
search + a merged-only filter) and a **focus** view reached by clicking a dot,
which draws that identity's real structure with each edge labelled by the
strategy that linked it (biometric / device / behavior / temporal, read from the
identity's version history). Labels appear automatically once a filtered set is
small enough (≤24) to hold them.

**2026-08-16 (later):** frontend rebuilt to the Stitch "Aether Identity" design
(project 17477230937716791356). Read APIs moved under `/api/*` so `/audit` and
`/replay` can serve pages; `POST /events` unchanged (PRD-mandated). Added:
rejections/duplicates log (real "Rejected" rows in the audit UI), decision-detail
endpoint with SHA-256 integrity hash and previous-state diff, audit export
download, and replay responses carrying the simulated trail for the comparison UI.

## Data model (DuckDB)

- `events(event_key PK, seq, platform, event_type, ts, user_id, device_id, embedding, confidence, behavior, raw)`
- `clusters(user_id PK, canonical_id)`
- `identity_versions(canonical_id, version, decision_ts, strategy, reason, event_key, merged, seq)`

`event_key = platform|user_id|event_type|ts` — the PRD's duplicate definition, and the
idempotency key. Replay = re-ingest `events.raw` in `seq` order into a fresh engine and
compare audit trails.
