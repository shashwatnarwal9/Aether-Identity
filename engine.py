"""Identity resolution engine: validation, deterministic resolution, DuckDB state, audit."""
import bisect
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import duckdb

PLATFORMS = {"mobile", "web", "edge"}
EVENT_TYPES = {"login", "face_auth", "behavior"}
EMBEDDING_DIM = 128
TEMPORAL_WINDOW = timedelta(hours=2)
LATE_LIMIT = timedelta(days=7)
COSINE_MAX = 0.15
BEHAVIOR_TOLERANCE = 0.25

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    event_key TEXT PRIMARY KEY, seq BIGINT, platform TEXT, event_type TEXT,
    ts TEXT, user_id TEXT, device_id TEXT,
    embedding TEXT, confidence DOUBLE, behavior TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS clusters(user_id TEXT PRIMARY KEY, canonical_id TEXT);
CREATE TABLE IF NOT EXISTS identity_versions(
    canonical_id TEXT, version BIGINT, decision_ts TEXT, strategy TEXT,
    reason TEXT, event_key TEXT, merged TEXT, seq BIGINT);
CREATE TABLE IF NOT EXISTS rejections(
    rseq BIGINT, kind TEXT, event_key TEXT, platform TEXT, user_id TEXT,
    event_type TEXT, ts TEXT, reason TEXT, raw TEXT);
