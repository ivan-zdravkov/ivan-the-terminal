# iPhone: ring and Health data to the private repo, with no hands

The goal is to need as little from you as possible.
- You never open the ring app on purpose or tap a shortcut.
- At most a few times a day, the ring app pops up by itself for a moment. You go back to what you were doing.

**What happens:**
1. **Wake the ring:** a silent "Health sync" shortcut runs when you open an app you use every day anyway. If the ring app hasn't been opened for 6 hours, the shortcut opens it for you. That's what makes the ring sync: most ring apps only pull data from the ring while they're open. You go straight back (tap **◀ <app>** at the top left, or swipe up to the home screen). The shortcut keeps running and waits a minute while the ring app finishes in the background.
2. **Health → repo:** the shortcut then commits the last day of Health samples as one small file into the private repo through the GitHub API. It stops itself if it already ran in the last 2 hours.
3. **Repo → plan:** the PC fetches the repo every 15 min in the morning. Once last night's sleep is there, it makes the plan and emails it.

The PC can be off: the files wait in the repo. iOS only lets anything read Health while the phone is **unlocked**, which is why the trigger is "app opened" and never a time of day.

You don't build the shortcut: `scripts/shortcut.py` generates it from `config.env`. Setup is four short steps.

## 1. The ring app (2 min)
- Health → profile → Apps → <ring app> → turn on every category.
- Settings → General → Background App Refresh → on, and on for the ring app. Settings → <ring app>: allow Bluetooth.
- When it pops up, **leave** it (◀ back link or swipe up to home); don't **close** it. Flicking its card away in the app switcher force-quits it, which stops the sync.
- In Health → Browse, check which types have data. The shortcut reads `HEALTH_TYPES` (default: Sleep, Heart Rate, Heart Rate Variability, Blood Oxygen, Steps). A listed type with **no data at all** stops the shortcut, so remove those; add Resting Heart Rate, Respiratory Rate, Body Temperature, Wrist Temperature or Weight if the ring or a scale writes them.

## 2. A GitHub token that can only write to the repo (3 min, on the phone)
In Safari on the iPhone: github.com → Settings → Developer settings → **Fine-grained tokens** → Generate new token.
- Repository access: **Only select repositories** → the private repo (`HEALTH_REPO`'s GitHub repo).
- Permissions: **Contents: Read and write**. Nothing else. Expiration: 1 year.
- Copy it. Making it on the phone means it never has to travel from the PC. Revoke it on GitHub if the phone is lost.

## 3. The shortcut (2 min)
On the PC: `itt run daily-coach --shortcut`. It builds the shortcut, has RoutineHub's HubSign service sign it (iOS only imports signed shortcuts, and Apple's signing tool needs a Mac), and prints where the `.shortcut` file is. The file holds the repo name and the ring app, never the token. Get the file to the phone (mail it to yourself or AirDrop it) and open it there.
- **Add Shortcut**, and paste the token when it asks. It's stored only inside the shortcut.
- Run **Health sync** once by hand in Shortcuts. Allow Health access for every type, opening the ring app, and connecting to api.github.com.
- The ring app pops up. About a minute later a new file appears in the repo under `health/<year>/<month>/`.

## 4. The automation (1 min; iOS can't import these)
Shortcuts → Automation → **+** → **App** → choose apps you open daily anyway (Messages, Viber/WhatsApp, Mail, your browser, Instagram) → **Is Opened** → **Run Immediately** → **Health sync**. Turn off **Notify When Run** if it's offered.
- Don't add the ring app itself: opening it from the shortcut would trigger the automation again.
- Triggers that fire while the phone is locked (alarm, charger, time of day) can't read Health, so they're not used.

To change something later (types, timings), edit `config.env` or `shortcut.py`, rerun `--shortcut` and import it again; it replaces the old one. Don't edit the shortcut on the phone: the next rebuild would undo it.

## On the PC
- `itt run daily-coach --import` fetches the repo and shows what arrived.
- `itt run daily-coach --dry-run` shows the last import, the samples per type (look for `UNKNOWN type` lines), last night and whether the plan is ready.

## Troubleshooting
- **No new files in the repo:** run Health sync by hand in Shortcuts to see the error.
  - It stops at **Find Health Samples**: that type has no data. Remove it from `HEALTH_TYPES` and rebuild.
  - **Get Contents of URL** answers `401` or `404`: the token expired, was mistyped, or can't see the repo. Delete the shortcut and import it again with a new token.
  - Nothing happens: it ran in the last 2 hours. Delete `health-sync-last.txt` in Files → iCloud Drive → Shortcuts to force the next run.
  - Also check that the automation is on and set to Run Immediately.
- **The ring app opened, but last night is still missing in the plan:**
  - The ring needs more time: stay in the ring app until it says synced. A backlog of several days takes minutes.
  - The ring was out of Bluetooth range, e.g. on the charger in another room. Or the app was force-quit (step 1).
  - Data that arrives late goes out with the next upload, 2 hours later at most. The plan waits for it until 10:30.
- **The ring app pops up too often or too rarely:** change `RING_EVERY_MIN` (360) or `RING_WAIT_S` (60) in `shortcut.py`, rebuild and reimport.
- **Files arrive, but `bad` > 0 in `--import`:** a field is missing or a date didn't parse. Look at the file in the repo.
