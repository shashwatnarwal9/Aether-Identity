"""Seed ~100 deterministic identities through the real ingestion endpoint.

Each persona i gets a 1-hour session (spaced 105 min apart so only adjacent
sessions share the 2-hour window) with events crafted to exercise every
resolution strategy without ever cross-linking personas:

- embeddings are two-hot vectors on axis i (orthogonal between personas, and
  cosine-distant from the one-hot fixture embeddings even on the same axis)
- devices are unique per persona; behavior keys (scroll_rate/tap_interval)
  never overlap the fixture keys, and adjacent personas alternate magnitude
  ~10x so the 25% tolerance can't link them

Run (server must be up):  python fixtures/seed_100.py [--url http://127.0.0.1:8000]
Writes fixtures/seed_100.json as the reproducible event log.
"""
import argparse
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
START = datetime(2026, 8, 8, 16, 0, tzinfo=timezone.utc)  # within 7d of fixture watermark
N = 100


def emb(axis, noise=0.0):
    v = [0.0] * 128
    v[axis % 128] = 0.8
    v[(axis + 7) % 128] = 0.6 + noise  # two-hot: never matches the one-hot fixtures
    return v


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_events():
    events = []
    for i in range(N):
        t0 = START + timedelta(minutes=105 * i)
        dev = f"dev-{i:03d}"
        mob, web, edge = f"p{i:03d}_mobile", f"p{i:03d}_web", f"p{i:03d}_edge"
        # anchor: mobile login. No embedding in the edge branch — otherwise the edge
        # face_auth merges early via fallback and edge_biometric_priority never fires.
        anchor = {"platform": "mobile", "event_type": "login", "timestamp": iso(t0),
                  "user_id": mob, "device_id": dev}
        if i % 10 < 6:
            anchor.update(embedding=emb(i), confidence=round(0.80 + (i % 20) * 0.01, 2))
        events.append(anchor)
        # 60%: web behavior on the same device -> mobile_device_priority merge
        if i % 10 < 6:
            mag = 8.0 if i % 2 == 0 else 80.0  # alternate ~10x so neighbors never behavior-match
            events.append({"platform": "web", "event_type": "behavior", "timestamp": iso(t0 + timedelta(minutes=20)),
                           "user_id": web, "device_id": dev,
                           "behavior_data": {"scroll_rate": round(mag + i * 0.001, 3),
                                             "tap_interval": round(mag * 3 + i * 0.001, 3)}})
        # 40%: edge face auth, then a mobile face auth that biometric-matches it
        # -> edge_biometric_priority merge
        if i % 10 >= 6:
            events.append({"platform": "edge", "event_type": "face_auth", "timestamp": iso(t0 + timedelta(minutes=30)),
                           "user_id": edge, "device_id": f"edge-kiosk-{i % 12}",
                           "embedding": emb(i), "confidence": round(0.90 + (i % 10) * 0.01, 2)})
            events.append({"platform": "mobile", "event_type": "face_auth", "timestamp": iso(t0 + timedelta(minutes=50)),
                           "user_id": mob, "device_id": dev,
                           "embedding": emb(i, noise=0.05), "confidence": round(0.85 + (i % 12) * 0.01, 2)})
        # every 15th persona: duplicate resend of the anchor login (idempotency rows)
        if i % 15 == 0:
            events.append(dict(anchor))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--dry-run", action="store_true", help="only write seed_100.json")
    args = ap.parse_args()

    events = build_events()
    (HERE / "seed_100.json").write_text(json.dumps(events, indent=1))
    print(f"wrote fixtures/seed_100.json ({len(events)} events)")
    if args.dry_run:
        return

    counts = {}
    for e in events:
        req = urllib.request.Request(args.url + "/events", method="POST",
                                     data=json.dumps(e).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                status = json.load(r)["status"]
        except urllib.error.HTTPError as err:
            status = json.load(err)["status"]
        counts[status] = counts.get(status, 0) + 1
    print(f"ingested: {counts}")


if __name__ == "__main__":
    main()
