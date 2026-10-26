# Photos without time or location

Missing metadata is normal and never the user's fault: the Claude app on iPhone drops it when photos are added with
„+“ → Photos, and messengers strip it too. Never lecture and never ask the user to change how they attach photos.
Ask one short question with your own guesses filled in, then move on:

> Снимките идват без час и място (приложението ги изтрива). Виждам табела „ул. …“ – правилно ли е и с коя пресечка
> или номер? И кога: „сега“ или напр. „вчера 18:30“?

- "сега" / "now": use the current Bulgarian local time, rounded to the minute.
- If the photo was taken earlier and the user doesn't remember: on iPhone, swiping up on the photo in the Photos app
  shows its date, time and place (Снимки → плъзнете нагоре / Photos → swipe up); on Android, the ⓘ (Details) button in the
  gallery does the same.
- Place: a street name, an intersection, a landmark or a Google Maps pin are all fine. Combine it with signs and house
  numbers you can read in the photos.

Only if the user asks how to keep time and place in the photos next time:
- Camera location must be on: iPhone Настройки → Поверителност и сигурност → Услуги за местоположение → Камера
  (Settings → Privacy & Security → Location Services → Camera); Android camera ⚙️ → „Етикети за местоположение“ /
  „Запазване на местоположението“ (Location tags / Save location).
- Sharing from the gallery app to Claude (Share → Claude) may keep more than „+“ → Photos; on iPhone turn on
  „Опции“ → „Местоположение“ (Options → Location) in the share sheet.
- A .zip of the original photos always keeps everything (scripts/exif.py reads zips), but only suggest it to someone
  who asks for exact GPS.

Good photos for a report: one wide shot showing the car and what it blocks (crossing, ramp, sign, sidewalk),
one close-up where the plate is readable.
