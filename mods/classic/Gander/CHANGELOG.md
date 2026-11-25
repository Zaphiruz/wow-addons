# Gander changelog

## 0.9.0 (2026-11-25)

- Gander's data now lives in its own addon, GanderData, so it can grow without waiting for a new Gander. Install GanderData alongside Gander to get it. Gander still works without it, exactly as before: it learns what you see and shares with other players.
- With GanderData installed, tooltips show its stats (in grey, marked "database") for mobs the game is hiding and you haven't seen. Anything you or another player saw more recently still wins, and a live reading always does.
- The "Casts:" line now comes from GanderData. Without it there is no Casts line on World of Warcraft: Forever, because the game doesn't let addons see what a mob casts.
- The bestiary lists the database's mobs along with yours, with a new "Database" button to show just those. The window is a little wider to fit it.
- The settings page says how many mobs the database knows, or that GanderData isn't installed.

## 0.8.2 (2026-11-24)

- New "ID:" line on mob tooltips, showing the mob's creature ID. It has its own row on the Stat order page ("Mob ID"), so you can move it or untick it to hide it.
- The list of what mobs cast grew: Thunderhead in the Barrens, the first open-world mob on it.

## 0.8.1 (2026-11-24)

- New option under the combat logging setting: "Also in the open world". With both ticked, Gander keeps combat logging on outside dungeons too, so open-world mobs can join the list of what mobs cast. It's off by default and logs every fight until you untick it. Battlegrounds are never logged.

## 0.8.0 (2026-11-24)

- New "Casts:" line on mob tooltips and in the bestiary, naming the spells a mob is known to use. The list ships with Gander and will grow with each release. It starts with Blackfathom Deeps on World of Warcraft: Forever.
- The line has its own row on the Stat order page ("What it casts"), so you can move it or untick it to hide it.
- New setting, off by default: "Log combat to a file in dungeons and raids". With it on, Gander switches the game's combat logging on when you enter a dungeon or raid and off when you leave. Those log files are where the list of spells comes from. Gander never touches logging you switched on yourself.

## 0.7.2 (2026-11-24)

- /gander debug now also prints the mob casts, new debuffs on you and control effects (stuns, disarms and the like) that the game reports while it's on. This is a test for a possible future feature, remembering what each mob can do. Nothing is saved or shared yet.

## 0.7.1 (2026-11-22)

- Fixed an error when you asked for the settings during a fight (right-clicking the minimap button, the bestiary's Settings button, "Stat order..." or /gander settings). The game doesn't let addons open the settings window in combat, so Gander now tells you and opens it when the fight ends.

## 0.7.0 (2026-11-22)

- You can now choose the order of the stat lines. Options > AddOns > Gander has a new "Stat order" page: drag a line up or down, and a gold marker shows where it will land. The tooltip and the bestiary both follow your order.
- The ticks that show or hide each line moved to that page, next to the line they belong to.
- "Reset order" puts the lines back in the usual order.
- The main settings page has a "Stat order..." button that takes you there.

## 0.6.0 (2026-11-22)

- New minimap button: left-click opens the bestiary, right-click opens the settings. Drag it to move it around the edge of the minimap.
- To hide it, switch off "Show a minimap button that opens the bestiary" in Options > AddOns > Gander.

## 0.5.0 (2026-11-22)

- New bestiary: type `/gander` to open a window listing every mob Gander remembers, with its level, type and zone. Click a mob to see everything known about it, level by level, with who saw it and when.
- Search the list by name, zone, type or creature number, and show everything, only what you saw yourself, or only what you heard from others. Scroll with the mouse wheel.
- Gander now remembers each mob's name, type, rank (elite, rare, boss) and the zone you first saw it in, and shares them along with its stats. Mobs remembered before this version show as "Mob #1108" until you see them again.
- `/gander` now opens the bestiary. The settings moved to `/gander settings`, and there's a Settings button in the bestiary.

## 0.4.1 (2026-11-22)

- New switch in Options > AddOns > Gander: "Only accept signed messages". It's on by default. Switch it off to also take unsigned messages, such as ones from versions before 0.4.0 or ones typed by hand. What you send is always signed.
- Fixed a rare case where Gander didn't answer a question because it had heard about that mob in the same instant.

## 0.4.0 (2026-11-22)

- Shared messages are now signed. Gander ignores any message that doesn't carry its signature, so mob stats typed by hand into chat commands aren't accepted. This stops casual tampering; it can't stop someone who copies Gander's own code.
- Everyone needs 0.4.0 or later to share with each other. Older versions and this one ignore each other's messages. What you already remembered is kept.
- `/gander debug` says when a message was ignored for not being signed.

## 0.3.0 (2026-11-22)

- Gander now asks for mobs it knows nothing about. When the game hides a mob's stats and nothing is remembered for it, a hidden question goes to your guild, group and the Gander channel, and whoever has seen that mob answers. The lines appear on the tooltip marked "(from Bob)". The same mob isn't asked about again for 10 minutes.
- Gander answers other players' questions too, for mobs you have seen yourself. Everyone who could answer waits a moment, and only the first one does.
- Newer data now replaces older data. Each shared mob says how long ago it was seen, and the most recently seen values are shown, whether you or someone else saw them. Before, your own sighting was kept forever, even after a mob's stats changed.
- Questions and answers aren't sent during a boss fight, because the game blocks them. If the game hides which mob it is, there is nothing to ask about.

## 0.2.1 (2026-11-22)

- `/gander debug` now says where each share went, such as "shared with guild, party, the Gander channel", and why the channel was skipped when it was.

## 0.2.0 (2026-11-22)

- What you learn is now also shared on a chat channel called "Gander", which every player running Gander joins. That reaches people outside your guild and group. Nothing shows in your chat window: the messages are hidden ones only addons read.
- The channel is joined about 30 seconds after you log in, so it doesn't take the number of General or Trade. It uses one of your chat channel slots.
- Anyone can join a channel, so what's heard there never replaces what a guildmate or group member told you, and what you saw yourself still comes first.
- New switch in Options > AddOns > Gander: "Also share on the Gander chat channel". Switching it off leaves the channel.
- `/gander debug` says whether you're in the channel.

## 0.1.1 (2026-11-22)

- Fixed Gander treating your own shared messages as if another player had sent them. With `/gander debug` on, every share was followed by two "heard" lines naming you.

## 0.1.0 (2026-11-22)

- Shows a mob's stats on its tooltip. A line appears for every stat the game reveals about that mob: on World of Warcraft: Forever that's defense and attack speed today, and Gander will show armor, resistances, health, mana, damage, attack power, ranged attack, base stats, run speed, class and family whenever the game sends them.
- Defense is always shown: when the game doesn't give it, it's worked out as level x 5.
- Remembers what it saw. When the game hides a mob's stats, the remembered ones are shown in grey with when you saw them, such as "Attack speed: 2.0 (seen 22 Nov)". Mobs in a fight aren't remembered, since debuffs change their stats for a while.
- Shares what you learn with your guild and group, and shows what they learned as "(from Bob)". What you saw yourself is always shown first. Nothing is sent during a boss fight, and only mob stats are sent, nothing about you.
- Every line has its own switch in Options > AddOns > Gander, or type `/gander`. Remembered values and sharing can be switched off there too.
- `/gander debug` prints everything the game says about your target: what it sends, what it leaves at zero and what it hides.
- Works on Classic Era and World of Warcraft: Forever.
