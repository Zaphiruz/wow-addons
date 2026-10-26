# Downcast changelog

## 0.1.0 (2026-10-25)

First release.

- Macros can now cast buffs and heal-over-time spells on low-level players. The game picks the highest rank that will land instead of failing with "Target is too low level".
- Each spell gets a button your macros press with `/click`, such as `/click DowncastRenew`. Your own macro lines, modifiers and `#showtooltip` keep working.
- Aims at your mouseover, then your friendly target, then yourself, and works in combat.
- Priests start with Renew, Power Word: Fortitude, Power Word: Shield, Divine Spirit and Shadow Protection. Other classes start with an empty list.
- Add any spell with `/downcast add <spell name>`, optionally with a shorter button name: `/downcast add Power Word: Shield as PWS`. Remove one with `/downcast remove <name>`.
- `/downcast spells` lists the spells in your spellbook worth adding.
- `/downcast` lists your buttons, the `/click` line for each, and whether it's ready.
- New ranks are picked up automatically when you train them, once you're out of combat.
- Spells sit in hidden action slots. Downcast only uses empty slots and never overwrites anything on your bars.
- `/downcast debug` prints what each click does, for troubleshooting.
