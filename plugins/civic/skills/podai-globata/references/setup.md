# First run: sender details

A report needs the sender's three names, email and phone: anonymous reports are not processed (чл. 111, ал. 4 АПК) and
the sender may be called as a witness. Ask once, in one message, in Bulgarian:

> За да е редовен сигналът, трябват три имена, имейл и телефон. Анонимни сигнали не се разглеждат, а може да Ви
> поканят като свидетел. Данните отиват само в имейла до институциите.

Then offer to remember them, in this order of preference:

1. **Claude memory** (if a memory tool is available and the user agrees): save one line:
   `Подай глобата подател: <три имена> | <имейл> | <телефон>`.
2. **Profile preferences** (always works, any plan): tell the user to paste the same line into
   Settings → Profile → "What personal preferences should Claude consider in responses?" (Настройки → Профил →
   лични предпочитания). Claude then sees it in every new chat.
3. **Claude Code**: write `~/.config/podai-globata/sender.json` (`{"name": "…", "email": "…", "phone": "…"}`) with mode 600.

Explain plainly where the data lives: in the user's own Claude account (memory or preferences) or on their computer
(Claude Code). The skill has no server, sends nothing anywhere except the email the user approves, and its author can't
see it. To change or delete it: edit or remove that line (or the file), or tell Claude "забрави данните за „Подай глобата“".

Never write the details anywhere else, and never repeat them in chat beyond the email preview.
