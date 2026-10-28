# Email template: СВЕДЕНИЕ

Plain text, Bulgarian, no Markdown. One email per car; several photos of the same car go in one email. Fill every
`<…>`. A sender field the user chose not to give stays as its `[…]` placeholder, exactly as written below, for the user
to fill in before sending. Drop any other line whose data is unknown rather than writing "неизвестно", except the plate,
which is mandatory.

**Subject:** `Сведение за неправилно паркиран автомобил – <РЕГ_№>, <кратък адрес>, <ДД.ММ.ГГГГ> <ЧЧ:ММ>`

**Body:**

```
На вниманието на служба КАТ

СВЕДЕНИЕ

Име, презиме, фамилия: <три имена | [три имена]>
Адрес за кореспонденция: <адрес | [адрес за кореспонденция]>
Мобилен номер: <телефон | [мобилен номер]>
Имейл: <имейл | [имейл]>
Номер на ЛК/ЛНЧ: <№ | [№ на ЛК/ЛНЧ]>, ЕГН: <ЕГН | [ЕГН]>

На <ДД.ММ.ГГГГ> г. около <ЧЧ:ММ> ч., минавайки по <ул. „…“ № … / кръстовището на ул. „…“ и ул. „…“>, гр. <…>,
установих 1 брой <лек автомобил | товарен автомобил | …> <марка> <модел>, <цвят>, рег. № <РЕГ_№>, спрял в нарушение:
1. <wording from violations.md> – <basis>;
2. <…>.

Прилагам <N> бр. снимков материал и <M> бр. видео материал, направени с мобилен телефон марка <марка>, модел <модел>,
с информация за нарушението (оригинални файлове с дата, час и местоположение) към сведението за потвърждаване на
гореспоменатото.

Запознат съм с наказателната отговорност, която се носи по чл. 313, ал. 1 от НК при потвърждаване на неистина или
затаяване на истина.

Моля:
1. Въз основа на приложените снимки и сведението ми да съставите акт за установяване на административно нарушение и да
   наложите предвидената санкция на собственика или ползвателя на автомобила (чл. 188 от ЗДвП).
2. Да ми съобщите входящия номер на сигнала.
3. Да ме уведомите писмено за предприетите действия в законоустановения срок (чл. 121 и чл. 123 от АПК).
Ако сигналът не е от Вашата компетентност, моля да го препратите на компетентния орган (чл. 112 от АПК).

При необходимост заявявам, че ще се явя като свидетел-очевидец при съответните институции (чл. 40, ал. 1 от ЗАНН),
стига това време да не е в неразрешим конфликт със служебните ми задължения.

Дата: <днешна дата ДД.ММ.ГГГГ> г.

Дал сведения: <три имена | [три имена]>
Приел сведения: ______________________
```

Rules:
- The email carries no GPS coordinates and no map link. Use GPS only to find the address (`scripts/geo.py`); when
  that fails, read signs and house numbers in the photos, then ask the user for the address.
- Ask for the act and the fine based on the photos and the sender's statement. Never ask for an on-site check
  ("проверка на място"), a patrol or towing, and never mention that inspectors usually arrive after the car has gone.
- Time comes from the photos. If they have none, use the time the user gives; never invent it. Write the local Bulgarian
  time (the Exif `utc_offset` is usually +02:00 in winter, +03:00 in summer).
- Place: use the intersection when the car is within ~25 m of it; otherwise street + number, or "ул. X, срещу № …".
- Car make/model: only if recognisable; "лек автомобил, <цвят>" otherwise. Never guess a plate: ask.
- Phone make/model: from the Exif `camera` summary. Write the brand properly ("Samsung", not "samsung") and the
  market name when the model is a code you know ("Galaxy S23 (SM-S911B)"). Unknown: write
  `марка [марка], модел [модел]` and list it among the things to check.
- `<M>` is 0 unless the user attaches a video to this email. Videos rarely fit in an email: see "Video" below.
- If the user adds facts (e.g. "стои там всеки ден", "блокира рампата"), add one short sentence after the list.
- "Приел сведения" stays blank: it is for the officer who receives a printed copy.
- Recipients' names don't go in the body. To/Cc carry them.

## Video

Photos are usually enough: don't ask for video. If the user has one, a short clip under ~20 MB can be attached and
counted in `<M>`. Bigger files don't pass email limits, and МВР has no upload portal. Don't suggest a cloud link:
МВР most likely won't open it and needs the original files. Tell the user to send the email with the photos and provide
the video separately on physical media (disc or USB stick), e.g. at the local police station (районно управление) with
the printed СВЕДЕНИЕ, or however МВР asks. Say plainly that it is inconvenient.

The СВЕДЕНИЕ structure, the МВР reception address and the video advice come from the Facebook group
[„Паркиране в София: нови идеи“](https://www.facebook.com/profile.php?id=61572325905650), with thanks.
