# First run: sender details

The СВЕДЕНИЕ asks for six sender fields. All six are personal data and all six are equal: the name, email and phone
are as optional as the ЕГН. Each one is the user's choice, the skill works without any of them, and a field the user
keeps to themselves becomes a `[…]` placeholder in the email that they fill in before sending.

Never fill a field from anywhere else: not from the Gmail account, the Claude profile name, earlier chats or other
memories. Only what the user gave for this skill.

| Field | Placeholder | Why МВР asks for it |
|---|---|---|
| три имена | `[три имена]` | anonymous reports are not processed (чл. 111, ал. 4 АПК) |
| адрес за кореспонденция | `[адрес за кореспонденция]` | where the written answer goes |
| мобилен номер | `[мобилен номер]` | to call the sender as a witness |
| имейл | `[имейл]` | for the answer and the incoming number |
| № на ЛК/ЛНЧ | `[№ на ЛК/ЛНЧ]` | identifies the sender for the act |
| ЕГН | `[ЕГН]` | identifies the sender for the act |

Ask once, in one message, in Bulgarian, before the first email:

> За официално сведение до МВР трябват: три имена, адрес за кореспонденция, мобилен номер, имейл, № на лична карта
> и ЕГН. Вие решавате кои да ми дадете. За всяко поле изберете:
> **запомни** (пазя го в паметта на Claude или в профила Ви, т.е. във Вашия акаунт),
> **само сега** (ползвам го само в този имейл) или
> **не давам** (оставям празно поле, например [ЕГН], и го попълвате сами преди изпращане).
> Умението работи и без тях. Данните отиват само в имейла, който Вие одобрите. Авторът му не ги вижда.
> Пример: „всичко: не давам“, „всичко: само сега“ или „имена и имейл: запомни; останалото: не давам“.

If the user just pastes some details without choosing, use them for this email only and ask once whether to remember them.

Remember only the fields marked "запомни", in this order of preference:

1. **Claude memory** (if a memory tool is available): one line,
   `Подай глобата подател: име=<…>; имейл=<…>; телефон=<…>; адрес=<…>; лк=<…>; егн=<…>`, leaving out what was not
   given. Also remember `не давам: <fields>` so you don't ask again, e.g.
   `Подай глобата подател: име=…; телефон=…; не давам: лк, егн`.
   Version 0.1.0 wrote `Подай глобата подател: <имена> | <имейл> | <телефон>` without asking field by field: ask
   once about all six, offering to keep those three, and rewrite the line in the new form (or remove it).
2. **Profile preferences** (always works, any plan): tell the user to paste the same line into
   Settings → Profile → "What personal preferences should Claude consider in responses?" (Настройки → Профил →
   лични предпочитания). Claude then sees it in every new chat.
3. **Claude Code**: write `~/.config/podai-globata/sender.json` with mode 600:
   `{"name": "…", "email": "…", "phone": "…", "address": "…", "id_card": "…", "egn": "…", "withheld": ["egn"]}`.

Explain plainly where the data lives: in the user's own Claude account (memory or preferences) or on their computer
(Claude Code). Fields given "само сега" still pass through this chat. To keep a field fully outside Claude, choose
"не давам". The skill has no server and sends nothing except the email the user approves. Its author can't see any of
it. To change or delete: edit or remove that line (or the file), or say "забрави данните за „Подай глобата“".

Never write the details anywhere else, and never repeat them in chat beyond the email preview.
