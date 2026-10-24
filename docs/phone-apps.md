# Phone apps over the tailnet

Some skills publish their results as small web apps that live on the phone's home screen. Today these are **Daily** (daily-coach) and **Jobs** (job-digest).
They replace emailed digests and app subscriptions. The data stays on the home machine, and the apps can only be reached from inside your tailnet.

## How it works
- Each skill runs a stdlib Python server bound to `127.0.0.1`. It serves only under a secret token path.
- `tailscale serve` publishes it on the tailnet with a real HTTPS certificate. It is not Funnel, so nothing is exposed to the internet.
- `tools/webapp/webapp.py` turns a page into a home-screen app:
  - a manifest and icon
  - a service worker that keeps the last copy of each page for when the PC is unreachable
  - a reload when the app is reopened after 10+ minutes, so it always shows the latest day
  - web push
- Pushes are empty. Apple, Google or Mozilla only learn *that* something changed. The phone then fetches the notification text from the app over the tailnet.
- A headless run can't send anything itself. The runner script calls `<app> notify` after the run has stored its result.

## Set up once
1. In the Tailscale admin console, open DNS and enable **MagicDNS** and **HTTPS Certificates**.
   Certificates are logged publicly (Certificate Transparency), so the machine's `*.ts.net` name becomes public. The machine still can't be reached from outside the tailnet.
2. Let your user manage serve: `sudo tailscale set --operator=$USER`
3. Publish the apps. The config persists across reboots:
   ```sh
   tailscale serve --bg --https=443  http://127.0.0.1:8765   # Daily (daily-coach PORT)
   tailscale serve --bg --https=8443 http://127.0.0.1:8766   # Jobs (job-digest PORT)
   tailscale serve status
   ```
4. In each skill's private `config.env`, set `BIND="127.0.0.1"` and set `PUBLIC_URL` to the serve address:
   - Daily: `https://<machine>.<tailnet>.ts.net`
   - Jobs: the same address with `:8443`

   Then restart the servers: `systemctl --user restart daily-coach-server job-digest-server`.
5. `itt run daily-coach --dry-run` and `itt run job-digest --dry-run` print the app links. They contain the token, so keep them private.

## On the iPhone
1. Turn on Tailscale. VPN On Demand keeps it connected.
2. Open the app link in **Safari** → Share → **Add to Home Screen**.
3. Open the app from the new icon, not from Safari, and tap **🔔 Notify me**. iOS only allows push for home-screen apps (iOS 16.4+), and only after a tap.
   - If you tap "Don't allow", iOS won't ask again. Remove the icon and add it again.
   - Each time the app opens, it renews its subscription, so a push that iOS silently dropped recovers by itself.

Android works the same way in Chrome: menu → Add to Home screen / Install app.

## Troubleshooting
| Symptom | Check |
|---|---|
| Icon opens an "Offline" copy | Tailscale is off on the phone, or the PC is asleep or off. On the PC, check `tailscale serve status` and `systemctl --user status <app>-server`. |
| No notification | Run `itt run <skill> --dry-run`: "push: 0 device(s)" means you need to tap 🔔 in the app again. If the device count is right, look at `notify` in the newest run log. |
| Certificate warning | HTTPS Certificates is off in the admin console, or `PUBLIC_URL` uses the IP instead of the `ts.net` name. |
