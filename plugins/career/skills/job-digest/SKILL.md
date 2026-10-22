---
name: job-digest
description: Run, test, tune or debug the weekday job digest - a headless Claude run that searches job feeds/boards, triages recruiter Gmail, drafts replies and cold outreach (never sends), archives job alerts and emails one ranked digest. Use when Ivan asks about the digest, a missing/odd digest, wants to change what it looks for, or asks to run it now.
---

# Job digest

- **Pieces:** `scripts/run` (runner, tool allowlist), `scripts/guard.py` (send/archive guard), `references/prompt.md` (procedure). The private part is `~/.config/ivan-the-terminal/job-digest/{config.env,profile.md}`: who, wants, rates, filters, search terms, signature. A user timer (in the private overlay) runs `itt run job-digest` on weekday mornings.
- **Check config without running:** `itt run job-digest --dry-run`. It should show 0 unfilled placeholders and the guard command.
- **Run now:** `itt run job-digest` (takes minutes; sends the digest). Ask Ivan first, because it creates drafts and sends an email. If a digest already went out today, the run sends an "Update:" digest with only new items.
- **Debug:** logs are in `~/.local/state/ivan-the-terminal/job-digest/logs/`; read the newest. Timer status: `systemctl --user status job-digest.timer job-digest.service`.
- **Tune what it looks for** (rates, stack, boards, queries, conflicts): edit the private `profile.md`, never the public prompt. Change `references/prompt.md` only for generic procedure fixes, and ship those via ship-public.
- **Safety invariants:** never widen the allowlist to sending/replying/forwarding, never remove the guard, never let the digest apply or contact anyone. Outreach is drafts with the "Job Search/Attach CV" label.