"""


class ValidationError(ValueError):
    pass


def parse_ts(value):
    if not isinstance(value, str):
        raise ValidationError("timestamp must be an ISO 8601 string")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"invalid timestamp: {value!r}")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def ts_iso(ts):
    # Fixed microsecond width so lexicographic order == chronological order.
    return ts.isoformat(timespec="microseconds")


def normalized(v):
    """Unit vector, or None for a zero vector (which can never be a biometric match)."""
    if v is None:
        return None
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else None


def cosine_distance(a, b):
    """a, b pre-normalized unit vectors."""
    return 1.0 - sum(x * y for x, y in zip(a, b))


def behavior_consistent(a, b):
    shared = [k for k in a
              if k in b and isinstance(a[k], (int, float)) and isinstance(b[k], (int, float))
              and not isinstance(a[k], bool) and not isinstance(b[k], bool)]
    if not shared:
        return False
    return all(abs(a[k] - b[k]) <= BEHAVIOR_TOLERANCE * max(abs(a[k]), abs(b[k]), 1e-9)
               for k in shared)


def validate(raw):
    if not isinstance(raw, dict):
        raise ValidationError("event must be a JSON object")
    for field in ("platform", "event_type", "timestamp", "user_id", "device_id"):
        if not raw.get(field):
            raise ValidationError(f"missing required field: {field}")
    if raw["platform"] not in PLATFORMS:
        raise ValidationError(f"invalid platform: {raw['platform']!r}")
    if raw["event_type"] not in EVENT_TYPES:
        raise ValidationError(f"invalid event_type: {raw['event_type']!r}")
    ts = parse_ts(raw["timestamp"])
    embedding = raw.get("embedding")
    if embedding is not None:
        if (not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIM
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in embedding)):
            raise ValidationError(f"embedding must be a {EMBEDDING_DIM}-dim float array")
    confidence = raw.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ValidationError("confidence must be a float in [0, 1]")
    behavior = raw.get("behavior_data")
    if behavior is not None and not isinstance(behavior, dict):
        raise ValidationError("behavior_data must be an object")
    return {
        "platform": raw["platform"], "event_type": raw["event_type"],
        "ts": ts, "user_id": str(raw["user_id"]), "device_id": str(raw["device_id"]),
        "embedding": embedding, "confidence": confidence, "behavior": behavior,
    }


class IdentityEngine:
    """DuckDB is the durable log; a rebuilt-on-startup in-memory index makes the
    per-event candidate scan fast enough for the 100 events/sec requirement.
    ponytail: whole index in RAM (~1GB per million embedded events, well under the
    16GB budget); page the window index into DuckDB if volume ever outgrows that."""

    def __init__(self, db_path=":memory:"):
        self.db = duckdb.connect(db_path)
        self.db.execute(SCHEMA)
        self._keys = set()
        self._by_ts = []       # sorted [(ts_iso, seq, event dict)]
        self._by_user = {}     # user_id -> [event dict] in ingest order
        self._clusters = {}    # user_id -> canonical_id
        self._versions = {}    # canonical_id -> latest version number
        self._watermark = None  # max event ts seen, as datetime
        self._seq = 0
        for row in self.db.execute(
                "SELECT seq, platform, event_type, ts, user_id, device_id, "
                "embedding, confidence, behavior FROM events ORDER BY seq").fetchall():
            seq, platform, event_type, ts, user_id, device_id, emb, conf, beh = row
            self._index({"seq": seq, "platform": platform, "event_type": event_type,
                         "ts": ts, "user_id": user_id, "device_id": device_id,
                         "embedding": json.loads(emb) if emb else None,
                         "confidence": conf,
                         "behavior": json.loads(beh) if beh else None})
            self._keys.add("|".join([platform, user_id, event_type, ts]))
        for u, c in self.db.execute("SELECT user_id, canonical_id FROM clusters").fetchall():
            self._clusters[u] = c
        for c, v in self.db.execute(
                "SELECT canonical_id, max(version) FROM identity_versions "
                "GROUP BY canonical_id").fetchall():
            self._versions[c] = v

    def close(self):
        self.db.close()

    def _index(self, ev):
        ev["nemb"] = normalized(ev["embedding"])
        bisect.insort(self._by_ts, (ev["ts"], ev["seq"], ev))
        self._by_user.setdefault(ev["user_id"], []).append(ev)
        self._seq = max(self._seq, ev["seq"])
        ts = datetime.fromisoformat(ev["ts"])
        if self._watermark is None or ts > self._watermark:
            self._watermark = ts

    def canonical_of(self, user_id):
        return self._clusters.get(user_id)

    def _log_rejection(self, kind, key, raw, reason, ev=None):
        rseq = self.db.execute("SELECT coalesce(max(rseq), 0) + 1 FROM rejections").fetchone()[0]
        self.db.execute(
            "INSERT INTO rejections VALUES (?,?,?,?,?,?,?,?,?)",
            [rseq, kind, key,
             ev["platform"] if ev else (raw.get("platform") if isinstance(raw, dict) else None),
             ev["user_id"] if ev else (raw.get("user_id") if isinstance(raw, dict) else None),
             ev["event_type"] if ev else (raw.get("event_type") if isinstance(raw, dict) else None),
             ts_iso(ev["ts"]) if ev else None, reason,
             json.dumps(raw, sort_keys=True, default=str) if isinstance(raw, dict) else None])

    def ingest(self, raw):
        try:
            ev = validate(raw)
        except ValidationError as e:
            self._log_rejection("rejected", None, raw, str(e))
            return {"status": "rejected", "reason": str(e)}
        iso = ts_iso(ev["ts"])
        key = "|".join([ev["platform"], ev["user_id"], ev["event_type"], iso])
        if key in self._keys:
            self._log_rejection("duplicate", key, raw, "duplicate event (same platform, user, type, timestamp)", ev)
            return {"status": "duplicate", "event_key": key}
        if self._watermark and ev["ts"] < self._watermark - LATE_LIMIT:
            reason = f"event older than 7 days behind watermark {ts_iso(self._watermark)}"
            self._log_rejection("rejected", key, raw, reason, ev)
            return {"status": "rejected", "event_key": key, "reason": reason}

        canon, strategy, reason = self._resolve(ev, iso)
        seq = self._seq + 1
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [key, seq, ev["platform"], ev["event_type"], iso, ev["user_id"], ev["device_id"],
             json.dumps(ev["embedding"]) if ev["embedding"] is not None else None,
             ev["confidence"],
             json.dumps(ev["behavior"], sort_keys=True) if ev["behavior"] is not None else None,
             json.dumps(raw, sort_keys=True)])
        self._keys.add(key)
        self._index({"seq": seq, "platform": ev["platform"], "event_type": ev["event_type"],
                     "ts": iso, "user_id": ev["user_id"], "device_id": ev["device_id"],
                     "embedding": ev["embedding"], "confidence": ev["confidence"],
                     "behavior": ev["behavior"]})
        merged = self._merged_record(canon)
        version = self._versions.get(canon, 0) + 1
        self._versions[canon] = version
        self.db.execute(
            "INSERT INTO identity_versions VALUES (?,?,?,?,?,?,?,?)",
            [canon, version, iso, strategy, reason, key, json.dumps(merged, sort_keys=True), seq])
        return {"status": "accepted", "event_key": key, "identity_id": canon,
                "version": version, "strategy": strategy, "reason": reason, "merged": merged}

    def _resolve(self, ev, iso):
        """Pick/merge a cluster for the event. Returns (canonical_id, strategy, reason)."""
        own = self.canonical_of(ev["user_id"])
        lo = ts_iso(ev["ts"] - TEMPORAL_WINDOW)
        hi = ts_iso(ev["ts"] + TEMPORAL_WINDOW)
        lo_i = bisect.bisect_left(self._by_ts, (lo, -1))
        hi_i = bisect.bisect_right(self._by_ts, (hi, 1 << 62))
        nemb = normalized(ev["embedding"])
        # matches: canonical_id -> {(kind, platform): first matching event_key}
        matches = {}
        for _, _, e in self._by_ts[lo_i:hi_i]:
            kinds = []
            if nemb is not None and e["nemb"] is not None \
                    and cosine_distance(nemb, e["nemb"]) <= COSINE_MAX:
                kinds.append("biometric")
            if ev["device_id"] == e["device_id"]:
                kinds.append("device")
            if ev["behavior"] is not None and e["behavior"] is not None \
                    and behavior_consistent(ev["behavior"], e["behavior"]):
                kinds.append("behavior")
            if kinds:
                canon = self.canonical_of(e["user_id"]) or e["user_id"]
                e_key = "|".join([e["platform"], e["user_id"], e["event_type"], e["ts"]])
                for kind in kinds:
                    matches.setdefault(canon, {}).setdefault((kind, e["platform"]), e_key)

        others = {c: k for c, k in matches.items() if c != (own or ev["user_id"])}
        if not others:
            if own is None:
                self._set_canonical(ev["user_id"], ev["user_id"])
                return ev["user_id"], "new_identity", "no matching identity within temporal window"
            return own, "same_user_append", "event matched only its own identity"

        # PRD tie-break order; sorted() makes multi-candidate picks deterministic.
        for kind, platform, strategy in (("biometric", "edge", "edge_biometric_priority"),
                                         ("device", "mobile", "mobile_device_priority"),
                                         ("behavior", "web", "web_behavior_priority")):
            hits = sorted(c for c, k in others.items() if (kind, platform) in k)
            if hits:
                target = hits[0]
                reason = f"{kind} match with {platform} event {others[target][(kind, platform)]}"
                break
        else:
            target = sorted(others)[0]
            strategy = "deterministic_fallback"
            reason = f"matched {sorted(others)} without priority signal; picked smallest id"
        if len(others) > 1:
            reason += f"; conflict among {sorted(others)} resolved by {strategy}"

        canon = self._merge_clusters(ev["user_id"], own, target)
        return canon, strategy, reason

    def _set_canonical(self, user_id, canon):
        self._clusters[user_id] = canon
        self.db.execute(
            "INSERT INTO clusters VALUES (?, ?) ON CONFLICT DO UPDATE SET canonical_id = ?",
            [user_id, canon, canon])

    def _merge_clusters(self, user_id, own, target):
        members = {user_id}
        for c in filter(None, (own, target)):
            members.update(u for u, cc in self._clusters.items() if cc == c)
        canon = min(members)
        for m in sorted(members):
            self._set_canonical(m, canon)
        return canon

    def _merged_record(self, canon):
        members = sorted(u for u, c in self._clusters.items() if c == canon)
        rows = sorted((e for u in members for e in self._by_user.get(u, [])),
                      key=lambda e: (e["ts"], e["seq"]))
        behavior = {}
        for e in rows:
            if e["behavior"] is not None:
                behavior.update(e["behavior"])
        confidences = [e["confidence"] for e in rows if e["confidence"] is not None]
        return {
            "identity_id": canon,
            "user_ids": members,
            "device_ids": sorted({e["device_id"] for e in rows}),
            "platforms": sorted({e["platform"] for e in rows}),
            "first_seen": rows[0]["ts"] if rows else None,
            "last_seen": rows[-1]["ts"] if rows else None,
            "event_count": len(rows),
            "max_confidence": max(confidences) if confidences else None,
            "has_biometric": any(e["embedding"] is not None for e in rows),
            "behavior": behavior,
        }

    def identities(self):
        return [self._merged_record(c) for c in sorted(set(self._clusters.values()))]

    def identity_detail(self, canon):
        rows = self.db.execute(
            "SELECT version, decision_ts, strategy, reason, event_key, merged "
            "FROM identity_versions WHERE canonical_id = ? ORDER BY version", [canon]).fetchall()
        if not rows:
            return None
        return {"identity": self._merged_record(canon),
                "versions": [{"version": v, "decision_ts": ts, "strategy": s,
                              "reason": r, "event_key": k, "merged": json.loads(m)}
                             for v, ts, s, r, k, m in rows]}

    def audit_trail(self):
        rows = self.db.execute(
            "SELECT seq, canonical_id, version, decision_ts, strategy, reason, event_key, merged "
            "FROM identity_versions ORDER BY seq").fetchall()
        return [{"seq": seq, "identity_id": c, "version": v, "decision_ts": ts,
                 "strategy": s, "reason": r, "event_key": k, "merged": json.loads(m)}
                for seq, c, v, ts, s, r, k, m in rows]

    def audit_trail_enriched(self):
        """Audit rows joined with the triggering event's platform/user/type/confidence."""
        rows = self.db.execute(
            "SELECT v.seq, v.canonical_id, v.version, v.decision_ts, v.strategy, v.reason, "
            "v.event_key, v.merged, e.platform, e.user_id, e.event_type, e.confidence "
            "FROM identity_versions v JOIN events e ON v.event_key = e.event_key "
            "ORDER BY v.seq").fetchall()
        return [{"seq": seq, "identity_id": c, "version": v, "decision_ts": ts,
                 "strategy": s, "reason": r, "event_key": k, "merged": json.loads(m),
                 "platform": p, "user_id": u, "event_type": et, "confidence": conf}
                for seq, c, v, ts, s, r, k, m, p, u, et, conf in rows]

    def rejections(self):
        rows = self.db.execute(
            "SELECT rseq, kind, event_key, platform, user_id, event_type, ts, reason, raw "
            "FROM rejections ORDER BY rseq").fetchall()
        return [{"rseq": rseq, "kind": kind, "event_key": k, "platform": p, "user_id": u,
                 "event_type": et, "decision_ts": ts, "reason": r,
                 "raw": json.loads(raw) if raw else None}
                for rseq, kind, k, p, u, et, ts, r, raw in rows]

    def decision(self, seq):
        """Full detail for one decision: audit row, raw input event, previous merged
        state (for the reconciliation diff), and a deterministic integrity hash."""
        rows = [a for a in self.audit_trail_enriched() if a["seq"] == seq]
        if not rows:
            return None
        entry = rows[0]
        prev = self.db.execute(
            "SELECT merged FROM identity_versions WHERE canonical_id = ? AND version = ?",
            [entry["identity_id"], entry["version"] - 1]).fetchone()
        raw = self.db.execute(
            "SELECT raw FROM events WHERE event_key = ?", [entry["event_key"]]).fetchone()
        core = {k: entry[k] for k in ("seq", "identity_id", "version", "decision_ts",
                                      "strategy", "reason", "event_key", "merged")}
        entry["hash"] = hashlib.sha256(
            json.dumps(core, sort_keys=True).encode()).hexdigest()
        entry["event"] = json.loads(raw[0]) if raw else None
        entry["previous_merged"] = json.loads(prev[0]) if prev else None
        return entry

    def raw_events(self):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT raw FROM events ORDER BY seq").fetchall()]

    def replay_from_log(self, include_trail=False):
        """Re-ingest the stored event log into a fresh engine and compare audit trails."""
        events = self.raw_events()
        fresh = IdentityEngine(":memory:")
        for e in events:
            fresh.ingest(e)
        result = {"reproduced": fresh.audit_trail() == self.audit_trail(),
                  "events_replayed": len(events)}
        if include_trail:
            result["trail"] = fresh.audit_trail_enriched()
            result["identities"] = fresh.identities()
        fresh.close()
        return result
