# 🚗📸 Podai globata (Подай глобата)

**Photograph a wrongly parked car in Bulgaria, send the photos to Claude, and get a formal report to the right authority a minute later.**

A free [Claude](https://claude.ai) skill for phone (Android, iPhone) and desktop. It reads time and GPS from the photos, recognises the plate, make and violations, finds the address or intersection, and routes the report (Sofia: the Urban Mobility Centre, with the city police in copy). It then writes a formal Bulgarian email citing the Road Traffic Act. You check it, attach the photos and send.

[Българска версия](README.md)

## What it does
- **Photos → facts:** date, time and location from Exif; plate, make, model and colour from the image. `scripts/exif.py` is stdlib-only and reads JPEG, HEIC, PNG and WebP.
- **Violations with legal basis:** crossings, intersections, sidewalks without 2 m for pedestrians, tactile paving, ramps, disabled bays, bike lanes, stops, double parking and more. Each maps to the Road Traffic Act as amended in 2025 ([violations.md](skills/podai-globata/references/violations.md)).
- **Address and recipients:** OpenStreetMap reverse geocoding plus the nearest intersection. The municipality's parking control (art. 167(2) ЗДвП) is the recipient and the regional police goes in copy ([authorities.json](skills/podai-globata/references/authorities.json), each address with its source and confidence).
- **A report that gets processed:** it has the sender's full name and contact (anonymous reports are dropped). It asks for an incoming number and a written answer within the statutory two months, and offers to testify as a witness.
- **Delivery:** a Gmail draft if Gmail is connected, otherwise a `mailto:` link that opens the phone's mail app. Copyable text either way.

## Limitations
- **Claude can't attach the photos: the sender must attach the original photos before sending.** The Gmail connector can't carry chat images reliably. Without photos the report is weak, and the untouched originals (with time and location) are the best evidence.
- Some phones and apps strip GPS on upload (Android's photo picker, messengers). Claude then asks for the address.
- Not every authority address is confirmed; unconfirmed ones are checked by web search when available, or flagged.
- Plate, make and violations are read from the image; always check the preview. Bulgaria only; not legal advice.

## Witnesses
A fine needs an official act drawn up in the presence of witnesses to the violation (art. 40(1) of the Administrative Violations Act). Photo-only reports often end with "no violation found" because the car has left. The email therefore states that the sender saw it and is willing to testify. **For real action, the sender may be called as a witness.**

## Install
**claude.ai (also works in the mobile apps):**
1. Download [podai-globata.zip](https://github.com/ivan-zdravkov/ivan-the-terminal/releases/download/podai-globata/podai-globata.zip).
2. Settings → Capabilities → enable *Code execution and file creation*.
3. Customize → Skills → + → Create skill → Upload a skill.
4. Optional: connect Gmail, and allow code-execution network access to `nominatim.openstreetmap.org` and `overpass-api.de` for automatic addresses.

**Claude Code:**
```
/plugin marketplace add ivan-zdravkov/ivan-the-terminal
/plugin install civic@ivan-the-terminal
```

## Privacy
- The sender's name, email and phone are asked once and kept where the user chooses: Claude memory or profile preferences (their own Claude account), or `~/.config/podai-globata/sender.json` in Claude Code.
- The skill has no server, analytics or tracking, and the author can't see any of it.
- Only the email the user approves leaves, from their own mailbox. If maps are allowed, only coordinates go to OpenStreetMap.

## Contribute authority emails
An address bounced, or you know the right one for your city? [Open the correction form](https://github.com/ivan-zdravkov/ivan-the-terminal/issues/new?template=authority-email.yml), or send a PR editing `authorities.json`. Link the official page that publishes the address. The form is public, so include no personal data.

## Replaces
City signal portals, phone queues and hand-written complaints.

MIT · part of [ivan-the-terminal](https://github.com/ivan-zdravkov/ivan-the-terminal)
