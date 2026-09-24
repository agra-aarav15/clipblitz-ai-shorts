"""Route probe: confirm every asset the UI asks for is served, and that the two
dead routes (gsap.min.js, tailwind.css) are gone. Traversal attempts must 404."""
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4301"

CASES = [
    ("/", 200),
    ("/styles.css", 200),
    ("/app.js", 200),
    ("/fonts/inter-latin.woff2", 200),
    ("/fonts/inter-latin-ext.woff2", 200),
    ("/fonts/jetbrains-mono-latin.woff2", 200),
    ("/fonts/jetbrains-mono-latin-ext.woff2", 200),
    ("/fonts/space-grotesk-latin.woff2", 200),
    ("/fonts/space-grotesk-latin-ext.woff2", 200),
    ("/api/health", 200),
    ("/api/styles", 200),
    ("/gsap.min.js", 404),
    ("/tailwind.css", 404),
    ("/fonts/nope.woff2", 404),
    ("/fonts/..%2f.env", 404),
    ("/fonts/../.env", 404),
    ("/.env", 404),
]

bad = 0
for path, want in CASES:
    try:
        r = urllib.request.urlopen(BASE + path)
        got, size = r.status, len(r.read())
    except urllib.error.HTTPError as e:
        got, size = e.code, 0
    except Exception as e:
        got, size = "ERR", str(e)
    ok = got == want
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {str(got):>4} (want {want})  {size:>8}  {path}")

print(f"\n{'PASS' if not bad else 'FAIL'}  {len(CASES) - bad}/{len(CASES)} routes correct")
sys.exit(1 if bad else 0)
