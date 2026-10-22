#!/usr/bin/env python3
"""Validate marketplace, plugin manifests and SKILL.md frontmatter. Silent on success."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_DESCRIPTION = 400  # always in context: keep it a sharp what + when
MAX_BODY_LINES = 80    # details belong in references/ or scripts/
errors = []

market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
listed = {p["name"]: p["source"] for p in market["plugins"]}
for plugin_dir in sorted((ROOT / "plugins").iterdir()):
    manifest = plugin_dir / ".claude-plugin/plugin.json"
    if not manifest.is_file():
        errors.append(f"{plugin_dir.name}: missing .claude-plugin/plugin.json")
        continue
    name = json.loads(manifest.read_text())["name"]
    if listed.get(name) != f"./plugins/{plugin_dir.name}":
        errors.append(f"{name}: not listed in marketplace.json with source ./plugins/{plugin_dir.name}")
    for skill in sorted((plugin_dir / "skills").glob("*/SKILL.md")):
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
        for ref in re.findall(r"`((?:references|scripts)/[^`\s]+)`", m.group(2)):
            if not (skill.parent / ref).exists():
                errors.append(f"{where}: references missing file {ref}")

for e in errors:
    print("lint_skills: " + e, file=sys.stderr)
sys.exit(1 if errors else 0)
