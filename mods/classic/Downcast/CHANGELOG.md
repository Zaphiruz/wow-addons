# Downcast changelog

## 0.2.1 (2026-10-31)

- Fixed an error when accepting the game's own confirmation popups, such as using a bind-on-use item like a mount. Downcast was blamed for the blocked action.

## 0.2.0 (2026-10-31)

- New window: `/downcast edit` lists your spells with their icons, `/click` lines and top ranks.
- Add a spell by dragging it from your spellbook into the window, or pick it from the "Add spell..." menu.
- Remove a spell with the X on its row, and rename a button with Rename.
- Select a `/click` line in the window and copy it with Ctrl+C.
- The window can be opened in combat, but changes are locked until combat ends.
- New command: `/downcast rename <ButtonName> <NewName>`.

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
