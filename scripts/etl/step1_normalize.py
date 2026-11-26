"""
Step 1: Raw Text Normalization & Audit for Dad's Legacy Fishing Notes.

Reads the raw Apple Notes text export, removes invisible Unicode artifacts,
standardizes swim name variations, normalizes whitespace, and writes a clean
intermediate text file + audit summary for Step 2.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

# Canonical swim names used in Pit 2 (plus Dovecote's Motorway swim).
# Mapping messy variations early prevents fragmented analytics in Explore tab.
SWIM_CANONICAL_MAP: dict[str, str] = {
    "carpark": "Car Park",
    "car park": "Car Park",
    "bk middle": "Back Middle",
    "back middle": "Back Middle",
    "side bay": "Side Bay",
    "point": "Point",
    "the point": "Point",
    "creek": "Creek",
    "posh": "Posh",
    "becks": "Becks",
    "bay": "Bay",
    "reeds": "Reeds",
    "lonely": "Lonely",
    "motorway swim": "Motorway Swim",
}

# Precompile a case-insensitive regex matching whole swim names cleanly.
# Sorting keys longest-first ensures "Side Bay" matches before "Bay",
# and "Back Middle" matches before shorter substrings.
_SWIM_PATTERN = re.compile(
    r"\b("
    + "|".join(re.escape(k) for k in sorted(SWIM_CANONICAL_MAP, key=len, reverse=True))
    + r")\b",
    flags=re.IGNORECASE,
)


def normalize_swim_names(line: str) -> str:
    """Replace inconsistent swim casing/spacing with canonical swim titles."""

    def _replace(match: re.Match[str]) -> str:
        raw_token = match.group(0).lower()
        return SWIM_CANONICAL_MAP[raw_token]

    return _SWIM_PATTERN.sub(_replace, line)


def clean_line(raw_line: str) -> str:
    """
    Clean a single line of raw Apple Notes text:
    1. Remove Unicode Object Replacement Characters (U+FFFC / '￼') left by photos.
    2. Replace non-breaking spaces (\u00a0) with standard ASCII spaces.
    3. Collapse multiple consecutive spaces/tabs into a single space.
    4. Strip leading/trailing whitespace.
    5. Canonicalize known swim names.
    """
    text = raw_line.replace("\ufffc", "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if text:
        text = normalize_swim_names(text)
    return text


def normalize_text(raw_text: str) -> tuple[str, dict[str, int]]:
    """
    Normalize the full document text and return (cleaned_text, audit_stats).
    Collapses runs of 2+ blank lines into a single blank line while preserving
    paragraph breaks between sessions.
    """
    stats: dict[str, int] = {
        "raw_lines": 0,
        "ufffc_removed": raw_text.count("\ufffc"),
        "blank_lines_collapsed": 0,
        "cleaned_lines": 0,
    }

    cleaned_lines: list[str] = []
    previous_was_blank = False

    for raw_line in raw_text.splitlines():
        stats["raw_lines"] += 1
        line = clean_line(raw_line)

        if not line:
            if previous_was_blank:
                stats["blank_lines_collapsed"] += 1
                continue
            previous_was_blank = True
            cleaned_lines.append("")
        else:
            previous_was_blank = False
            cleaned_lines.append(line)

    # Trim leading/trailing empty lines
    while cleaned_lines and cleaned_lines[0] == "":
        cleaned_lines.pop(0)
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()

    stats["cleaned_lines"] = len(cleaned_lines)
    return "\n".join(cleaned_lines) + "\n", stats


def run_audit(cleaned_text: str) -> None:
    """Print quick diagnostic counts so we can verify tokens before Step 2."""
    lines = cleaned_text.splitlines()
    season_headers = [ln for ln in lines if re.search(r"\bseason\b", ln, re.IGNORECASE)]
    swim_hits: Counter[str] = Counter()

    for ln in lines:
        for match in _SWIM_PATTERN.finditer(ln):
            swim_hits[SWIM_CANONICAL_MAP[match.group(0).lower()]] += 1

    print("\n--- STEP 1 AUDIT SUMMARY ---")
    print(f"Season headers found ({len(season_headers)}):")
    for header in season_headers:
        print(f"  • {header}")

    print("\nCanonical swim mentions across file:")
    for swim, count in swim_hits.most_common():
        print(f"  • {swim:<15} {count}")


def main() -> None:
    etl_dir = Path(__file__).resolve().parent
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else etl_dir / "raw_notes.txt"
    output_dir = etl_dir / "output"
    output_path = output_dir / "step1_cleaned.txt"

    if not input_path.exists():
        print(f"Error: Input file not found at {input_path}")
        print("Save your raw notes to scripts/etl/raw_notes.txt or pass a path argument.")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_text = input_path.read_text(encoding="utf-8")
    cleaned_text, stats = normalize_text(raw_text)
    output_path.write_text(cleaned_text, encoding="utf-8")

    print(f"Wrote cleaned text to: {output_path}")
    print(f"Raw lines:             {stats['raw_lines']}")
    print(f"U+FFFC chars stripped: {stats['ufffc_removed']}")
    print(f"Extra blanks removed:  {stats['blank_lines_collapsed']}")
    print(f"Final line count:      {stats['cleaned_lines']}")
    run_audit(cleaned_text)


if __name__ == "__main__":
    main()