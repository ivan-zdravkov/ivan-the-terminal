#!/usr/bin/env python3
"""webapp: what turns a stdlib skill server into a home-screen app on a phone. Stdlib plus the openssl CLI.

Used by daily-coach (coach.py) and job-digest (jobs.py). Every URL is relative, so an app works under any prefix.
  env(path, defaults)        KEY="value" config file -> dict
  token(configured, dir)     the secret path prefix: from config, else generated once into the data dir
  AppHandler, serve(...)     token-gated HTTP handler base (security headers) and a multi-address server
  head(name, theme, vapid)   <head> tags: manifest, home-screen icon, iOS standalone metas, VAPID key
  manifest(name, bg, theme)  web app manifest (JSON)
  icon_png(size, bg, fg, glyph)   flat PNG icon (iOS wants PNG for the home screen)
  SW_JS                      service worker: keeps the last copy of each page for offline, push -> notification
  CLIENT_JS                  registers the worker, reloads a stale page on reopen, offline banner, push button
  Push(dir, subject)         VAPID key, subscriptions, empty "something new" pushes (the phone fetches api/latest)
  STATIC                     paths every app serves from this module: sw.js and the icons

Pushes carry no payload: the push service (Apple, Google, Mozilla) learns only that something changed. The
worker then fetches api/latest from the app over the tailnet and shows that as the notification.
"""
import base64
import hmac
import html
import json
import re
import secrets
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Only real push services: a subscription is a URL the server will POST to, so anything else would be SSRF.
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com", ".notify.windows.com")
MAX_SUBS = 10
ICON_SIZES = (180, 192, 512)

BASE_CSS = """:root{--bg:#f6f5f1;--card:#fff;--fg:#1d1d1b;--mute:#6b6a65;--line:#e4e2dc;--acc:ACC;--acc2:ACC2;
--green:#2f9e5b;--yellow:#d9a21b;--red:#d1493f}
@media (prefers-color-scheme:dark){:root{--bg:#141513;--card:#1e201d;--fg:#ecebe6;--mute:#a09f98;--line:#30332e;
--acc:DACC;--acc2:DACC2}}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:640px;margin:0 auto;padding:max(16px,env(safe-area-inset-top)) 16px 48px}a{color:var(--acc)}h1{font-size:22px;margin:4px 0}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:22px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:10px 0}
.mute{color:var(--mute);font-size:14px}.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;background:var(--acc2);white-space:nowrap}
nav{display:flex;justify-content:space-between;font-size:14px}
button{font:inherit;padding:8px 14px;border:0;border-radius:8px;background:var(--acc);color:#fff}
button.s{background:var(--acc2);color:var(--fg);min-width:44px}button.s.on{background:var(--acc);color:#fff}.big{width:100%;padding:14px;font-size:17px}
#offline{background:var(--acc2);border-radius:10px;padding:8px 12px;font-size:14px;margin:6px 0}"""


def css(acc, acc2, dacc, dacc2):
    """Base stylesheet in one accent colour (light and dark)."""
    return (BASE_CSS.replace("DACC2", dacc2).replace("DACC", dacc).replace("ACC2", acc2).replace("ACC", acc))


def head(name, theme, vapid=""):
    e = html.escape
    return (f'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
            f'<meta name="apple-mobile-web-app-title" content="{e(name)}"><meta name="theme-color" content="{e(theme)}">'
            f'<meta name="apple-mobile-web-app-status-bar-style" content="default">'
            f'<link rel="manifest" href="manifest.webmanifest"><link rel="apple-touch-icon" href="icon-180.png">'
            + (f'<meta name="vapid" content="{e(vapid)}">' if vapid else ""))


def manifest(name, bg, theme):
    return json.dumps({"name": name, "short_name": name, "id": "./", "start_url": "./", "scope": "./",
                       "display": "standalone", "background_color": bg, "theme_color": theme,
                       "icons": [{"src": f"icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any"}
                                 for n in ICON_SIZES[1:]]})


# ---------------------------------------------------------------- config, token, server

def env(path, defaults):
    cfg = dict(defaults)
    if Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_]+)=(.*)$", line)
            if not m:
                continue
            raw = m.group(2).strip()
            q = re.match(r"""(["'])(.*?)\1""", raw)
            cfg[m.group(1)] = q.group(2) if q else re.sub(r"\s+#.*$", "", raw)
    return cfg


def token(configured, data_dir):
    """Secret path prefix for every URL. From config, else generated once into the data dir (outside any repo)."""
    if configured:
        return configured
    f = Path(data_dir) / "token"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch(mode=0o600)
        f.write_text(secrets.token_urlsafe(24))
    return f.read_text(encoding="utf-8").strip()


