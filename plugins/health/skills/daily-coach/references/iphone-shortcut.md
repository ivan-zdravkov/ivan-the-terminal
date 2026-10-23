# iPhone: "Good morning" shortcut

One tap when you get up: it nudges the ring app to sync into Health, sends the last ~36 h of samples to the coach server over Tailscale, and starts today's plan. It's free and needs no third-party export app. Build it once, in about 10 minutes.

Before you start: Tailscale is on the phone (VPN On Demand helps), and the ring app writes to Health (Health → profile → Apps → <ring app> → turn on every category). In Health → Browse, check which types the ring actually writes; temperature and HRV vary by ring.

## Build it (Shortcuts → + → name it "Good morning")
1. **Open App** → the ring's app. *(This makes it sync to Health.)*
2. **Wait** → 20 seconds.
3. **Find Health Samples** where *Type* is *Sleep Analysis* and *Start Date* is in the last *36 hours*. Sort by Start Date, no limit.
4. **Set Variable** `samples` to *Health Samples*.
5. For each type below, add **Find Health Samples** (*Start Date* in the last *36 hours*) and then **Add to Variable** `samples`:
   - Heart Rate Variability · Resting Heart Rate · Oxygen Saturation · Respiratory Rate · Body Temperature (and/or Wrist Temperature) · Body Mass
   - Heart Rate: last *12 hours* only (the ring logs a lot of it)
   - Steps: last *3 days*, **Group By: Day** (one daily total instead of hundreds of samples)
6. **Repeat with Each** item in `samples`, containing one **Text** action:
   `Type|Start Date|End Date|Value|Unit|Source`
   Insert each field as *Repeat Item* → tap it → pick the property (Type, Start Date, …). For both dates, set **Date Format: ISO 8601** and turn on **Include ISO 8601 Time**. Keep the `|` between fields.
7. **Combine Text** → *Repeat Results* with *New Lines*.
8. **Get Contents of URL** → the `shortcut:` URL that `itt run daily-coach --dry-run` prints (it contains the secret token)
   Method **POST**, Request Body **JSON**, one field: key `data`, type Text, value *Combined Text*.
9. **Show Notification** → *Contents of URL* (it says how many samples arrived and whether the plan is being made).
10. Optional: **Open URLs** → the `check-in:` URL, to land on the check-in page.

Run it once by hand and allow Health access for every type it asks about.

## Trigger it
- **Action button** (Settings → Action Button → Shortcut → Good morning): press it when you're up. Pressing it is the ritual.
- Or **Automation** → *Alarm* → *Is Stopped* (or *Sleep* → *Waking Up*) → Good morning, **Run Immediately**. Health data is locked while the phone is locked, so if the notification reports 0 samples, use the Action button instead.
- A forgotten morning is fine: the fallback timer makes the plan mid-morning from whatever data is there.

## Check-in page on the home screen
Open the `check-in:` URL in Safari → Share → **Add to Home Screen**. It opens full-screen like an app. "Trends" is the dashboard.

## Troubleshooting
- Notification shows an error or times out → Tailscale is off on the phone, or the server isn't running (`systemctl --user status daily-coach-server`).
- `bad` > 0 → dates aren't ISO 8601 (step 6), or a field is missing.
- No sleep in the plan email → in Health, does last night show data from the ring? Open the ring app once, then run the shortcut again.
- New types shown as `UNKNOWN` in `itt run daily-coach --dry-run` → the phone language names them differently; add the name to `METRICS` in `coach.py`.
