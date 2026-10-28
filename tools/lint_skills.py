#!/usr/bin/env python3
"""Validate marketplace, plugin manifests and SKILL.md frontmatter. Silent on success."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_DESCRIPTION = 400  # always in context: keep it a sharp what + when
MAX_BODY_LINES = 80    # details belong in references/ or scripts/
SEMVER = re.compile(r"\d+\.\d+\.\d+")
errors = []

market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
listed = {p["name"]: p["source"] for p in market["plugins"]}
for plugin_dir in sorted((ROOT / "plugins").iterdir()):
    manifest = plugin_dir / ".claude-plugin/plugin.json"
    if not manifest.is_file():
        errors.append(f"{plugin_dir.name}: missing .claude-plugin/plugin.json")
        continue
    plugin = json.loads(manifest.read_text())
    name = plugin["name"]
    if not SEMVER.fullmatch(plugin.get("version", "")):
        errors.append(f"{name}: plugin.json version must be MAJOR.MINOR.PATCH")
    skills = sorted((plugin_dir / "skills").glob("*/SKILL.md"))
    if listed.get(name) != f"./plugins/{plugin_dir.name}":
        errors.append(f"{name}: not listed in marketplace.json with source ./plugins/{plugin_dir.name}")
    for skill in skills:
        text = skill.read_text()
        m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
        where = skill.relative_to(ROOT)
        if not m:
            errors.append(f"{where}: missing frontmatter")
            continue
        meta = dict(re.findall(r"^(\w[\w-]*):\s*(.+)$", m.group(1), re.M))
        if meta.get("name") != skill.parent.name:
            errors.append(f"{where}: name '{meta.get('name')}' must equal directory '{skill.parent.name}'")
        if not 40 <= len(meta.get("description", "")) <= MAX_DESCRIPTION:
            errors.append(f"{where}: description must be 40-{MAX_DESCRIPTION} chars")
        if len(m.group(2).splitlines()) > MAX_BODY_LINES:
            errors.append(f"{where}: body over {MAX_BODY_LINES} lines; move detail to references/")
        # One version everywhere: SKILL.md metadata.version (claude.ai zip), the changelog's top entry, and
        # plugin.json (Claude Code) when the plugin holds just this skill. Required once a skill has a changelog.
        version = re.search(r'^metadata:\n(?:[ \t]+.*\n)*?[ \t]+version:\s*"?([^"\s]+)"?', m.group(1) + "\n", re.M)
        version = version and version.group(1)
        changelog = skill.parent / "CHANGELOG.md"
        if changelog.is_file():
            top = re.search(r"^## \[([^\]]+)\]", changelog.read_text(), re.M)
            if not version:
                errors.append(f"{where}: has CHANGELOG.md but no metadata.version")
            elif not top or top.group(1) != version:
                errors.append(f"{where}: metadata.version {version} is not the top CHANGELOG.md entry")
        if version and not SEMVER.fullmatch(version):
            errors.append(f"{where}: metadata.version must be MAJOR.MINOR.PATCH")
        if version and len(skills) == 1 and plugin.get("version") != version:
            errors.append(f"{where}: metadata.version {version} differs from plugin.json {plugin.get('version')}")
        for ref in re.findall(r"`((?:references|scripts)/[^`\s]+)`", m.group(2)):
            if not (skill.parent / ref).exists():
                errors.append(f"{where}: references missing file {ref}")

for e in errors:
    print("lint_skills: " + e, file=sys.stderr)
sys.exit(1 if errors else 0)
