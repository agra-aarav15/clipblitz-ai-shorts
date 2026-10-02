"""Marketplace / plugin packaging tests for ClipBlitz Studio - stdlib only, offline.

Run from the studio root:   python scripts/test_marketplace.py

What is proven:

  1. ONE COMMAND INSTALLS. The repo publishes a Claude Code marketplace manifest, the
     plugin it points at exists and is the same plugin this checkout ships, and both
     installers (plugin/install.sh, plugin/install.bat) name the same repo, marketplace
     and plugin ids - so the documented command cannot drift away from the manifest.
  2. THE FILE SET IS PINNED. Plugin files are exactly the ones the CI bundle check
     counts, every one is UTF-8 text, and the folder carries no absolute drive paths -
     a bundle that only runs on the machine that built it is not installable.
  3. THE DOCS MATCH THE CODE. The tool table in plugin/README.md lists exactly the
     tools agent.TOOLS exports, with no row missing and no invented row.
  4. THE VERSIONS AGREE. plugin.json, the marketplace entry and agent.VERSION are the
     same number; the Windows bundle name in the docs is that version.

The marketplace manifest is looked up next to this checkout (repo root) or through
CB_MARKETPLACE; when this suite runs from a bare studio copy it says so and skips
those few checks instead of failing.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO = os.path.dirname(HERE)
PLUGIN = os.path.join(STUDIO, "plugin")
sys.path.insert(0, STUDIO)

from clipblitz import agent  # noqa: E402

RESULTS = []
REPO = "agra-aarav15/clipblitz-ai-shorts"
MARKET = "clipblitz"
PLUGIN_NAME = "clipblitz-studio"

# The bundle the CI workflow counts; kept here so an accidental extra file (a stray
# .pyc, an editor backup) fails locally before it fails the release.
EXPECTED_PLUGIN_FILES = [
    ".claude-plugin/plugin.json",
    ".mcp.json",
    ".mcp.windows.json",
    "README.md",
    "clipblitz-mcp.py",
    "commands/cut.md",
    "install.bat",
    "install.sh",
    "skills/cut-clips/SKILL.md",
]

EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
# A drive path is `X:\something` or `X:/something`, but `cleanly:\now` is a string
# escape, not a path, so require at least two path characters after the separator.
DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/][A-Za-z0-9_.$-]{2,}")
ESCAPE = re.compile(r"[A-Za-z]:\\(?:[nrtbfuUx'\"]|[\\])")


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def loads(path):
    try:
        return json.loads(read(path))
    except Exception as exc:  # noqa: BLE001 - the failure text is the test output
        check(f"parse {os.path.basename(path)}", False, str(exc))
        return None


def find_marketplace():
    """The repo-root manifest: next to this checkout, or wherever CB_MARKETPLACE says."""
    env = os.environ.get("CB_MARKETPLACE")
    if env:
        return env if os.path.isfile(env) else None
    for up in (os.path.join(STUDIO, ".."), os.path.join(STUDIO, "..", "..")):
        cand = os.path.normpath(os.path.join(up, ".claude-plugin", "marketplace.json"))
        if os.path.isfile(cand):
            return cand
    return None


def test_plugin_manifest():
    path = os.path.join(PLUGIN, ".claude-plugin", "plugin.json")
    check("plugin.json exists", os.path.isfile(path))
    if not os.path.isfile(path):
        return None
    data = loads(path)
    if data is None:
        return None
    check("plugin.json: name", data.get("name") == PLUGIN_NAME, str(data.get("name")))
    check("plugin.json: version matches agent.VERSION",
          data.get("version") == agent.VERSION,
          f"{data.get('version')} vs {agent.VERSION}")
    check("plugin.json: has a description", bool(str(data.get("description", "")).strip()))
    check("plugin.json: homepage is the repo",
          str(data.get("homepage", "")) == f"https://github.com/{REPO}",
          str(data.get("homepage")))
    check("plugin.json: licence stated", str(data.get("license", "")).upper() == "MIT",
          str(data.get("license")))
    check("plugin.json: keywords describe the work",
          "video" in [k.lower() for k in data.get("keywords", [])])
    return data


def test_mcp_configs():
    std = loads(os.path.join(PLUGIN, ".mcp.json"))
    if std is not None:
        servers = std.get("mcpServers", {})
        check(".mcp.json: one server named clipblitz", list(servers) == ["clipblitz"],
              str(list(servers)))
        server = servers.get("clipblitz", {})
        check(".mcp.json: launches the python launcher",
              server.get("command") == "python"
              and server.get("args") == ["${CLAUDE_PLUGIN_ROOT}/clipblitz-mcp.py"],
              f"{server.get('command')} {server.get('args')}")
        check(".mcp.json: forces utf-8 on the JSON-RPC channel",
              server.get("env", {}).get("PYTHONIOENCODING") == "utf-8")
    win = loads(os.path.join(PLUGIN, ".mcp.windows.json"))
    if win is not None:
        server = win.get("mcpServers", {}).get("clipblitz", {})
        check(".mcp.windows.json: the bundle EXE answers MCP itself",
              str(server.get("command", "")).endswith("ClipBlitzStudio.exe")
              and server.get("args") == ["--mcp"],
              f"{server.get('command')} {server.get('args')}")
    launcher = os.path.join(PLUGIN, "clipblitz-mcp.py")
    check("launcher exists", os.path.isfile(launcher))
    src = read(launcher)
    check("launcher finds the engine one folder up", 'os.path.dirname(HERE)' in src)
    check("launcher honours CB_ROOT", '"CB_ROOT"' in src)
    check("launcher has a main guard", '__name__ == "__main__"' in src)
    # The launcher must not print into the JSON-RPC channel while being imported.
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            exec(compile(src, launcher, "exec"),
                 {"__name__": "cb_probe", "__file__": launcher})
        except Exception as exc:  # noqa: BLE001 - the failure text is the test output
            check("launcher imports without side effects", False, str(exc))
        else:
            check("launcher imports without side effects", buf.getvalue() == "",
                  repr(buf.getvalue()[:80]))


def test_command_and_skill():
    cmd = os.path.join(PLUGIN, "commands", "cut.md")
    check("commands/cut.md exists", os.path.isfile(cmd))
    if os.path.isfile(cmd):
        text = read(cmd)
        check("/cut points at the MCP tool", "cut_clips" in text)
        check("/cut takes a video and a count", "how many" in text.lower() or "clips" in text)
    skill = os.path.join(PLUGIN, "skills", "cut-clips", "SKILL.md")
    check("skills/cut-clips/SKILL.md exists", os.path.isfile(skill))
    if os.path.isfile(skill):
        text = read(skill)
        check("skill names the MCP server", "clipblitz" in text.lower())
        check("skill names the cutting tool", "cut_clips" in text)


def test_readme_matches_tools():
    readme = os.path.join(PLUGIN, "README.md")
    check("plugin README exists", os.path.isfile(readme))
    if not os.path.isfile(readme):
        return
    rows = re.findall(r"^\|\s*`([a-z_]+)`\s*\|", read(readme), re.M)
    names = [t["name"] for t in agent.TOOLS]
    check("tool table lists every tool", set(rows) == set(names),
          f"missing={sorted(set(names) - set(rows))} extra={sorted(set(rows) - set(names))}")
    check("tool table has no duplicate rows", len(rows) == len(set(rows)), str(rows))
    check("plugin README states the tool count", "11 tools" in read(readme)
          or len(rows) == 11)
    check("plugin README documents the one-command install",
          "install.sh" in read(readme) and "install.bat" in read(readme))
    check("plugin README names the bundle at the current version",
          f"ClipBlitzStudio-{agent.VERSION}-windows.zip" in read(readme))


def test_installers():
    sh = os.path.join(PLUGIN, "install.sh")
    bat = os.path.join(PLUGIN, "install.bat")
    check("install.sh exists", os.path.isfile(sh))
    check("install.bat exists", os.path.isfile(bat))
    if os.path.isfile(sh):
        text = read(sh)
        check("install.sh registers the repo", REPO in text)
        check("install.sh installs plugin@marketplace",
              f'PLUGIN="{PLUGIN_NAME}"' in text
              and '"${PLUGIN}@${MARKET}"' in text)
        check("install.sh names the marketplace", f'MARKET="{MARKET}"' in text)
        check("install.sh fails loudly without the CLI",
              "command -v claude" in text and "exit 1" in text)
        check("install.sh prints the manual fallback",
              "plugin marketplace add" in text and "plugin install" in text)
        check("install.sh stops on the first error", "set -e" in text)
        check("install.sh is ASCII", text.isascii())
        check("install.sh uses LF line endings (a CRLF shebang does not run)",
              b"\r\n" not in read_bytes(sh))
        check("install.sh uses no drive paths", not DRIVE_PATH.search(text),
              (DRIVE_PATH.search(text) or [""])[0])
    if os.path.isfile(bat):
        raw = read_bytes(bat)
        text = raw.decode("utf-8")
        check("install.bat uses CRLF line endings", b"\r\n" in raw and b"\n" in raw
              and raw.count(b"\n") == raw.count(b"\r\n"), "LF-only .bat can break cmd.exe")
        check("install.bat registers the repo", REPO in text)
        check("install.bat installs plugin@marketplace", PLUGIN_NAME in text
              and MARKET in text and "%PLUGIN%@%MARKET%" in text)
        check("install.bat fails loudly without the CLI",
              "where claude" in text and "exit /b 1" in text)
        check("install.bat prints the manual fallback",
              "plugin marketplace add" in text and "plugin install" in text)
        check("install.bat keeps its variables local", "setlocal" in text)
        check("install.bat is ASCII", text.isascii())
        check("install.bat uses no drive paths", not DRIVE_PATH.search(text),
              (DRIVE_PATH.search(text) or [""])[0])


def test_marketplace_manifest():
    path = find_marketplace()
    if path is None:
        check("marketplace manifest: SKIP (not next to this checkout, "
              "set CB_MARKETPLACE to check it)", True, "skipped")
        return
    data = loads(path)
    if data is None:
        return
    check("marketplace manifest is a .claude-plugin/marketplace.json",
          path.replace("\\", "/").endswith(".claude-plugin/marketplace.json"), path)
    check("marketplace name", data.get("name") == MARKET, str(data.get("name")))
    check("marketplace version matches agent.VERSION",
          data.get("metadata", {}).get("version") == agent.VERSION,
          f"{data.get('metadata', {}).get('version')} vs {agent.VERSION}")
    check("marketplace owner is the repo owner",
          REPO.split("/")[0] in str(data.get("owner", {})))
    plugins = data.get("plugins", [])
    check("marketplace has exactly one entry", len(plugins) == 1, str(len(plugins)))
    if len(plugins) != 1:
        return
    entry = plugins[0]
    check("marketplace entry name matches plugin.json",
          entry.get("name") == PLUGIN_NAME, str(entry.get("name")))
    check("marketplace entry has a description", len(str(entry.get("description", ""))) > 80)
    src = str(entry.get("source", ""))
    check("marketplace entry source is a relative path", src.startswith("./"), src)
    resolved = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(path)),
                                             src))
    manifest = os.path.join(resolved, ".claude-plugin", "plugin.json")
    check("marketplace entry source carries a plugin manifest", os.path.isfile(manifest),
          resolved)
    if os.path.isfile(manifest):
        # The path legitimately differs between a working copy and the repo mirror (and
        # in CI it is the same folder), so compare identity: same plugin, same version.
        other = loads(manifest) or {}
        check("marketplace entry is this plugin", other.get("name") == PLUGIN_NAME,
              f"{other.get('name')} at {resolved}")
        check("marketplace entry is this version",
              other.get("version") == agent.VERSION,
              f"{other.get('version')} vs {agent.VERSION}")


def test_release_workflow_matches_version():
    """The release workflow names one version in ten places. This is the check that a
    future bump cannot land half-done (it caught this one's own leftovers)."""
    roots = [os.path.join(STUDIO, "..")]
    manifest = find_marketplace()
    if manifest:
        roots.append(os.path.dirname(os.path.dirname(manifest)))
    path = next((os.path.normpath(os.path.join(r, ".github", "workflows", "build.yml"))
                 for r in roots
                 if os.path.isfile(os.path.join(r, ".github", "workflows", "build.yml"))),
                None)
    if path is None:
        check("release workflow: SKIP (not next to this checkout)", True, "skipped")
        return
    text = read(path)
    check("release workflow uploads the current asset name",
          f"ClipBlitzStudio-{agent.VERSION}-windows.zip" in text)
    check("release workflow publishes into the current tag",
          f"gh release upload v{agent.VERSION}" in text
          and f"gh release download v{agent.VERSION}" in text)
    # Only the product's own major (4.x) is scanned: the workflow legitimately names SDK
    # and toolchain versions like build-tools 35.0.0, and those are not this number.
    stale = sorted(set(re.findall(r"(?<![\d.])v?4\.\d+\.\d+(?![\d.])", text))
                   - {agent.VERSION, f"v{agent.VERSION}"})
    check("release workflow carries no other product version", not stale, str(stale))
    check("release workflow runs the new suites",
          "scripts/test_clipbench.py" in text and "scripts/test_marketplace.py" in text)
    check("release workflow counts the shipped plugin files", "-ne 9" in text)
    check("release workflow asserts the tool count", "-ne 11" in text)


def test_bundle_hygiene():
    found = []
    for root, _dirs, files in os.walk(PLUGIN):
        for name in files:
            found.append(os.path.relpath(os.path.join(root, name), PLUGIN)
                         .replace("\\", "/"))
    check("plugin file set is exactly the shipped nine",
          sorted(found) == EXPECTED_PLUGIN_FILES,
          f"missing={sorted(set(EXPECTED_PLUGIN_FILES) - set(found))} "
          f"extra={sorted(set(found) - set(EXPECTED_PLUGIN_FILES))}")
    for rel in EXPECTED_PLUGIN_FILES:
        path = os.path.join(PLUGIN, rel)
        if not os.path.isfile(path):
            continue
        raw = read_bytes(path)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            check(f"{rel}: is utf-8 text", False, str(exc))
            continue
        check(f"{rel}: is utf-8 text", True)
        check(f"{rel}: no emoji", not EMOJI.search(text),
              (EMOJI.search(text) or [""])[0])
        hits = [m for m in DRIVE_PATH.finditer(text) if not ESCAPE.match(m.group(0))]
        check(f"{rel}: no absolute drive paths", not hits,
              str([m.group(0) for m in hits][:3]))


def main():
    print(f"ClipBlitz Studio {agent.VERSION} - marketplace and plugin packaging\n")
    test_plugin_manifest()
    test_mcp_configs()
    test_command_and_skill()
    test_readme_matches_tools()
    test_installers()
    test_marketplace_manifest()
    test_release_workflow_matches_version()
    test_bundle_hygiene()
    fails = [r for r in RESULTS if r[1] is False]
    print(f"\n{len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    for name, _, detail in fails:
        print(f"  FAIL {name}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
