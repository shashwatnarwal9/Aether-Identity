import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import IdentityEngine  # noqa: E402


def emb(i, noise=0.0):
    """128-dim unit-ish vector pointing at axis i, optionally nudged (small cosine dist)."""
    v = [0.0] * 128
    v[i] = 1.0
    v[(i + 1) % 128] = noise
    return v


def ev(platform="mobile", event_type="login", timestamp="2026-08-16T10:00:00Z",
       user_id="u1", device_id="d1", **extra):
    return {"platform": platform, "event_type": event_type, "timestamp": timestamp,
            "user_id": user_id, "device_id": device_id, **extra}


def test_validation_rejections():
    e = IdentityEngine()
    assert e.ingest({"platform": "mobile"})["status"] == "rejected"
    assert e.ingest(ev(platform="tv"))["status"] == "rejected"
    assert e.ingest(ev(timestamp="not-a-date"))["status"] == "rejected"
    assert e.ingest(ev(embedding=[0.1] * 127))["status"] == "rejected"
    assert e.ingest(ev(confidence=1.5))["status"] == "rejected"
    assert e.audit_trail() == []


def test_duplicate_event_is_idempotent():
    e = IdentityEngine()
    first = e.ingest(ev())
    assert first["status"] == "accepted"
    before = e.audit_trail()
    assert e.ingest(ev())["status"] == "duplicate"
    assert e.audit_trail() == before


def test_rejections_are_logged():
    e = IdentityEngine()
    e.ingest({"platform": "mobile"})               # malformed
    e.ingest(ev())
    e.ingest(ev())                                  # duplicate
    kinds = [r["kind"] for r in e.rejections()]
    assert kinds == ["rejected", "duplicate"]
    assert e.rejections()[1]["event_key"] is not None


def test_decision_detail_and_hash_deterministic():
    e1, e2 = IdentityEngine(), IdentityEngine()
    for eng in (e1, e2):
        eng.ingest(ev(user_id="u1"))
        eng.ingest(ev(user_id="u2", timestamp="2026-08-16T10:30:00Z"))
    d1, d2 = e1.decision(2), e2.decision(2)
    assert d1["hash"] == d2["hash"]
    assert d1["event"]["user_id"] == "u2"
    assert d1["previous_merged"] is None or d1["previous_merged"]["identity_id"]


def test_late_event_window():
    e = IdentityEngine()
    e.ingest(ev(timestamp="2026-08-16T10:00:00Z"))
    ok = e.ingest(ev(user_id="u2", device_id="d2", timestamp="2026-08-09T10:00:01Z"))
    assert ok["status"] == "accepted"  # just inside 7 days behind watermark
    late = e.ingest(ev(user_id="u3", device_id="d3", timestamp="2026-08-09T09:59:59Z"))
    assert late["status"] == "rejected" and "7 days" in late["reason"]


def test_out_of_order_event_still_links():
    e = IdentityEngine()
    e.ingest(ev(user_id="u1", timestamp="2026-08-16T12:00:00Z"))
    # arrives later but happened earlier, same device within 2h -> same identity
    r = e.ingest(ev(user_id="u2", timestamp="2026-08-16T11:00:00Z"))
    assert r["identity_id"] == "u1"
    assert sorted(r["merged"]["user_ids"]) == ["u1", "u2"]


def test_biometric_merge_and_edge_priority_conflict():
    e = IdentityEngine()
    # cluster A: edge face auth; cluster B: mobile login sharing device with new event
    e.ingest(ev(platform="edge", event_type="face_auth", user_id="edge_a",
                device_id="kiosk1", embedding=emb(0), confidence=0.98))
    e.ingest(ev(platform="mobile", user_id="mob_b", device_id="phone9",
                timestamp="2026-08-16T10:30:00Z"))
    # new event matches A by biometrics AND B by device -> edge biometric wins
    r = e.ingest(ev(platform="mobile", event_type="face_auth", user_id="u_new",
                    device_id="phone9", embedding=emb(0, noise=0.1),
                    timestamp="2026-08-16T11:00:00Z"))
    assert r["strategy"] == "edge_biometric_priority"
    assert "conflict" in r["reason"]
    assert sorted(r["merged"]["user_ids"]) == ["edge_a", "u_new"]


