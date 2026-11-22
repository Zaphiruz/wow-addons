# Gander changelog

## 0.1.0 (2026-11-22)

- Shows a mob's stats on its tooltip. A line appears for every stat the game reveals about that mob: on World of Warcraft: Forever that's defense and attack speed today, and Gander will show armor, resistances, health, mana, damage, attack power, ranged attack, base stats, run speed, class and family whenever the game sends them.
- Defense is always shown: when the game doesn't give it, it's worked out as level x 5.
- Remembers what it saw. When the game hides a mob's stats, the remembered ones are shown in grey with when you saw them, such as "Attack speed: 2.0 (seen 22 Nov)". Mobs in a fight aren't remembered, since debuffs change their stats for a while.
- Shares what you learn with your guild and group, and shows what they learned as "(from Bob)". What you saw yourself is always shown first. Nothing is sent during a boss fight, and only mob stats are sent, nothing about you.
- Every line has its own switch in Options > AddOns > Gander, or type `/gander`. Remembered values and sharing can be switched off there too.
- `/gander debug` prints everything the game says about your target: what it sends, what it leaves at zero and what it hides.
- Works on Classic Era and World of Warcraft: Forever.
