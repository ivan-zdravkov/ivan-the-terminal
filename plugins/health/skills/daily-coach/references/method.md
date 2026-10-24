# Method: why the coach works the way it does

The design target: something people who struggle to get started (low energy, broken sleep from small kids, attention/ADHD-style traits) keep using for months. Effectiveness in week one matters less. Each rule below maps to a design choice in `prompt.md` or `coach.py`.

| Problem | Design choice | Basis |
|---|---|---|
| Activation energy: starting feels like Everest | A **floor** of 3 tiny ★ items (~10 min total). Doing them = "showed up". Everything else is a bonus. | Making the behaviour as easy as possible beats motivation (behaviour design); habits take ~2 to 8 months to automate, so consistency beats intensity early (Lally et al. 2010, UCL). |
| ADHD: weak link between intention and action | Every item is one concrete action with a number, plus an **if-then anchor** to an existing routine. | Implementation intentions (Gollwitzer) improved inhibition in children with ADHD (Gawrilow & Gollwitzer). Adult ADHD data are thin, but it costs nothing. |
| ADHD: novelty-seeking, boredom with the gym | **Fresh wording and exercises daily**, one optional "side quest", XP and levels | Interest-based motivation in ADHD. Gamification has little outcome evidence, so it's here as a hook, not a mechanism. |
| One miss → drop out | **No streaks.** XP never resets. "Showed up X/7 days" instead of a streak. A **comeback bonus** (+20 XP) for showing up after a missed day. Misses shrink the plan, never guilt. | The "what-the-hell" effect after a broken streak; the fresh-start effect (Dai, Milkman & Riis). |
| No time for a 1 h session | **Exercise snacks**: kettlebell swings, push-ups, carries, stairs, brisk dog walks, spread across the day | VILPA: ~3 bursts of 1-2 min of vigorous incidental activity a day was associated with ~40% lower mortality in non-exercisers (Stamatakis et al. 2022, *Nature Medicine*, observational). Single exercise sessions improve inhibitory control in adult ADHD (small-to-moderate effects). |
| Chores lose to the computer | One timed **chore sprint**, with a podcast/audiobook allowed only during it | Temptation bundling: +51% gym visits at first, fading over time (Milkman, Minson & Volpp 2014). Rotate the bundle. |
| Food needs a decision every day | One **recipe a day** (local, seasonal, ≤40 min) with a 6-item shopping list, plus one food action in the floor | Removes the decision; the shop round trip becomes a movement snack. |
| Breakfast? | Not forced. If eaten, protein-first. | RCT meta-analysis: adding breakfast doesn't help weight loss; breakfast eaters ate ~260 kcal/day more (Sievert et al. 2019, *BMJ*). |
| Sweet tooth, salt | Fruit + nuts, and "taste before salting" as rotating floor items; low-salt notes on recipes | Swaps beat bans. |
| Half-awake "on call" nights | Morning light, a consistent wake time, a short early nap only after a broken night, and an **on-duty/off-duty** split between partners | Parents' night waking tracks their children's within minutes (actigraphy). Stressed, poorly sleeping parents are woken by smaller noises. Off-duty nights (earplugs, other room) remove the vigilance. |
| Sick days | **Readiness** from the ring: temperature, resting HR, HRV, breathing rate and SpO2 vs a 28-day baseline → green/yellow/red. Red = recovery day (walk, food, sleep). Persistent flags → "see a doctor". | Elevated temperature and resting HR with lower HRV are early illness signals in wearable studies; the thresholds here are conservative heuristics, not diagnostics. |
| Feedback loop | Check-ins → tomorrow's plan. Difficulty steps up ~10% after a strong week and shrinks after a weak one. Monday weekly review. Trends page. The note box in the app is read every morning. | Progressive overload; self-monitoring is among the most effective behaviour-change techniques. |

## What this can't replace
- **ADHD assessment.** If ADHD is likely, a proper assessment is worth it. Medication has the strongest evidence for adult ADHD symptoms (Cortese et al. 2018, *Lancet Psychiatry*). Exercise and structure are adjuncts.
- **Sleep apnea screening.** Morning headaches + unrefreshing sleep + frequent wake-ups are classic apnea signs. Some rings flag it; a doctor confirms it.

## Sources
- Stamatakis et al. 2022, VILPA and mortality, *Nature Medicine* (coverage: https://www.wcrf.org/our-blog/vigorous-exercise-and-the-science-behind-exercise-snacking/)
- Sievert et al. 2019, breakfast RCT meta-analysis, *BMJ* https://www.bmj.com/content/364/bmj.l42
- Milkman, Minson & Volpp 2014, temptation bundling https://pubmed.ncbi.nlm.nih.gov/25843979/
- Adult ADHD and single exercise sessions https://adhdevidence.org/blog/meta-analysis-finds-small-to-moderate-benefits-of-single-exercise-sessions-for-adult-adhd
- Cortese et al. 2018, ADHD medication network meta-analysis, *Lancet Psychiatry* https://doi.org/10.1016/S2215-0366(18)30269-4
- Parent-child night waking concordance (actigraphy) https://research.monash.edu/en/publications/actigraphy-measured-sleep-concordance-night-wakings-intraindividu/
- Children's sleep problems and parents' sleep quality https://dovepress.com/article/download/58744
- SMS reminders in an adult ADHD internet intervention (reminders alone didn't raise completion) https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9149073/
