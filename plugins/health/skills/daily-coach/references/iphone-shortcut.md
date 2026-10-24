# iPhone: syncing ring data automatically

iOS has no cloud API for Health, and it only lets anything read Health data while the phone is **unlocked**.
So "automatic" here means: whenever you've just used the ring app, or another app you open every morning.
Every sync is safe to repeat, because the server ignores duplicate samples.
The first sync after AUTO_PLAN_HOUR (06:00), once the night has been over for 20+ min, starts today's plan by itself. A notification arrives a few minutes later.

Before you start, check two things:
- Tailscale is on the phone (VPN On Demand helps).
- The ring app writes to Health: Health → profile → Apps → <ring app> → turn on every category.

In Health → Browse, check which types the ring actually writes. Temperature and HRV vary by ring.

## 1. The "Coach sync" shortcut (silent, about 10 minutes to build)
In Shortcuts, tap **+** and name it **Coach sync**.
1. **Find Health Samples** where *Type* is *Sleep Analysis* and *Start Date* is in the last *36 hours*. Sort by Start Date, no limit.
2. **Set Variable** `samples` to *Health Samples*.
3. For each type below, add **Find Health Samples** (*Start Date* in the last *36 hours*) and then **Add to Variable** `samples`:
   - Heart Rate Variability · Resting Heart Rate · Oxygen Saturation · Respiratory Rate · Body Temperature (and/or Wrist Temperature) · Body Mass
   - Heart Rate: last *12 hours* only (the ring logs a lot of it)
   - Steps: last *3 days*, **Group By: Day** (one daily total instead of hundreds of samples)
4. **Repeat with Each** item in `samples`, containing one **Text** action:
   `Type|Start Date|End Date|Value|Unit|Source`
   - Insert each field as *Repeat Item* → tap it → pick the property (Type, Start Date, …).
   - For both dates, set **Date Format: ISO 8601** and turn on **Include ISO 8601 Time**.
   - Keep the `|` between fields.
5. **Combine Text** → *Repeat Results* with *New Lines*.
6. **Get Contents of URL** → the `sync:` URL that `itt run daily-coach --dry-run` prints (it contains the secret token).
   - Method **POST**, Request Body **JSON**.
   - One field: key `data`, type Text, value *Combined Text*.

Run it once by hand and allow Health access for every type it asks about.

## 2. Automations (Shortcuts → Automation → +)
Set each to **Run Immediately** and turn off **Notify When Run**:
- **App** → <ring app> → **Is Closed** → Coach sync. This is the main one. Look at last night in the ring app (that's what makes it sync to Health), then switch away; the sync runs as you leave.
- **App** → an app you open every morning anyway (Weather, Messages, your browser) → **Is Opened** → Coach sync. This covers mornings when you skip the ring app. The ring syncs to Health in the background less reliably, so the plan may start with partial data. The 10:30 fallback is there either way.

Skip triggers that fire while the phone is locked (alarm stopped, charger, time of day). Health is locked then, so they post nothing.

## 3. Optional: a "Good morning" button
A second shortcut for the Action button, for when you want the plan right away:
1. **Open App** → the ring app.
2. **Wait** 20 seconds.
3. **Run Shortcut** → Coach sync, but with the `morning:` URL. That starts the plan even before AUTO_PLAN_HOUR. The simplest way is to duplicate Coach sync and swap the URL.
4. **Show Notification** → *Contents of URL* (how many samples arrived, and whether the plan is being made).

## The app
Open the `app:` URL in Safari → Share → **Add to Home Screen**. Then open it from the icon and tap **🔔 Notify me**. See `docs/phone-apps.md` in the repo.
It always opens on the newest plan: before today's is ready, it shows yesterday's and switches by itself when the new one lands.

## Troubleshooting
- **`last sync: never` in `--dry-run`:** an automation didn't run. In Shortcuts → Automation, check that it's on and set to Run Immediately. Run Coach sync by hand to see the error.
- **The shortcut errors or times out:** Tailscale is off on the phone, or the server isn't running (`systemctl --user status daily-coach-server`).
- **`bad` > 0:** the dates aren't ISO 8601 (step 4), or a field is missing.
- **No sleep in the plan:** in Health, does last night show data from the ring? Open the ring app once; closing it syncs again.
- **New types shown as `UNKNOWN` in `--dry-run`:** the phone language names them differently. Add the name to `METRICS` in `coach.py`.
