"""Regenerates the fixture datasets. Deterministic — no randomness.

Run from repo root:  python fixtures/make_fixtures.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def emb(axis, noise=0.0):
    v = [0.0] * 128
    v[axis] = 1.0
    v[(axis + 1) % 128] = noise
    return v


def ev(platform, event_type, timestamp, user_id, device_id, **extra):
    return {"platform": platform, "event_type": event_type, "timestamp": timestamp,
            "user_id": user_id, "device_id": device_id, **extra}


FIXTURES = {
    # 1. Exact duplicates: second copy must be a no-op.
    "01_duplicates.json": [
        ev("mobile", "login", "2026-08-10T09:00:00Z", "alice_mobile", "pixel-7",
           embedding=emb(0), confidence=0.95),
        ev("mobile", "login", "2026-08-10T09:00:00Z", "alice_mobile", "pixel-7",
           embedding=emb(0), confidence=0.95),
        ev("web", "behavior", "2026-08-10T09:30:00Z", "alice_web", "pixel-7",
           behavior_data={"click_freq": 12.0, "mouse_speed": 340.0}),
        ev("web", "behavior", "2026-08-10T09:30:00Z", "alice_web", "pixel-7",
           behavior_data={"click_freq": 12.0, "mouse_speed": 340.0}),
    ],
    # 2. Late/out-of-order: one event 6 days late (accepted, still links via device),
    #    one 8 days behind the watermark (rejected).
    "02_late_events.json": [
        ev("mobile", "login", "2026-08-10T12:00:00Z", "bob_mobile", "iphone-15"),
        ev("edge", "face_auth", "2026-08-10T13:00:00Z", "bob_edge", "kiosk-2",
           embedding=emb(5), confidence=0.99),
        ev("mobile", "login", "2026-08-04T12:30:00Z", "bob_old", "iphone-15"),
        ev("mobile", "login", "2026-08-02T11:00:00Z", "bob_too_old", "iphone-15"),
    ],
    # 3. Cross-platform biometric merge: mobile + edge embeddings within cosine 0.15,
    #    within 2h -> one identity.
    "03_biometric_merge.json": [
        ev("edge", "face_auth", "2026-08-11T08:00:00Z", "carol_edge", "kiosk-1",
           embedding=emb(10), confidence=0.97),
        ev("mobile", "face_auth", "2026-08-11T08:45:00Z", "carol_mobile", "galaxy-s24",
           embedding=emb(10, noise=0.08), confidence=0.91),
        ev("mobile", "face_auth", "2026-08-11T09:15:00Z", "mallory_mobile", "oneplus-12",
           embedding=emb(60), confidence=0.90),  # different face -> separate identity
    ],
    # 4. Conflict: new event matches identity A by edge biometrics AND identity B by
    #    mobile device fingerprint -> edge biometric priority must win.
    "04_conflict_tiebreak.json": [
        ev("edge", "face_auth", "2026-08-12T10:00:00Z", "dave_edge", "kiosk-3",
           embedding=emb(20), confidence=0.99),
        ev("mobile", "login", "2026-08-12T10:15:00Z", "erin_mobile", "phone-77"),
        ev("mobile", "face_auth", "2026-08-12T10:30:00Z", "dave_mobile", "phone-77",
           embedding=emb(20, noise=0.05), confidence=0.93),
        ev("web", "behavior", "2026-08-12T10:45:00Z", "erin_web", "browser-9",
           behavior_data={"click_freq": 8.0}),
        ev("mobile", "behavior", "2026-08-12T11:00:00Z", "erin_phone2", "phone-77",
           behavior_data={"click_freq": 8.2}),  # device (mobile) beats behavior (web)
    ],
    # 5. Midnight transition: 23:30 and 00:30 next day are 1h apart -> same identity;
    #    03:00 is outside the 2h window -> new identity despite same device.
    "05_midnight_boundary.json": [
        ev("web", "login", "2026-08-13T23:30:00Z", "frank_web", "laptop-4"),
        ev("mobile", "login", "2026-08-14T00:30:00Z", "frank_mobile", "laptop-4"),
        ev("mobile", "login", "2026-08-14T03:00:00Z", "frank_late", "laptop-4"),
    ],
    # 6. Behavioral linking: web + mobile telemetry within 25% tolerance -> merged;
    #    a wildly different profile stays separate.
    "06_behavior_link.json": [
        ev("web", "behavior", "2026-08-15T14:00:00Z", "grace_web", "browser-2",
           behavior_data={"click_freq": 10.0, "mouse_speed": 300.0}),
        ev("mobile", "behavior", "2026-08-15T14:20:00Z", "grace_mobile", "pixel-9",
           behavior_data={"click_freq": 11.0, "mouse_speed": 320.0}),
        ev("web", "behavior", "2026-08-15T14:40:00Z", "heidi_web", "browser-3",
           behavior_data={"click_freq": 40.0, "mouse_speed": 900.0}),
    ],
}

if __name__ == "__main__":
    for name, events in FIXTURES.items():
        (HERE / name).write_text(json.dumps(events, indent=2))
        print(f"wrote fixtures/{name} ({len(events)} events)")
