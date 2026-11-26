"""
Step 4: Validation, Quarantine Review & Final JSON Export for Dad's Fishing Notes.

Reads scripts/etl/output/step3_parsed.json, enforces schema and constraint
validation against the Dad Fishing PWA v2 rules, isolates any quarantined or
approximate items into scripts/etl/output/step4_quarantine_report.json, and
exports the clean importable bundle to scripts/etl/output/pit2_legacy_import_v2.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VALID_CARP_TYPES = {"Mirror", "Common"}
VALID_RODS = {"Left", "Middle", "Right"}


def is_valid_iso(ts: str | None) -> bool:
    """Return True if ts parses as a valid ISO-8601 date/datetime string."""
    if not ts or not isinstance(ts, str):
        return False
    try:
        datetime.fromisoformat(ts)
        return True
    except ValueError:
        return False


def validate_and_build_bundle(step3_data: dict) -> tuple[dict, dict, dict[str, int]]:
    """
    Validate sessions, swim_stints, and catches.
    Returns (import_bundle, quarantine_report, summary_stats).
    """
    raw_sessions = step3_data.get("sessions", [])
    excluded_items = step3_data.get("excluded_items", [])

    clean_sessions: list[dict] = []
    quarantined_catches: list[dict] = []
    quarantined_sessions: list[dict] = []

    stats = {
        "input_sessions": len(raw_sessions),
        "exported_sessions": 0,
        "exported_stints": 0,
        "exported_catches": 0,
        "quarantined_catches": 0,
        "excluded_lines_logged": len(excluded_items),
        "approximate_weights_flagged": 0,
    }

    for sess in raw_sessions:
        sess_id = sess.get("temp_session_id", "")
        lake_name = (sess.get("lake_name") or "").strip()
        start_time = sess.get("start_time")
        end_time = sess.get("end_time")

        if not sess_id or not lake_name or not is_valid_iso(start_time) or not is_valid_iso(end_time):
            quarantined_sessions.append(
                {
                    "temp_session_id": sess_id,
                    "reason": "Invalid session ID, lake_name, or ISO timestamp",
                    "session": sess,
                }
            )
            continue

        stints = sess.get("swim_stints", [])
        valid_stint_ids: set[str] = set()
        clean_stints: list[dict] = []

        for st in stints:
            st_id = st.get("temp_stint_id", "")
            st_name = (st.get("swim_name") or "").strip()
            st_start = st.get("started_at")
            st_end = st.get("ended_at")
            if st_id and st_name and is_valid_iso(st_start) and is_valid_iso(st_end):
                valid_stint_ids.add(st_id)
                clean_stints.append(
                    {
                        "temp_stint_id": st_id,
                        "swim_name": st_name,
                        "started_at": st_start,
                        "ended_at": st_end,
                    }
                )

        if not clean_stints:
            fallback_stint_id = f"{sess_id}_stint_01"
            valid_stint_ids.add(fallback_stint_id)
            clean_stints.append(
                {
                    "temp_stint_id": fallback_stint_id,
                    "swim_name": "Unknown Swim",
                    "started_at": start_time,
                    "ended_at": end_time,
                }
            )

        clean_catches: list[dict] = []
        for c in sess.get("catches", []):
            carp_type = c.get("carp_type")
            rod = c.get("rod")
            weight_grams = c.get("weight_grams")
            caught_at = c.get("caught_at")
            stint_id = c.get("temp_stint_id")
            notes = c.get("notes") or ""

            issues: list[str] = []
            if carp_type not in VALID_CARP_TYPES:
                issues.append(f"Invalid carp_type: {carp_type!r}")
            if rod not in VALID_RODS:
                issues.append(f"Invalid rod: {rod!r}")
            if not isinstance(weight_grams, int) or isinstance(weight_grams, bool) or weight_grams <= 0:
                issues.append(f"Invalid weight_grams: {weight_grams!r}")
            if not is_valid_iso(caught_at):
                issues.append(f"Invalid caught_at timestamp: {caught_at!r}")
            if stint_id not in valid_stint_ids:
                issues.append(f"Unlinked temp_stint_id: {stint_id!r}")

            if issues:
                stats["quarantined_catches"] += 1
                quarantined_catches.append(
                    {
                        "temp_session_id": sess_id,
                        "reasons": issues,
                        "catch": c,
                    }
                )
                continue

            if "approximate weight" in notes.lower() or "parsed decimal" in notes.lower() or "parsed '" in notes.lower():
                stats["approximate_weights_flagged"] += 1

            clean_catches.append(
                {
                    "temp_stint_id": stint_id,
                    "lake_name": c.get("lake_name") or lake_name,
                    "swim_name": c.get("swim_name") or clean_stints[-1]["swim_name"],
                    "carp_type": carp_type,
                    "rod": rod,
                    "weight_grams": weight_grams,
                    "caught_at": caught_at,
                    "moon_illumination_pct": float(c.get("moon_illumination_pct", 0.0)),
                    "moon_phase": str(c.get("moon_phase", "Unknown")),
                    "description": str(c.get("description") or ""),
                    "notes": notes,
                }
            )

        clean_sessions.append(
            {
                "temp_session_id": sess_id,
                "lake_name": lake_name,
                "start_time": start_time,
                "end_time": end_time,
                "notes": str(sess.get("notes") or ""),
                "swim_stints": clean_stints,
                "catches": clean_catches,
            }
        )
        stats["exported_sessions"] += 1
        stats["exported_stints"] += len(clean_stints)
        stats["exported_catches"] += len(clean_catches)

    import_bundle = {
        "format_version": "2.0",
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "legacy_notes_pit_2",
        "sessions": clean_sessions,
    }

    quarantine_report = {
        "step": 4,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "summary": stats,
        "quarantined_sessions": quarantined_sessions,
        "quarantined_catches": quarantined_catches,
        "excluded_non_carp_or_lost": excluded_items,
    }

    return import_bundle, quarantine_report, stats


def main() -> None:
    etl_dir = Path(__file__).resolve().parent
    input_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else etl_dir / "output" / "step3_parsed.json"
    )
    bundle_out = etl_dir / "output" / "pit2_legacy_import_v2.json"
    quarantine_out = etl_dir / "output" / "step4_quarantine_report.json"

    if not input_path.exists():
        print(f"Error: Parsed file not found at {input_path}")
        print("Run step3_parse_catches.py first.")
        sys.exit(1)

    step3_data = json.loads(input_path.read_text(encoding="utf-8"))
    bundle, quarantine, stats = validate_and_build_bundle(step3_data)

    bundle_out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    quarantine_out.write_text(json.dumps(quarantine, indent=2), encoding="utf-8")

    print(f"Exported final bundle to:    {bundle_out}")
    print(f"Wrote quarantine report to:  {quarantine_out}")
    print(f"Sessions exported:           {stats['exported_sessions']}")
    print(f"Swim stints exported:        {stats['exported_stints']}")
    print(f"Catches exported:            {stats['exported_catches']}")
    print(f"Quarantined catches:         {stats['quarantined_catches']}")
    print(f"Approximate weights noted:   {stats['approximate_weights_flagged']}")
    print(f"Excluded items logged:       {stats['excluded_lines_logged']}")


if __name__ == "__main__":
    main()