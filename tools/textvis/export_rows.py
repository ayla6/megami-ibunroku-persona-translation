"""Build rows.json for the textbox visualiser: the same records /rows serves,
for a file:// open with no server behind it.

The server is the live path. This reuses the server's own reader instead of
keeping a second copy of the merge rules (manual over generated, Japanese
when neither has English).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import serve  # noqa: E402

OUT = os.path.join(HERE, "rows.json")
rows = serve.rows()
open(OUT, "w", encoding="utf-8").write(
    json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
print(f"{OUT}: {len(rows)} rows, {os.path.getsize(OUT)} bytes")
