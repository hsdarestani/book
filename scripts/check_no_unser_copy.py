#!/usr/bin/env python3
from pathlib import Path
import re
import sys

PATTERN = re.compile(r"\bunser(?:e|er|em|en|es)?\b", re.IGNORECASE)
ROOTS = [Path("templates"), Path("static/booking")]
EXTENSIONS = {".html", ".js", ".json", ".txt"}

violations = []
for root in ROOTS:
    if not root.exists():
        continue
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                violations.append(f"{path}:{lineno}: {line.strip()}")

if violations:
    print("Forbidden first-person brand copy found:")
    print("\n".join(violations))
    sys.exit(1)

print("NO_UNSER_COPY=success")
