# Podai globata (Подай глобата)

🚗📸 **Photograph a wrongly parked car in Bulgaria, send the photos to Claude, and get a formal report to the right authority a minute later.**

Free · Android, iPhone and desktop · all you need is a [Claude](https://claude.ai) account (the free plan works)

[How it works](#how-it-works) · [Install](#install-3-minutes-once) · [Example email](#example-email) · [Important](#important-before-your-first-report) · [Questions](#questions) · [Български](README.md)

Useful? **[⭐ Star it on GitHub](https://github.com/ivan-zdravkov/ivan-the-terminal)** (the **Star** button, top right) so more people find it.

## How it works

1. **Photograph the car:** one wide shot that shows the violation, and one close-up where the plate is readable.
2. **Send the photos to Claude** in a new chat. No need to type anything.
3. **Check the finished email**, attach the photos and send.

Claude finds the date, time and place, the plate and make, the violations with the article of the law, and the right authority (Sofia: the Urban Mobility Centre, with the city police in copy). If anything is missing, it asks.

## Install (3 minutes, once)

Easiest from a desktop browser. After that the skill works everywhere, including the Claude phone app.

1. On [claude.ai](https://claude.ai), open **Settings → Capabilities** and turn on **Code execution and file creation**.
2. Open **Customize → Plugins → Add → Add marketplace → Add from a repository**, enter `ivan-zdravkov/ivan-the-terminal` and confirm.
3. In **Discover**, pick **civic** → **Add**. The other plugins in the list aren't needed.
4. *(Recommended)* **Settings → Connectors → Gmail → Connect**, to get a ready draft in Gmail.

Done. On a phone, close and reopen the Claude app. Plugins need a paid plan (Pro, Max, Team); on the free plan, use the .zip below.

<details>
<summary>Other ways: free plan (.zip file), Claude Code, more accurate addresses</summary>

- **Free plan (.zip file):** after step 1, download **[podai-globata.zip](https://github.com/ivan-zdravkov/ivan-the-terminal/releases/download/podai-globata/podai-globata.zip)** (don't unzip it), then **Customize → Skills → „+“ → Create skill → Upload a skill** and pick the file. Works on every plan.
- **Claude Code:** `/plugin marketplace add ivan-zdravkov/ivan-the-terminal`, then `/plugin install civic@ivan-the-terminal`.
- **More accurate addresses:** in the Code execution settings, allow network access to `nominatim.openstreetmap.org` and `overpass-api.de` (OpenStreetMap). Without it, Claude reads the address from street signs in the photo or asks you.

</details>

## Example email

A car on the sidewalk next to an intersection, with a fictional sender. The email is always in Bulgarian, and Claude shows it to you before anything is sent.

<details>
<summary><b>To:</b> Urban Mobility Centre · <b>Cc:</b> Sofia traffic police · <b>Subject:</b> report of a wrongly parked car, CA1234AB, Граф Игнатиев / Солунска (tap to see the whole email)</summary>

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
> GPS координати: 42.692545, 23.323929 (точност около 5 м)<br> <!-- leakguard:allow (example: public intersection) -->
> Карта: https://maps.google.com/?q=42.692545,23.323929<br> <!-- leakguard:allow (example: public intersection) -->
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

</details>

## Important before your first report

- **📎 Attach the original photos yourself before sending.** Claude can't attach them to the email, and without them the report is weak.
- **👮 You may be asked to act as a witness.** That's what lets the authority fine from the photos, without an on-site check days later.
- **Check the plate and violations** in the preview: Claude reads them from the photo.
- **Bulgaria only.** This isn't legal advice.

## Questions

<details>
<summary><b>The photos have no time or location?</b></summary>

No problem. The Claude iPhone app and messengers often strip them. Claude reads street signs and house numbers from the photo and asks only for what's missing, e.g. "I see бул. Витоша: which cross street? And when: now, or yesterday 18:30?" If you don't remember, open the photo in your gallery and swipe up (iPhone) or tap ⓘ Details (Android).

To make the camera save the location: iPhone → Settings → Privacy & Security → Location Services → Camera; Android → camera → ⚙️ → Location tags / Save location.

</details>

<details>
<summary><b>Who receives the report?</b></summary>

Parking in towns is enforced by the municipality (art. 167(2) of the Road Traffic Act), so the report goes to the municipal service, with the police in copy:

| City | To | Cc |
|---|---|---|
| Sofia | Urban Mobility Centre (ЦГМ) | Sofia traffic police (СДВР) |
| Sofia, car on a green area | Sofia Inspectorate | СДВР |
| Plovdiv, Varna, Burgas | the municipal service | the regional police (ОДМВР) |
| Other towns | the regional police (+ the municipality, if Claude finds its address) | |

Violations follow the Road Traffic Act as amended in September 2025: sidewalks, crossings, intersections, tactile paving, ramps, disabled bays, bike lanes, stops, double parking, in front of garages or schools and more ([violations.md](references/violations.md)).

</details>

<details>
<summary><b>Why might I be called as a witness?</b></summary>

A fine needs an official act drawn up in the presence of witnesses to the violation (art. 40(1) of the Administrative Violations Act), and the car's owner answers for the violation (art. 188 of the Road Traffic Act). So the email asks for the act based on the photos and your eyewitness testimony. If the authority acts on it, they may call you to sign the act. Without a willing witness, a report rarely ends in a fine.

</details>

<details>
<summary><b>Where is my personal data kept?</b></summary>

Your full name, email and phone, because anonymous reports aren't processed. Claude asks once and keeps them where you choose: Claude memory or your profile preferences (Settings → Profile), i.e. your own account. In Claude Code, a file on your computer.

**The author has no access** to your data, photos or emails. The skill has no server, database or tracking. Only the email you approve leaves, from your own mailbox, and, if you allowed maps, only coordinates go to OpenStreetMap. Photos and text pass through Claude like any conversation ([Anthropic privacy](https://www.anthropic.com/legal/privacy)).

To delete them, tell Claude "forget the Подай глобата details".

</details>

<details>
<summary><b>Is the .zip file safe?</b></summary>

Yes. It's plain text: instructions and three short Python scripts, exactly [these on GitHub](https://github.com/ivan-zdravkov/ivan-the-terminal/tree/main/plugins/civic/skills/podai-globata). It never installs or runs on your phone: Claude uses it in its own sandbox. The skill does nothing outbound without your explicit yes.

</details>

<details>
<summary><b>How do I update?</b></summary>

The **Plugins** (GitHub) install and Claude Code update themselves; if you don't see a change, remove and re-add the plugin. An uploaded .zip doesn't: delete the skill in **Customize → Skills** and upload the file again from the same link. To hear about new versions: on GitHub, **Watch → Custom → Releases**.

</details>

<details>
<summary><b>When will I get an answer?</b></summary>

The authority must answer in writing within **2 months** (art. 121 of the Administrative Procedure Code). If it doesn't, reply in the same thread and ask about the incoming number. Send soon after the violation. If the spot is a chronic problem, say so: the municipality can install bollards. In Sofia you can also file the same report at [call.sofia.bg](https://call.sofia.bg).

</details>

<details>
<summary><b>The authority's email is wrong?</b></summary>

We can't know the right address for every town in advance ([the list with sources](references/authorities.json)). If the email bounced or the authority replied that it isn't competent, [fill in the short form](https://github.com/ivan-zdravkov/ivan-the-terminal/issues/new?template=authority-email.yml) with the town, the authority and the right email, or send a PR editing `authorities.json`. The form is public: no personal data, plates or photos. The fix ships to everyone in the next version.

</details>

---

**[⭐ Star on GitHub](https://github.com/ivan-zdravkov/ivan-the-terminal)** · MIT · part of [ivan-the-terminal](https://github.com/ivan-zdravkov/ivan-the-terminal)