def test_mobile_device_priority_when_no_edge_match():
    e = IdentityEngine()
    e.ingest(ev(platform="mobile", user_id="mob_b", device_id="phone9"))
    e.ingest(ev(platform="web", user_id="web_c", device_id="browser1",
                event_type="behavior", behavior_data={"click_freq": 10.0},
                timestamp="2026-08-16T10:10:00Z"))
    r = e.ingest(ev(platform="web", user_id="u_new", device_id="phone9",
                    event_type="behavior", behavior_data={"click_freq": 10.5},
                    timestamp="2026-08-16T11:00:00Z"))
    assert r["strategy"] == "mobile_device_priority"
    assert sorted(r["merged"]["user_ids"]) == ["mob_b", "u_new"]


def test_web_behavior_priority():
    e = IdentityEngine()
    e.ingest(ev(platform="web", user_id="web_c", device_id="browser1",
                event_type="behavior", behavior_data={"click_freq": 10.0}))
    r = e.ingest(ev(platform="mobile", user_id="u_new", device_id="phone1",
                    event_type="behavior", behavior_data={"click_freq": 10.5},
                    timestamp="2026-08-16T10:30:00Z"))
    assert r["strategy"] == "web_behavior_priority"
    assert r["identity_id"] == "u_new"  # min("u_new", "web_c")


def test_behavior_inconsistent_no_merge():
    e = IdentityEngine()
    e.ingest(ev(platform="web", user_id="web_c", device_id="browser1",
                event_type="behavior", behavior_data={"click_freq": 10.0}))
    r = e.ingest(ev(platform="mobile", user_id="u_new", device_id="phone1",
                    event_type="behavior", behavior_data={"click_freq": 50.0},
                    timestamp="2026-08-16T10:30:00Z"))
    assert r["strategy"] == "new_identity"


def test_midnight_boundary():
    e = IdentityEngine()
    e.ingest(ev(user_id="u1", timestamp="2026-08-15T23:30:00Z"))
    r = e.ingest(ev(user_id="u2", timestamp="2026-08-16T00:30:00Z"))
    assert r["identity_id"] == "u1"  # 1h apart across midnight -> merged
    far = e.ingest(ev(user_id="u3", device_id="d9", timestamp="2026-08-16T03:00:00Z"))
    assert far["strategy"] == "new_identity"  # outside 2h window


def test_temporal_window_exact_boundary():
    e = IdentityEngine()
    e.ingest(ev(user_id="u1", timestamp="2026-08-16T10:00:00Z"))
    r = e.ingest(ev(user_id="u2", timestamp="2026-08-16T12:00:00Z"))
    assert r["identity_id"] == "u1"  # exactly 2h -> inclusive


def test_replay_reproduces_and_is_idempotent():
    e = IdentityEngine()
    events = [
        ev(platform="edge", event_type="face_auth", user_id="a", device_id="k1",
           embedding=emb(3), confidence=0.9),
        ev(platform="mobile", user_id="b", device_id="p1",
           timestamp="2026-08-16T10:20:00Z", embedding=emb(3, noise=0.05)),
        ev(platform="web", user_id="c", device_id="w1", event_type="behavior",
           timestamp="2026-08-16T10:40:00Z", behavior_data={"clicks": 5.0}),
        ev(platform="mobile", user_id="b", device_id="p1",  # duplicate
           timestamp="2026-08-16T10:20:00Z", embedding=emb(3, noise=0.05)),
    ]
    for x in events:
        e.ingest(x)
    trail = e.audit_trail()
    # replaying the full log changes nothing (idempotency)
    for x in events:
        e.ingest(x)
    assert e.audit_trail() == trail
    # fresh engine, same input -> identical decisions (determinism)
    assert e.replay_from_log() == {"reproduced": True, "events_replayed": len(trail)}
    e2 = IdentityEngine()
    for x in events:
        e2.ingest(x)
    assert e2.audit_trail() == trail
