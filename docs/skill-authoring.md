# Skill authoring conventions

Goal: skills that trigger reliably, cost few tokens and never leak.

1. **Description = what + when.** It's always in context, so keep it 1–3 sentences (≤400 chars) with the trigger phrases a user would actually say. The linter enforces this.
2. **Body ≤ 80 lines, imperative.** Steps, decisions and fixes. No background essays.
3. **Scripts over prose.** Deterministic work goes in `scripts/`. Output is problems-only plus one summary line, with `--json` when Claude must parse it. Claude runs a script without reading it, so its source costs nothing.
4. **Progressive disclosure.** Put detail in `references/*.md` and link it from the step that needs it ("if X, read `references/x.md`").
5. **Generic + overlay.** Never hard-code personal values. Read `~/.config/ivan-the-terminal/<skill>.*`, ship a `config.example`, and fail with a clear message when config is missing.
6. **Secrets via sops only.** Use `sops exec-env`. Never put secrets in args, logs or output.
7. **Idempotent and safe.** Re-running is harmless. Destructive steps confirm or dry-run first. Interactive or sudo steps are handed to the user as an exact command.
8. **Headless-ready.** If it can run on a timer, declare the minimal tool allowlist, a guard hook for outbound actions, and log to `~/.local/state/ivan-the-terminal/<skill>/`.
9. **Replace something.** Note which paid or enshittified service the skill makes unnecessary.
10. **Ship through `ship-public`.**
