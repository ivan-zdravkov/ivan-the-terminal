# Security

## Reporting

Found something sensitive in this repo, or a weakness in the guards? Email **ivan@zdravkov.dev** or use GitHub's private vulnerability reporting. Please don't open a public issue.

## Data classification

| Tier | Lives in | Rule |
|---|---|---|
| 0 public | this repo | Generic and reusable. Placeholders only. |
| 1 private | private overlay repo | Anything identifying a person, place, device, network, account or employer |
| 2 secret | overlay, sops+age encrypted | Credentials, keys, tokens. Never plaintext in any git repo |

Placeholders: `~` / `$HOME` for paths, `192.0.2.0/24` (RFC 5737) for IPs, `example.com` for domains and emails, `<tablet-serial>`-style tokens for identifiers. Skills read the real values at runtime from `~/.config/ivan-the-terminal/`.

## Threat model

| Threat | Mitigation |
|---|---|
| Claude (or I) paste a personal value into a public file | PreToolUse hook, pre-commit, CI. All three run leakguard against the denylist |
| A personal value in a commit message or PR text | commit-msg hook; the Claude hook on `gh` commands; CI scans PR title/body |
| A value added then removed inside one PR (still in history) | pre-push and CI scan **every commit**, not just the final diff |
| Pushed branch = published, even if never merged | all gates run locally before the first push; `pre-push` is the last one |
| Credentials | gitleaks (local + CI, full history), GitHub secret scanning + push protection |
| Photo metadata (GPS) | leakguard rejects images that carry EXIF |
| The denylist itself leaking | it lives only in the private repo and an encrypted Actions secret. Secrets in it are sha256 hashes, and CI output is redacted |
| Compromised CI dependency | actions pinned by commit SHA, gitleaks binary checksum-verified, `contents: read` token, Dependabot for updates |
| Direct pushes / force pushes to `main` | branch protection (admins included), linear history, local pre-push refusal |
| A PR neutering its own guard (edits leakguard, allowlist or gitleaks config) | CI runs leakguard, `.leakguard-allow` and `.gitleaks.toml` from the **base branch**, and ignores PR-supplied `.gitleaksignore` |
| Fork PRs (no access to the denylist secret) | workflows need approval for outside contributors; fork PRs are reviewed and merged by hand (auto-merge is only for my own branches); the push to `main` re-scans against the denylist |
| Hidden content: renames, binary/UTF-16 files, `-diff` attributes, merge commits | leakguard scans file names, forces text diffs, decodes UTF-16, extracts strings from binaries for the denylist, and diffs merges against the first parent |
| Office/PDF/video files (author, GPS and device metadata) | rejected by default; publish Markdown, or strip metadata and allowlist the path |
| Hook bypass by Claude | the Claude hook blocks `git commit/push --no-verify` and `git commit -n`, and scans every file a `gh` command could upload |

Known limits: leakguard is pattern-based. It can't recognise a personal fact that isn't on the denylist, like a new club name. So `/security-review` and a human read remain part of the flow. Hashed denylist entries match exact (sub)tokens, case-sensitively. IPv6 isn't parsed beyond Tailscale's range.

## If something leaks

1. **Rotate first.** Treat any exposed credential as compromised: revoke or rotate it, then encrypt the new one into the overlay.
2. Remove it from the tree via a normal PR.
3. History: this repo doesn't rewrite history, **except** to purge leaked personal data or credentials. Then: `git filter-repo`, temporarily lift branch protection, force-push, restore protection.
4. Ask GitHub Support to purge cached views and `refs/pull/*`, since PR refs survive force-pushes.
5. Add the leaked value to the denylist so it can never return.
