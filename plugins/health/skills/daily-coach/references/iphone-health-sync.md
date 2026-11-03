# iPhone: Health data to the private repo, with no hands

The goal is zero manual syncing: no opening the ring app, no tapping a shortcut.

- **Ring → Health:** the ring app writes to Health whenever iOS lets it run in the background.
- **Health → repo:** a silent "Health sync" shortcut runs whenever you open an app you use every day anyway. It commits the last day of samples as one small file into the private repo through the GitHub API. It stops itself if it already ran in the last 2 hours.
- **Repo → plan:** the PC fetches the repo every 15 min in the morning. Once last night's sleep is there, it makes the plan and emails it.

The PC can be off: the files wait in the repo. Re-sending overlapping data is harmless, because the importer ignores duplicate samples.

iOS only lets anything read Health while the phone is **unlocked**. That's why the triggers are "app opened" and never a time of day.

## 0. Once: the ring app writes to Health in the background
- Health → profile → Apps → <ring app> → turn on every category.
- Settings → General → Background App Refresh → on, and on for the ring app.
- Settings → <ring app>: allow Bluetooth, and don't swipe the app away in the app switcher (iOS won't wake a swiped-away app).

In Health → Browse, check which types the ring actually writes. Temperature and HRV vary by ring.

## 1. A GitHub token that can only write to the repo (5 min)
On github.com → Settings → Developer settings → **Fine-grained tokens** → Generate new token:
- Repository access: **Only select repositories** → the private repo (`HEALTH_REPO`'s GitHub repo).
- Permissions: **Contents: Read and write**. Nothing else.
- Expiration: 1 year. Put a reminder in your calendar to renew it.

Keep the token only inside the shortcut. GitHub can't limit a token to one folder, so anyone who has it can change anything in that repo. Revoke it on GitHub if the phone is lost.

## 2. The "Health sync" shortcut (about 15 minutes to build)
In Shortcuts, tap **+** and name it **Health sync**.

**Skip if it ran in the last 2 hours:**
1. **Get File** from the Shortcuts folder, path `health-sync-last.txt`. Turn off *Error If Not Found*.
2. **If** *File* has any value:
   - **Get Dates from Input** → *File*.
   - **Get Time Between Dates**: *Dates* and *Current Date*, in **Minutes**.
   - **If** *Time Between Dates* is less than **120** → **Stop This Shortcut**. End If.

   End If.

**Collect the samples:**

3. **Find Health Samples** where *Type* is *Sleep Analysis* and *Start Date* is in the last *30 hours*. Sort by Start Date, no limit. Then **Set Variable** `samples` to *Health Samples*.
4. For each type below, add **Find Health Samples** and then **Add to Variable** `samples`:
   - *Start Date* in the last *30 hours*: Heart Rate Variability · Resting Heart Rate · Oxygen Saturation · Respiratory Rate · Body Temperature (and/or Wrist Temperature)
   - Body Mass: last *7 days*
   - Heart Rate: last *10 hours* only (the ring logs a lot of it)
   - Steps: last *2 days*, **Group By: Day** (one daily total instead of hundreds of samples)
5. **Repeat with Each** item in `samples`, containing one **Text** action:
   `Type|Start Date|End Date|Value|Unit|Source`
   - Insert each field as *Repeat Item* → tap it → pick the property (Type, Start Date, …).
   - For both dates, set **Date Format: ISO 8601** and turn on **Include ISO 8601 Time**.
   - Keep the `|` between fields.
6. **Combine Text** → *Repeat Results* with *New Lines*.

**Commit it to the repo:**

7. **Base64 Encode** *Combined Text* (Line Breaks: **None**).
8. **Format Date** *Current Date* → Custom: `yyyy/MM/yyyy-MM-dd_HHmmss`.
9. **Get Contents of URL**:
   - URL: `https://api.github.com/repos/<owner>/<repo>/contents/health/` + *Formatted Date* + `.txt` (`health` is `HEALTH_DIR`).
   - Method **PUT**.
   - Headers: `Authorization` = `Bearer <token>`, `Accept` = `application/vnd.github+json`, `X-GitHub-Api-Version` = `2022-11-28`.
   - Request Body **JSON** with two Text fields: `message` = `health sync`, `content` = *Base64 Encoded*.
10. **Get Dictionary Value** for `commit` in *Contents of URL*. **If** it has any value → **Save File**: *Current Date* to the Shortcuts folder as `health-sync-last.txt`, **Overwrite If File Exists** on. End If.

If the upload failed, nothing is saved, so the next trigger tries again.

Run it once by hand. Allow Health access for every type it asks about, and allow it to connect to api.github.com. A new file should appear in the repo under `health/<year>/<month>/`.

## 3. Automations (Shortcuts → Automation → +)
Make one **App** automation: **Is Opened**, with every app you open daily anyway, e.g. Messages, Viber/WhatsApp, Mail, your browser, Instagram. → Health sync.
- Set it to **Run Immediately** and turn off **Notify When Run**.
- The 2-hour check inside the shortcut keeps this from firing all day.
- Optional: a second automation with the ring app → **Is Closed**. When you do look at the ring app, the fresh data goes out right away.

Skip triggers that fire while the phone is locked (alarm, charger, time of day). Health is locked then, so they send nothing.

## On the PC
- `itt run daily-coach --import` fetches the repo and shows what arrived.
- `itt run daily-coach --dry-run` shows the last import, the samples per type (look for `UNKNOWN type` lines), last night and whether the plan is ready.

## Troubleshooting
- **No new files in the repo:** check that the automation is on and set to Run Immediately. Run Health sync by hand to see the error.
  - A `401` or `404` in the result means the token expired, or it can't see the repo.
  - Delete `health-sync-last.txt` in Files → Shortcuts to force the next run.
- **Files arrive, but `bad` > 0 in `--import`:** the dates aren't ISO 8601 (step 5), or a field is missing.
- **No sleep in the plan:** does last night show data from the ring in Health? If not, the ring app hasn't synced. Open it once, and check Background App Refresh (step 0).
- **New types shown as `UNKNOWN` in `--dry-run`:** the phone language names them differently. Add the name to `METRICS` in `coach.py`.
