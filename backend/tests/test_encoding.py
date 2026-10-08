"""Windows defaults to cp1252: every text file read/write must name its encoding."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PAT = re.compile(r"(read_text\(\)|write_text\([^)]*\)|\bopen\([^)]*\))")


def test_text_io_names_encoding():
    bad = []
    for p in ROOT.rglob("*.py"):
        if any(x in p.parts for x in (".venv", "venv", "__pycache__", "site-packages")) or p.name == "test_encoding.py":
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if PAT.search(line) and "encoding" not in line and not re.search(r"""["'][rwa]?b["']""", line):
                bad.append(f"{p.relative_to(ROOT)}:{n}")
    assert not bad, bad