class AppHandler(BaseHTTPRequestHandler):
    """Subclasses set `secret` (a function returning the token) and implement do_GET/do_POST with route()."""
    secret = staticmethod(lambda: "")

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; worker-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def route(self):
        """(path parts after the token, query dict), or (None, None) when the token is missing or wrong."""
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        secret = self.secret()
        if len(secret) < 16 or not parts or not hmac.compare_digest(parts[0].encode(), secret.encode()):
            return None, None
        return parts[1:], {k: v[0] for k, v in parse_qs(u.query).items()}

    def redirect_to_slash(self):
        """/TOKEN -> /TOKEN/ so relative links resolve under the token. True when it redirected."""
        path = urlparse(self.path).path
        if path.endswith("/") or path.count("/") != 1:
            return False
        self.send_response(301)
        self.send_header("Location", path + "/")
        self.end_headers()
        return True

    def body(self, limit):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        return self.rfile.read(n).decode("utf-8", "replace")


def serve(name, handler, binds, port):
    if len(handler.secret()) < 16:
        sys.exit(f"{name}: TOKEN must be 16+ random chars")
    servers = []
    for addr in [a.strip() for a in binds.split(",") if a.strip()]:
        servers.append(ThreadingHTTPServer((addr, int(port)), handler))
        print(f"{name}: listening on {addr}:{port}", flush=True)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    servers[0].serve_forever()


# ---------------------------------------------------------------- icons

GLYPHS = {
    # (x, y) in 0..1 -> inside the glyph?
    "ring": lambda x, y: 0.22 <= ((x - .5) ** 2 + (y - .5) ** 2) ** .5 <= 0.31,
    "case": lambda x, y: (0.2 <= x <= 0.8 and 0.36 <= y <= 0.76 and not (0.2 <= x <= 0.8 and 0.53 <= y <= 0.56))
    or (0.38 <= x <= 0.62 and 0.26 <= y <= 0.36 and not (0.43 <= x <= 0.57 and 0.30 <= y <= 0.36)),
}


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=16)
def icon_png(size, bg, fg, glyph):
    """A square PNG: fg glyph on a bg field, 3x3 supersampled. iOS rounds the corners itself."""
    inside, b, f = GLYPHS[glyph], _rgb(bg), _rgb(fg)
    rows = bytearray()
    sub = [(i + .5) / 3 for i in range(3)]
    for py in range(size):
        rows.append(0)  # filter: none
        for px in range(size):
            hit = sum(inside((px + dx) / size, (py + dy) / size) for dx in sub for dy in sub) / 9
            rows.extend(round(b[c] + (f[c] - b[c]) * hit) for c in range(3))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def static(path, bg, fg, glyph):
    """(body, content type) for sw.js and icon-N.png, or None."""
    if path == "sw.js":
        return SW_JS, "text/javascript; charset=utf-8"
    m = re.fullmatch(r"icon-(\d+)\.png", path)
    if m and int(m.group(1)) in ICON_SIZES:
        return icon_png(int(m.group(1)), bg, fg, glyph), "image/png"
    return None


# ---------------------------------------------------------------- browser side

SW_JS = """const C='pages-v1',S=self.registration.scope;
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{const r=e.request;if(r.method!=='GET'||new URL(r.url).pathname.includes('/api/'))return;
e.respondWith(fetch(r).then(res=>{if(res.ok){const c=res.clone();caches.open(C).then(x=>x.put(r,c))}return res})
.catch(()=>caches.match(r).then(m=>m||caches.match(S))))});
self.addEventListener('push',e=>e.waitUntil(fetch(S+'api/latest',{cache:'no-store'}).then(r=>r.json())
.catch(()=>({title:'Something new',body:'Open the app to see it.'}))
.then(j=>Promise.all([self.registration.showNotification(j.title,{body:j.body||'',tag:'latest',data:j.url||''}),
caches.open(C).then(c=>c.add(S)).catch(()=>0)]))));
self.addEventListener('notificationclick',e=>{e.notification.close();e.waitUntil(clients.matchAll({type:'window'})
.then(ws=>ws.length?ws[0].navigate(S+e.notification.data).then(w=>w&&w.focus()):clients.openWindow(S+e.notification.data)))});"""

