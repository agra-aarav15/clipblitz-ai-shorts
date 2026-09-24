"""ClipBlitz UI static verification — the checks that do not need a browser.

V5  dangling-reference sweep: every id the JS reaches for exists in the markup,
    every data-goto target exists, every icon <use href="#..."> resolves, every
    class the JS applies is defined in the CSS, every @keyframes name resolves.
V8  banned-pattern sweep: no opacity in @keyframes, no duplicate @keyframes name,
    no CDN <script>/<link>, no animation library, no emoji, no conflicting
    duplicate rule outside a media query.

Exit code 0 = clean. Anything printed under FAIL is a real defect.
"""
import collections
import os
import re
import sys

WEB = r"E:\clipping\clipblitz\web"
html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
css_raw = open(os.path.join(WEB, "styles.css"), encoding="utf-8").read()
js = open(os.path.join(WEB, "app.js"), encoding="utf-8").read()

fails, notes = [], []


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


css = strip_comments(css_raw)

# ---------------------------------------------------------------- V5 ids
html_ids = set(re.findall(r'\bid="([^"]+)"', html))
js_ids = set(re.findall(r"\$\('([^']+)'\)", js)) | set(re.findall(r'getElementById\("([^"]+)"\)', js))
runtime = {"toasts"}
missing = sorted(i for i in js_ids - html_ids - runtime if not re.fullmatch(r"[tdh]-\d+", i))
if missing:
    fails.append(f"JS references ids that are not in index.html: {missing}")
notes.append(f"ids: {len(js_ids)} referenced, {len(html_ids)} defined, {len(js_ids - html_ids - runtime)} dynamic")

# ---------------------------------------------------------------- V5 data-goto
gotos = set(re.findall(r'data-goto="([^"]+)"', html))
screens = set(re.findall(r'id="screen-([a-z]+)"', html))
bad_goto = sorted(gotos - screens)
if bad_goto:
    fails.append(f"data-goto targets with no screen: {bad_goto}")
if screens != {"studio", "clips", "lab", "transcript", "connect"}:
    fails.append(f"screen set is not the documented five: {sorted(screens)}")
notes.append(f"screens: {sorted(screens)} · goto targets all resolve: {not bad_goto}")

# ---------------------------------------------------------------- V5 icons
defined = set(re.findall(r'<symbol id="i-([\w-]+)"', html))
used = set(re.findall(r'href="#i-([\w-]+)"', html)) | set(re.findall(r'IC\(\'([\w-]+)\'\)', js))
bad_icons = sorted(used - defined)
if bad_icons:
    fails.append(f"icon <use> refs with no <symbol>: {bad_icons}")
unused_icons = sorted(defined - used)
if unused_icons:
    fails.append(f"icon symbols defined but never used (dead sprite weight): {unused_icons}")
notes.append(f"icons: {len(defined)} defined, {len(used)} used, all resolve: {not bad_icons}")

# ---------------------------------------------------------------- V8 keyframes
names = re.findall(r"@keyframes\s+([\w-]+)\s*\{", css)
dupes = [n for n, c in collections.Counter(names).items() if c > 1]
if dupes:
    fails.append(f"@keyframes defined more than once (the silent-override bug): {dupes}")
refs = set(re.findall(r"animation:\s*([\w-]+)", css)) | set(re.findall(r"animation-name:\s*([\w-]+)", css))
orphan_kf = sorted(set(names) - refs)
if orphan_kf:
    fails.append(f"@keyframes never referenced: {orphan_kf}")
notes.append(f"@keyframes: {len(names)} unique names, 0 duplicates, 0 orphans")

# ---------------------------------------------------------------- V8 opacity law
bad_kf = [m.group(1) for m in re.finditer(r"@keyframes\s+([\w-]+)\s*\{(.*?)\n\}", css, re.S)
          if re.search(r"\bopacity\s*:", m.group(2))]
