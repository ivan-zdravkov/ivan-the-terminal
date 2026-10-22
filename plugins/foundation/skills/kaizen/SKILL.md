---
name: kaizen
description: Continuous-improvement pass over the ivan-the-terminal setup - find what in public or private skills, docs, scripts, memory and guards should improve after a task or a casual session, apply small fixes now, log bigger ones. Use at the end of any substantial task, or when Ivan says "retro", "let's improve", "what did we learn", or a skill was missing, wrong or clumsy.
---

# Kaizen

1. **Scan the session.** Look at: skills used, skills that should have existed, steps repeated by hand, errors and their fixes, facts learned, and anything Ivan corrected.
2. **Route each item:**
   - fact about Ivan, family, devices or setup → memory or `~/Repositories/ivan-the-terrible/profile/` (private)
   - repeatable procedure → a new or updated skill: generic → public plugin; personal → `~/Repositories/ivan-the-terrible/skills/`
   - doc, script or skill bug → fix it
   - leak-guard gap → leakguard rule + test (public) or `bin/denylist-add` (private)
   - token waste (long output, re-reading files) → make the script terser or split the skill into `references/`
3. **Small (≈15 min or less): do it now.** Public changes go through the ship-public skill; private changes are committed and pushed in ivan-the-terrible.
4. **Bigger:** append to `~/Repositories/ivan-the-terrible/backlog.md`:
   `- [ ] YYYY-MM-DD <plugin/area>: <what> (why: <evidence from the session>)`
5. **Report** in at most 3 lines: what changed and what got logged. Skip the pass silently if nothing qualifies.
