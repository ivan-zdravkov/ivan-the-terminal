# Email template

Plain text, Bulgarian, no Markdown. Fill every `<…>`; drop a line whose data is unknown rather than writing "неизвестно",
except the plate, which is mandatory. One email per car. Several photos of the same car go in one email.

**Subject:** `Сигнал за неправилно паркиране – <РЕГ_№>, <кратък адрес>, <ДД.ММ.ГГГГ> <ЧЧ:ММ>`

**Body:**

```
Уважаеми госпожи и господа,

Подавам сигнал за неправилно паркиран автомобил, на който съм очевидец:

Дата и час: <ДД.ММ.ГГГГ г., ЧЧ:ММ ч.> (по данни от снимките)
Място: <ул. „…“ № … / кръстовището на ул. „…“ и ул. „…“>, <гр. …>
GPS координати: <LAT>, <LON> (точност около <N> м)
Карта: <maps_url>
Превозно средство: <марка> <модел>, <цвят>, рег. № <РЕГ_№>

Нарушения:
1. <wording from violations.md> – <basis>;
2. <…>.

Прилагам <N> бр. снимки (оригинални файлове с дата, час и местоположение).

Моля:
1. Да извършите проверка и да наложите предвидената в ЗДвП санкция, а при необходимост и принудително преместване на автомобила.
2. Да ми съобщите входящия номер на сигнала.
3. Да ме уведомите писмено за предприетите действия в законоустановения срок (чл. 121 и чл. 123 от АПК).

Заявявам готовност да бъда свидетел при съставянето на акт за установяване на административно нарушение (чл. 40, ал. 1 от ЗАНН) и да предоставя снимките в оригинал.
Ако сигналът не е от Вашата компетентност, моля да го препратите на компетентния орган съгласно чл. 112 от АПК.

С уважение,
<Име Презиме Фамилия>
Тел.: <телефон>
Имейл: <имейл>
```

Rules:
- Time comes from the photos. If they have none, use the time the user gives; never invent it. Write the local Bulgarian
  time (the Exif `utc_offset` is usually +02:00 in winter, +03:00 in summer).
- Coordinates: 5 decimals. Omit the accuracy if it is unknown. Without GPS, drop the GPS and Карта lines and describe
  the place precisely (street, number, landmark).
- Place: use the intersection when the car is within ~25 m of it ("кръстовището на ул. X и ул. Y"); otherwise
  street + number, or "ул. X, срещу № …".
- Make/model: only if recognisable; "лек автомобил, <цвят>" otherwise. Never guess a plate: ask.
- If the user adds facts (e.g. "стои там всеки ден", "блокира рампата"), add one short sentence after the list.
- Recipients' names don't go in the body. To/Cc carry them.
