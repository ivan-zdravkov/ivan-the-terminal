# iPhone: ring and Health data to the private repo, with no hands

The goal is to need as little from you as possible.
- You never open the ring app on purpose or tap a shortcut.
- At most a few times a day, the ring app pops up by itself for a moment. You go back to what you were doing.

**What happens:**
1. **Wake the ring:** a silent "Health sync" shortcut runs when you open an app you use every day anyway. If the ring app hasn't been opened for 6 hours, the shortcut opens it for you. That's what makes the ring sync: most ring apps only pull data from the ring while they're open, so data otherwise waits for days. You go straight back (tap **◀ <app>** at the top left, or swipe up to the home screen). The shortcut keeps running and waits a minute while the ring app finishes in the background.
2. **Health → repo:** the shortcut then commits the last day of Health samples as one small file into the private repo through the GitHub API. It stops itself if it already ran in the last 2 hours.
3. **Repo → plan:** the PC fetches the repo every 15 min in the morning. Once last night's sleep is there, it makes the plan and emails it.

The PC can be off: the files wait in the repo. Re-sending overlapping data is harmless, because the importer ignores duplicate samples.

iOS only lets anything read Health while the phone is **unlocked**. That's why the triggers are "app opened" and never a time of day.

## 0. Once: let the ring app finish in the background
- Health → profile → Apps → <ring app> → turn on every category.
- Settings → General → Background App Refresh → on, and on for the ring app.
- Settings → <ring app>: allow Bluetooth.
- When it pops up, **leave** it (◀ back link or swipe up to home); don't **close** it. Flicking its card away in the app switcher force-quits it, which stops the sync, and iOS won't wake a force-quit app in the background either.
- The first time, or after days without a sync, keep it open until it says it's synced: a big backlog can take a few minutes.

In Health → Browse, check which types the ring actually writes. Temperature and HRV vary by ring.