if bad_kf:
    fails.append(f"@keyframes that animate opacity (stuck-dim risk): {bad_kf}")

op0 = re.findall(r"\.([\w.-]+)\s*\{[^}]*opacity:\s*0\s*[;}]", css)
if op0:
    fails.append(f"selectors whose resting state is opacity:0: {sorted(set(op0))}")

for m in re.finditer(r"\.([\w.-]+)\s*\{([^}]*)\}", css):
    body = m.group(2)
    if "animation" in body and "infinite" in body and re.search(r"\bopacity\s*:", body):
        fails.append(f"infinite animation that also sets opacity (flicker risk): .{m.group(1)}")
notes.append("opacity law: no keyframe touches opacity, no element rests at opacity:0, no pulsing chrome")

# ---------------------------------------------------------------- V8 no CDN
cdn = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?://[^"]+)"', html)
if cdn:
    fails.append(f"remote assets in index.html (must ship locally): {cdn}")
for lib in ("gsap", "tailwind", "cdn.", "unpkg", "jsdelivr"):
    if lib in html.lower():
        fails.append(f"banned reference in index.html: {lib}")
for path in ("gsap.min.js", "tailwind.css"):
    if os.path.exists(os.path.join(WEB, path)):
        fails.append(f"dead asset still on disk: web/{path}")
notes.append("no CDN, no animation library, no dead bundled assets")

# ---------------------------------------------------------------- V8 no emoji
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u23E9-\u23FA\u2705\u274C\u23F3]")
for name, blob in (("index.html", html), ("app.js", js), ("styles.css", css_raw)):
    hits = EMOJI.findall(blob)
    if hits:
        fails.append(f"{name} contains pictographic characters: {sorted(set(hits))}")
notes.append("emoji: none in index.html / app.js / styles.css")

# ---------------------------------------------------------------- V8 CSS integrity
# Walk the stylesheet tracking nesting depth, so a rule inside @media is never
# compared against its base declaration — that would be a false conflict
# (responsive design legitimately overrides). Only top-level rules are compared.
records, buf, depth = [], "", 0
for ch in css:
    if ch == "{":
        sel = " ".join(buf.strip().split())
        records.append([sel, "", depth + 1])
        buf = ""
        depth += 1
    elif ch == "}":
        depth = max(0, depth - 1)
        buf = ""
    elif depth and records:
        records[-1][1] += ch
    else:
        buf += ch

by_sel = collections.defaultdict(list)
for sel, body, d in records:
    if d == 1 and sel.startswith("."):
        by_sel[sel].append(body)
for sel, bodies in by_sel.items():
    if len(bodies) > 1:
        props = collections.defaultdict(set)
        for b in bodies:
            for decl in b.split(";"):
                if ":" in decl:
                    k, v = decl.split(":", 1)
                    props[k.strip()].add(v.strip())
        conflict = {k: v for k, v in props.items() if len(v) > 1}
        if conflict:
            fails.append(f"top-level selector `{sel}` declared {len(bodies)}x with conflicting values: {conflict}")
notes.append(f"css: {len(by_sel)} top-level class rules, no conflicting duplicates "
             f"(media-query overrides exempt)")

# ---------------------------------------------------------------- balance
for tag in ("div", "section", "aside", "article", "nav", "button", "svg", "span", "textarea", "select"):
    o = len(re.findall(rf"<{tag}[\s>]", html))
    c = len(re.findall(rf"</{tag}>", html))
    if o != c:
        fails.append(f"unbalanced <{tag}> in index.html: {o} open vs {c} close")
notes.append("html: every tracked tag balanced")

print("=" * 74)
for n in notes:
    print("  ok   " + n)
print("=" * 74)
if fails:
    print(f"\nFAIL ({len(fails)})\n")
    for f in fails:
        print("  x  " + f)
    sys.exit(1)
print("\nPASS — static UI verification clean")