CLIENT_JS = """(()=>{const loaded=Date.now(),B=document.body;
if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js').catch(()=>0);
document.addEventListener('visibilitychange',()=>{const a=document.activeElement;
if(document.visibilityState==='visible'&&Date.now()-loaded>6e5&&!(a&&/INPUT|TEXTAREA/.test(a.tagName)))location.reload()});
fetch('api/ping',{cache:'no-store'}).then(r=>{if(!r.ok)throw 0}).catch(()=>{const d=document.createElement('div');d.id='offline';
d.textContent='Offline: this is the copy from '+(B.dataset.at||'earlier')+'. It refreshes when the PC is reachable.';
document.querySelector('main').prepend(d)});
const key=(document.querySelector('meta[name=vapid]')||{}).content,box=document.getElementById('push');
if(!key||!box||!('PushManager' in window)||!('serviceWorker' in navigator))return;
const raw=Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
const save=s=>fetch('api/push',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(s)});
navigator.serviceWorker.ready.then(async reg=>{let s=await reg.pushManager.getSubscription();
if(s){save(s);box.textContent='🔔 Notifications on';return}
if(Notification.permission==='granted'){s=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:raw}).catch(()=>null);
if(s){save(s);box.textContent='🔔 Notifications on';return}}
if(Notification.permission==='denied'){box.textContent='Notifications are blocked: remove and re-add the app to ask again.';return}
const b=document.createElement('button');b.className='s';b.textContent='🔔 Notify me when there is something new';box.append(b);
b.onclick=async()=>{if(await Notification.requestPermission()!=='granted'){b.textContent='Not allowed';return}
const n=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:raw}).catch(e=>{b.textContent='Failed: '+e.message});
if(n&&(await save(n)).ok)box.textContent='🔔 Notifications on'}})})()"""


# ---------------------------------------------------------------- push (RFC 8030 + VAPID RFC 8292), no payload

def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def der_to_raw(sig):
    """ECDSA DER SEQUENCE{INTEGER r, INTEGER s} -> 64-byte r||s (what JWS ES256 wants)."""
    if len(sig) < 8 or sig[0] != 0x30:
        raise ValueError("not a DER signature")
    i, out = 2 if sig[1] < 0x80 else 3, b""
    for _ in range(2):
        if sig[i] != 0x02:
            raise ValueError("not a DER integer")
        n = sig[i + 1]
        out += sig[i + 2:i + 2 + n].lstrip(b"\0").rjust(32, b"\0")
        i += 2 + n
    if len(out) != 64:
        raise ValueError("bad P-256 signature")
    return out


def valid_endpoint(url):
    u = urlparse(str(url))
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and not u.username and u.port in (None, 443)
            and any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS))


class Push:
    def __init__(self, data_dir, subject):
        self.dir, self.subject = Path(data_dir), subject
        self.key, self.file = self.dir / "vapid.pem", self.dir / "push.json"

    def _openssl(self, *args, data=None):
        return subprocess.run(["openssl", *args], input=data, capture_output=True, check=True, timeout=20).stdout

    def public_key(self):
        """applicationServerKey: the uncompressed P-256 point, base64url. Creates the key pair once (owner-only)."""
        if not self.key.exists():
            self.dir.mkdir(parents=True, exist_ok=True)
            pem = self._openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout")
            self.key.touch(mode=0o600)
            self.key.write_bytes(pem)
        return b64u(self._openssl("ec", "-in", str(self.key), "-pubout", "-outform", "DER")[-65:])

    def subs(self):
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _write(self, subs):
        self.file.touch(mode=0o600)
        self.file.write_text(json.dumps(subs[-MAX_SUBS:]))

    def subscribe(self, sub):
        ep = sub.get("endpoint") if isinstance(sub, dict) else None
        if not valid_endpoint(ep) or len(ep) > 1000:
            raise ValueError("not a push service endpoint")
        self._write([s for s in self.subs() if s != ep] + [ep])
        return len(self.subs())

    def jwt(self, endpoint):
        u = urlparse(endpoint)
        claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 3600, "sub": self.subject}
        signing = b64u(b'{"typ":"JWT","alg":"ES256"}') + "." + b64u(json.dumps(claims, separators=(",", ":")).encode())
        sig = self._openssl("dgst", "-sha256", "-sign", str(self.key), data=signing.encode())
        return signing + "." + b64u(der_to_raw(sig))

    def send(self):
        """Ping every subscription. Returns (delivered, dropped); expired subscriptions are removed."""
        subs, keep, sent = self.subs(), [], 0
        if not subs:
            return 0, 0
        k = self.public_key()
        for ep in subs:
            if not valid_endpoint(ep):
                continue
            req = urllib.request.Request(ep, data=b"", method="POST", headers={
                "TTL": "43200", "Urgency": "high", "Authorization": f"vapid t={self.jwt(ep)}, k={k}"})
            try:
                with urllib.request.urlopen(req, timeout=20):
                    sent += 1
                keep.append(ep)
            except urllib.error.HTTPError as e:
                e.close()
                if e.code not in (404, 410):  # gone = unsubscribed; anything else may be temporary
                    keep.append(ep)
            except OSError:
                keep.append(ep)
        self._write(keep)
        return sent, len(subs) - len(keep)
