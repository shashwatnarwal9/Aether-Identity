"""CLI replay tool: feed a fixture file through a fresh engine, write the audit trail.

Usage:
    python replay.py fixtures/03_biometric_merge.json
    python replay.py fixtures/*.json --db out.duckdb --audit-dir audit_output
"""
import argparse
import json
from pathlib import Path

from engine import IdentityEngine


def main():
    ap = argparse.ArgumentParser(description="Replay event fixtures deterministically")
    ap.add_argument("files", nargs="+", help="JSON files, each an array of events")
    ap.add_argument("--db", default=":memory:", help="DuckDB path (default in-memory)")
    ap.add_argument("--audit-dir", default="audit_output", help="where audit JSON goes")
    args = ap.parse_args()

    out_dir = Path(args.audit_dir)
    out_dir.mkdir(exist_ok=True)
    for f in args.files:
        engine = IdentityEngine(args.db)
        events = json.loads(Path(f).read_text())
        results = [engine.ingest(e) for e in events]
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        verify = engine.replay_from_log()
        out = out_dir / (Path(f).stem + "_audit.json")
        out.write_text(json.dumps({
            "fixture": f, "ingest_results": results, "status_counts": counts,
            "replay_verification": verify, "audit_trail": engine.audit_trail(),
            "identities": engine.identities(),
        }, indent=2, sort_keys=True))
        print(f"{f}: {counts} | replay reproduced={verify['reproduced']} -> {out}")
        engine.close()


if __name__ == "__main__":
    main()
