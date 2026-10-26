# 🚗📸 Podai globata (Подай глобата)

**Photograph a wrongly parked car in Bulgaria, send the photos to Claude, and get a formal report to the right authority a minute later.**

A free [Claude](https://claude.ai) skill for phone (Android, iPhone) and desktop. It reads time and GPS from the photos, recognises the plate, make and violations, finds the address or intersection, and routes the report (Sofia: the Urban Mobility Centre, with the city police in copy). It then writes a formal Bulgarian email citing the Road Traffic Act. You check it, attach the photos and send.

[Българска версия](README.md) · Share link: **[zdravkov.dev/podai-globata](https://zdravkov.dev/podai-globata)**

**Contents**

- [What it does](#what-it-does)
- [Example email](#example-email)
- [Limitations](#limitations)
- [Witnesses](#witnesses)
- [Install](#install)
- [Privacy](#privacy)
- [Contribute authority emails](#contribute-authority-emails)
- [Replaces](#replaces)

## What it does
- **Photos → facts:** date, time and location from Exif; plate, make, model and colour from the image. `scripts/exif.py` is stdlib-only and reads JPEG, HEIC, PNG and WebP.
- **Violations with legal basis:** crossings, intersections, sidewalks without 2 m for pedestrians, tactile paving, ramps, disabled bays, bike lanes, stops, double parking and more. Each maps to the Road Traffic Act as amended in 2025 ([violations.md](references/violations.md)).
- **Address and recipients:** OpenStreetMap reverse geocoding plus the nearest intersection. The municipality's parking control (art. 167(2) ЗДвП) is the recipient and the regional police goes in copy ([authorities.json](references/authorities.json), each address with its source and confidence).
- **A report that gets processed:** it has the sender's full name and contact (anonymous reports are dropped). It asks for an incoming number and a written answer within the statutory two months, and offers to testify as a witness.
- **Delivery:** a Gmail draft if Gmail is connected, otherwise a `mailto:` link that opens the phone's mail app. Copyable text either way.

## Example email

The finished report for a car on the sidewalk next to an intersection (fictional sender). The email is always in Bulgarian; Claude shows it to you before anything is sent.

> **До:** office@sofiatraffic.bg (ЦГМ)<br>
> **Копие:** trafficpolicesdvr@mvr.bg (СДВР – „Пътна полиция“)<br>
> **Тема:** Сигнал за неправилно паркиране – CA1234AB, ул. „Граф Игнатиев“ / ул. „Солунска“, 25.10.2026 18:42
>
> Уважаеми госпожи и господа,
>
> Подавам сигнал за неправилно паркиран автомобил, на който съм очевидец:
>
> Дата и час: 25.10.2026 г., 18:42 ч. (по данни от снимките)<br>
> Място: кръстовището на ул. „Граф Игнатиев“ и ул. „Солунска“, гр. София<br>
> GPS координати: 42°41'31.7"N 23°19'22.2"E (точност около 5 м)<br>
> Карта: https://www.google.com/maps?q=42%C2%B041%2731.7%22N+23%C2%B019%2722.2%22E<br>
> Превозно средство: Volkswagen Golf, сив, рег. № CA1234AB
>
> Нарушения:
> 1. Паркиране върху тротоар извън обозначените места, без да остават 2 м за пешеходците – чл. 94, ал. 3; чл. 183, ал. 2, т. 1 ЗДвП;
> 2. Паркиране на по-малко от 5 м от кръстовище – чл. 98, ал. 1, т. 6; чл. 183, ал. 4, т. 8 ЗДвП.
>
> Прилагам 2 бр. снимки (оригинални файлове с дата, час и местоположение).
>
> Моля:
> 1. Въз основа на приложените снимки и моите показания като очевидец да съставите акт за установяване на административно нарушение и да наложите предвидената в ЗДвП санкция на собственика или ползвателя на автомобила (чл. 188 ЗДвП).
> 2. Да ми съобщите входящия номер на сигнала.
> 3. Да ме уведомите писмено за предприетите действия в законоустановения срок (чл. 121 и чл. 123 от АПК).
>
> Заявявам готовност да бъда свидетел при съставянето на акта (чл. 40, ал. 1 от ЗАНН) и да предоставя снимките в оригинал.
> Ако сигналът не е от Вашата компетентност, моля да го препратите на компетентния орган съгласно чл. 112 от АПК.
>
> С уважение,<br>
> Мария Петрова Иванова<br>
> Тел.: 08XX XXX XXX<br>
> Имейл: maria@example.com
>
> 📎 *2 прикачени снимки*

## Limitations
- **Claude can't attach the photos: the sender must attach the original photos before sending.** The Gmail connector can't carry chat images reliably. Without photos the report is weak, and the untouched originals (with time and location) are the best evidence.
- Some phones and apps strip GPS on upload (Android's photo picker, messengers). Claude then asks for the address.
- Not every authority address is confirmed; unconfirmed ones are checked by web search when available, or flagged.
- Plate, make and violations are read from the image; always check the preview. Bulgaria only; not legal advice.

## Witnesses
A fine needs an official act drawn up in the presence of witnesses to the violation (art. 40(1) of the Administrative Violations Act). The car's owner answers for the violation (art. 188 of the Road Traffic Act), so a fine can be issued from the photos without anyone visiting the spot days later. The email therefore asks for the act and the fine based on the photos and the sender's eyewitness testimony, and says the sender is willing to testify. **For real action, the sender may be called as a witness.**

## Install
**A. From GitHub, no zip (paid plans: Pro, Max, Team):** claude.ai → Customize → Plugins → Add → Add marketplace → Add from a repository → `ivan-zdravkov/ivan-the-terminal` → in Discover, add **civic**.

**B. Zip upload (all plans, including Free):** download [podai-globata.zip](https://github.com/ivan-zdravkov/ivan-the-terminal/releases/download/podai-globata/podai-globata.zip) → Customize → Skills → + → Create skill → Upload a skill.

**Both:**
- Settings → Capabilities → enable *Code execution and file creation*.
- Optional: connect Gmail, and allow code-execution network access to `nominatim.openstreetmap.org` and `overpass-api.de` for automatic addresses.

**Is the zip safe?** It is plain text: instructions and three short Python scripts, identical to this folder. It never runs on your phone; Claude unpacks it in its own sandbox. You can read every file in Customize → Skills after uploading.

**Updates:** zip uploads don't update themselves. Delete the skill and upload the zip again from the same link; watch the repo's Releases to hear about new versions. GitHub installs pick changes up from the repository. Claude Code syncs plugins on every start.

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
