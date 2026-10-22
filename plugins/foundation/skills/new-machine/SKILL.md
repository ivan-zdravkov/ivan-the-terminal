---
name: new-machine
description: Set up or migrate the ivan-the-terminal environment onto a fresh Linux machine, or repair a broken one - toolchain, GitHub SSH auth, both repos, age key, overlay links, skills and memory. Use when moving to a new PC, after a reinstall or rebase, or when doctor reports missing links.
---

# New machine

The only thing that travels outside git is the **age key**. Everything else comes from the two repos.

1. Prerequisites: Homebrew (preinstalled on Bazzite / Universal Blue; else https://brew.sh) and git.
2. Auth: `brew install gh` then `gh auth login -p ssh -w`. Ivan runs this himself; it's interactive. Use an SSH key **with a passphrase**.
3. Clone: `gh repo clone ivan-zdravkov/ivan-the-terminal ~/Repositories/ivan-the-terminal`
4. Age key: Ivan restores it from the offline backup to `~/.config/sops/age/keys.txt`, then `chmod 600`. Without it, secrets stay locked but everything else works.
5. `~/Repositories/ivan-the-terminal/bin/itt bootstrap`. It installs `toolchain.txt`, git hooks, `itt` on PATH and skill links, clones the private overlay (`$ITT_PRIVATE_REPO`, default `<gh-user>/ivan-the-terrible`) and runs its bootstrap (config, memory, private skills).
6. `itt doctor` until green (use the doctor skill).
7. From then on, start Claude in `~/Repositories/ivan-the-terminal` and approve the one-time import of the overlay CLAUDE.md.

Services, timers and app configs (job digest, streaming host, emulators) are installed by their own skills, not here.
To retire the old machine: revoke its SSH key (`gh ssh-key list` / `gh ssh-key delete`) and `gh auth logout`.
