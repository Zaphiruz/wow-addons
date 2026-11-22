# Gander changelog

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
