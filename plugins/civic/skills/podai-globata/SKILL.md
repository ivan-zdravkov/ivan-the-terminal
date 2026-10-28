---
name: podai-globata
description: Report a wrongly parked car in Bulgaria from 1+ photos - time, GPS, plate, violations, address, the right authority (МВР приемна + общината), a formal СВЕДЕНИЕ email as a Gmail draft, mailto link or copy text. Use when someone sends photos of a badly parked car or says сигнал, неправилно паркиране, паркиран на тротоара/пешеходна пътека, нарушител, глоба, паяк.
metadata:
  version: "0.2.0"
---

# Подай глобата

Replaces: city signal portals, phone queues and hand-written complaints. Talk to the user in Bulgarian (or their
language); the email is always Bulgarian. Scripts are in `scripts/` next to this file: `python3`, stdlib only.
Be fast: one short summary per step, ask everything missing in a single message.

## 1. Photos → facts
1. Find the files: on claude.ai `/mnt/user-data/uploads/`, in Claude Code the paths given. Run
   `python3 scripts/exif.py FILE...` (zips of photos work too). If the photos exist only as chat images (no files),
   metadata is gone: continue.
2. No time or GPS in `summary` (common: the iPhone app strips it): look at the photos first, then ask once, with your
   guesses, as `references/photos.md` shows. Never make the user re-send or re-attach photos.
3. `spread_m` > 100 or times more than an hour apart: ask whether it's one car and one place.
4. Look at every photo: plate (Latin capitals, no spaces), make, model, colour, visible signs, markings, street names,
   house numbers. Note the phone from the summary's `camera`. Match what you see to `references/violations.md`. Never guess a plate or a violation: if unsure, ask.
5. Parking that looks legal, or a place outside Bulgaria: say so honestly and stop.

## 2. Place → recipients
Run `python3 scripts/geo.py locate LAT LON` (add `--green` for a car on grass or in a park). To is always the МВР
reception (priemna@mvr.bg, national), Cc the municipal service when known; `fallback` is the regional police.
- Exit 3 (no network in the sandbox): ask for street and city, then `python3 scripts/geo.py route OBLAST MUNICIPALITY`
  ("София" alone means the city). Prefer a house number or street name visible in a photo over the OSM guess.
- Within ~25 m of `intersection` (or `near_streets`), name the intersection; otherwise use street + number.
- No address from GPS, OSM or the photos: ask the user. The email has no coordinates, so the address must be right.
- Each `lookup` line: with web search, find or confirm that address on the institution's own site and use it; without it,
  keep the listed address and tell the user which one is unverified. No recipient at all: ask the user.

## 3. Sender
Look for a `Подай глобата подател:` line in memory, profile preferences or project instructions, or for
`~/.config/podai-globata/sender.json`. Missing (or a 0.1.0 line without the new fields): follow `references/setup.md`:
the user decides field by field what to give; withheld fields stay as `[…]` placeholders. Never insist.

## 4. Preview → confirm
Write the email from `references/email-template.md`. Show To/Cc (names + emails), subject and body, then a short list of
anything uncertain (plate characters, the 5 m distance, unverified address) and every `[…]` placeholder the user must
fill in. Apply edits. Ask:
"Да го подготвя ли за изпращане?". Do nothing outbound before a clear yes.

## 5. Deliver (first option that works)
1. **Gmail tool available**: create a draft with to, cc, subject, the plain-text body and an `htmlBody` (same text,
   `<br>` line breaks, any link as an `<a href>`: Gmail turns plain-text links into redirects). No attachments: photos can't
   pass through the tool reliably, and the original files with their metadata are the stronger evidence. Tell the user:
   open Gmail → Чернови → the draft → 📎 attach the photos → Изпрати (give the draft link if returned). Send directly
   with `send_message` only if the user explicitly asks to send without photos.
2. **No Gmail**: pipe `{"to","cc","subject","body"}` as JSON into `python3 scripts/mailto.py` and give the result as a
   link "📧 Отвори в пощата". It opens the phone's mail app filled in; the user attaches the photos and sends.
3. **Always** add the full text in one code block (До, Копие, Тема, then the body) for manual copy.
4. **Always** end with this reminder, bold, on its own line: "📎 Прикачете оригиналните снимки (от галерията, не от чата)
   преди да изпратите! Без тях сигналът е слаб." Name which photos. With placeholders, add on the next line:
   "✍️ Попълнете [ЕГН], […] в текста преди изпращане." listing the ones left.

## 6. After
One line: keep the original photos; the institution must answer within two months (чл. 121 АПК); if not, reply in the
same thread asking for the status with the incoming number. Several cars: one email per car, repeat from step 1.

## Fixes
- Address looks wrong: OSM snaps to the nearest building. Trust the photo and the user, and keep the GPS line.
- Sofia alternative channel: call.sofia.bg (the city's portal) accepts the same text and photos.
- The user wants the photos attached by Claude: explain step 5.1 and offer the draft; never send a half-empty email.
- Video: see "Video" in `references/email-template.md` (big files go on a disc or USB stick to the police station).
- An address bounced or the institution says it isn't competent: resend to the `fallback` recipient, and ask the user to report
  the correct address at https://github.com/ivan-zdravkov/ivan-the-terminal/issues/new?template=authority-email.yml
  (public form: no personal data).
