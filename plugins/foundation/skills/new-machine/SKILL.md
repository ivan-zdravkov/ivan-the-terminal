---
name: new-machine
description: Set up or migrate the ivan-the-terminal environment onto a fresh Linux or Windows machine, or repair a broken one - toolchain, GitHub SSH auth, both repos, age key, overlay links, skills, memory and Claude history. Use when moving to a new PC, after a reinstall or rebase, or when doctor reports missing links.
---

# New machine

The only things that travel outside git are the **SSH key** and the **age key**. Everything else comes from the two repos.
On Windows, `prep-windows11-installation-iso` with `toolchain` in `APPS` already installed the tools and restored both keys; start at step 2.

1. Prerequisites: git and Python 3. Linux: Homebrew (preinstalled on Bazzite; else https://brew.sh). Windows: winget.
2. Keys:
   - SSH key **with a passphrase** in `~/.ssh/`. Ivan loads it himself, in his own terminal: `ssh-add` (Windows: the OpenSSH agent service keeps it across reboots; Claude's `!` prefix can't prompt for it).
   - Windows: git must use that agent: `git config --global core.sshCommand C:/Windows/System32/OpenSSH/ssh.exe`.
   - age key from the offline backup: `~/.config/sops/age/keys.txt` (`chmod 600`), on Windows `%APPDATA%\sops\age\keys.txt`. Without it, secrets stay locked but everything else works.
3. Auth: `gh auth login -p ssh -w` (Ivan, interactive; skip uploading the key if it's already on GitHub).
4. Clone: `gh repo clone ivan-zdravkov/ivan-the-terminal ~/Repositories/ivan-the-terminal` (any parent dir works; the overlay lands next to it).
5. `python3 <repo>/bin/itt bootstrap`. It installs `toolchain.txt` (brew / winget), git hooks, `itt` on PATH, skill links and the interactive-`claude` wrapper, then clones the private overlay (`$ITT_PRIVATE_REPO`, default `<gh-user>/ivan-the-terrible`) and runs its bootstrap (config, memory, private skills, claude-sync). Open a new terminal afterwards on Windows (PATH changed).
6. Restore Claude history from the overlay: `<overlay>/bin/claude-sync --restore-history`.
7. `itt doctor` until green (use the doctor skill).
8. From then on, `claude` in any terminal starts in ivan-the-terminal (`$env:CLAUDE_HERE=1` / `CLAUDE_HERE=1` to opt out); approve the one-time import of the overlay CLAUDE.md.

Services, timers and app configs (job digest, streaming host, emulators) are installed by their own skills, not here.
To retire the old machine: revoke its SSH key (`gh ssh-key list` / `gh ssh-key delete`) and `gh auth logout`.
