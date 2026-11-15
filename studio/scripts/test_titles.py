"""Fallback titles must read like titles, not like raw caption lines."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipblitz.virality import clean_title

CASES = [
    ("Run wide, [music] crash, and have to start over. Confidence goes. You ",
     "Run wide, crash, and have to start over. Confidence goes."),
    (">> Day two, made it through the night, top six. Still got our our main",
     "Day two, made it through the night, top six. Still got our main"),
    ("  [applause]  He won the whole thing, and  ", "He won the whole thing"),
    ("", "Clip"),
]
failed = 0
for raw, want in CASES:
    got = clean_title(raw)
    ok = got == want
    print(("[PASS] " if ok else "[FAIL] ") + repr(raw) + " -> " + repr(got))
    if not ok:
        print("       wanted " + repr(want))
        failed += 1
long = clean_title("word " * 60).split()
ok = len(" ".join(long)) <= 90 and len(long) > 0
print(("[PASS] " if ok else "[FAIL] ") + "long titles are cut at a word boundary")
failed += 0 if ok else 1
print(f"{len(CASES) + 1 - failed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