## 1. A GitHub token that can only write to the repo (5 min)
On github.com → Settings → Developer settings → **Fine-grained tokens** → Generate new token:
- Repository access: **Only select repositories** → the private repo (`HEALTH_REPO`'s GitHub repo).
- Permissions: **Contents: Read and write**. Nothing else.
- Expiration: 1 year. Put a reminder in your calendar to renew it.

Keep the token only inside the shortcut. GitHub can't limit a token to one folder, so anyone who has it can change anything in that repo. Revoke it on GitHub if the phone is lost.

## 2. The "Health sync" shortcut (about 20 minutes to build)
In Shortcuts, tap **+** and name it **Health sync**. The two time checks use small files in the Shortcuts folder (Files → iCloud Drive → Shortcuts).

**Skip if it ran in the last 2 hours:**
1. **Get File** from the Shortcuts folder, path `health-sync-last.txt`. Turn off *Error If Not Found*.
2. **If** *File* has any value:
   - **Get Dates from Input** → *File*.
   - **Get Time Between Dates**: *Dates* and *Current Date*, in **Minutes**.
   - **If** *Time Between Dates* is less than **120** → **Stop This Shortcut**. End If.

   End If.

**Wake the ring app, at most every 6 hours:**

3. **Text** `yes`, then **Set Variable** `wake` to *Text*.
4. **Get File** from the Shortcuts folder, path `ring-opened-last.txt`. Turn off *Error If Not Found*.
5. **If** *File* has any value:
   - **Get Dates from Input** → *File*.
   - **Get Time Between Dates**: *Dates* and *Current Date*, in **Minutes**.
   - **If** *Time Between Dates* is less than **360** → **Text** `no` → **Set Variable** `wake` to *Text*. End If.

   End If.
6. **If** `wake` is `yes`:
   - **Open App** → <ring app>.
   - **Wait** **60** seconds. This is the time the ring app gets to pull from the ring and write to Health. You can leave it after a second or two; the shortcut keeps waiting in the background.
   - **Save File**: *Current Date* to the Shortcuts folder as `ring-opened-last.txt`, **Overwrite If File Exists** on.

   End If.

**Collect the samples:**

7. **Find Health Samples** where *Type* is *Sleep Analysis* and *Start Date* is in the last *30 hours*. Sort by Start Date, no limit. Then **Set Variable** `samples` to *Health Samples*.
8. For each type below, add **Find Health Samples** and then **Add to Variable** `samples`:
   - *Start Date* in the last *30 hours*: Heart Rate Variability · Resting Heart Rate · Oxygen Saturation · Respiratory Rate · Body Temperature (and/or Wrist Temperature)
   - Body Mass: last *7 days*
   - Heart Rate: last *10 hours* only (the ring logs a lot of it)
   - Steps: last *2 days*, **Group By: Day** (one daily total instead of hundreds of samples)
9. **Repeat with Each** item in `samples`, containing one **Text** action:
   `Type|Start Date|End Date|Value|Unit|Source`
   - Insert each field as *Repeat Item* → tap it → pick the property (Type, Start Date, …).
   - For both dates, set **Date Format: ISO 8601** and turn on **Include ISO 8601 Time**.
   - Keep the `|` between fields.
10. **Combine Text** → *Repeat Results* with *New Lines*.

**Commit it to the repo:**

11. **Base64 Encode** *Combined Text* (Line Breaks: **None**).
12. **Format Date** *Current Date* → Custom: `yyyy/MM/yyyy-MM-dd_HHmmss`.
13. **Get Contents of URL**:
    - URL: `https://api.github.com/repos/<owner>/<repo>/contents/health/` + *Formatted Date* + `.txt` (`health` is `HEALTH_DIR`).
    - Method **PUT**.
    - Headers: `Authorization` = `Bearer <token>`, `Accept` = `application/vnd.github+json`, `X-GitHub-Api-Version` = `2022-11-28`.
    - Request Body **JSON** with two Text fields: `message` = `health sync`, `content` = *Base64 Encoded*.
14. **Get Dictionary Value** for `commit` in *Contents of URL*. **If** it has any value → **Save File**: *Current Date* to the Shortcuts folder as `health-sync-last.txt`, **Overwrite If File Exists** on. End If.

If the upload failed, nothing is saved, so the next trigger tries again.

Run it once by hand.
- Allow Health access for every type it asks about, and allow it to open the ring app and connect to api.github.com.
- The ring app should pop up, and about a minute later a new file should appear in the repo under `health/<year>/<month>/`.

## 3. Automations (Shortcuts → Automation → +)
Make one **App** automation: **Is Opened**, with every app you open daily anyway, e.g. Messages, Viber/WhatsApp, Mail, your browser, Instagram. → Health sync.
- Set it to **Run Immediately** and turn off **Notify When Run**.
- The two time checks keep it quiet: at most one upload every 2 hours, and the ring app at most every 6 hours (so usually once in the morning, once in the afternoon and once in the evening).
- Don't add the ring app itself to the list: opening it from the shortcut would trigger the automation again.

Skip triggers that fire while the phone is locked (alarm, charger, time of day). Health is locked then, so they send nothing.

## On the PC
- `itt run daily-coach --import` fetches the repo and shows what arrived.
- `itt run daily-coach --dry-run` shows the last import, the samples per type (look for `UNKNOWN type` lines), last night and whether the plan is ready.

## Troubleshooting
- **No new files in the repo:** check that the automation is on and set to Run Immediately. Run Health sync by hand to see the error.
  - A `401` or `404` in the result means the token expired, or it can't see the repo.
  - Delete `health-sync-last.txt` in Files → Shortcuts to force the next run.
- **The ring app pops up too often:** raise **360** in step 5 (e.g. 720 for twice a day). **Too rarely** or the morning plan misses last night: lower it.
- **The ring app opened, but last night is still missing in the plan:**
  - The ring needs more time. Raise the **Wait** in step 6 to 90-120 seconds, or stay in the ring app until it says synced. A backlog of several days takes minutes.
  - The ring was out of Bluetooth range, e.g. on the charger in another room.
  - Or the app was force-quit (step 0).
  - Data that arrives late goes out with the next upload, 2 hours later at most. The plan waits for it until 10:30.
- **Files arrive, but `bad` > 0 in `--import`:** the dates aren't ISO 8601 (step 9), or a field is missing.
- **New types shown as `UNKNOWN` in `--dry-run`:** the phone language names them differently. Add the name to `METRICS` in `coach.py`.
