# Persona types and element terminology

Reference for localizing the PSX game's type, subtype, and affinity text. The
tables below summarize material supplied from the Megami Tensei Wiki's pages on
types and minor elements, including the supplied type/subtype screenshot. Wiki
material is credited to the [Megami Tensei Wiki](https://megamitensei.fandom.com/)
and is available under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

**Evidence:** This is a translation aid, not a verified specification of PSX
combat. The wiki's mechanics and mappings have not all been checked against
the retail game. PSP wording describes the PSP release and is context, not
proof that the PSX has the same behavior. Do not use this document to generate
in-game names or affinity descriptions; names come from extracted game data,
and the English wording of affinity descriptions is manually authored.

## Types

The PSX type labels are English even in the Japanese release. PSP Japanese
and PSP-US names are given for comparison.

| PSX label | PSP Japanese | PSP US | Races reported by wiki | Persona Arcana reported by wiki |
|---|---|---|---|---|
| NORMAL | 通常 | Normal | Meta, Fiend | None |
| ELEMENTAL | 精霊 | Element | Yoma, Fairy, Flight, Jirae, Jaki | Magician, Emperor, Lovers, Hermit, Star, Sun |
| PHYSICAL | 物理 | Force | Drake, Raptor, Femme, Grave, Foul | Empress, Chariot, Justice, Temperance, World, Fool |
| HOLYLIGHT | 神聖 | Light | Divine, Snake, Beast, Brute | Priestess, Hierophant, Strength, Fortune, Judgment |
| EVILDARK | 暗黒 | Dark | Night, Fallen, Wilder, Haunt, Spirit, Karma | Hangedman, Death, Devil, Tower, Moon |

**PHYSICAL versus physical attacks:** `PHYSICAL` is a PSX *type label* whose
PSP-US name is **Force**. It includes the Electric, Nuclear, Gravity, and
Blast subtypes below. It is not automatically the same thing as the physical
attacks described by Japanese `ぶつりこうげき`. Context matters: do not
replace one with the other merely because both involve 物理.

## Subtypes

Each non-Normal type has four subtypes. Normal has Normal as its subtype.
Rows are aligned by the supplied source's mapping, not by visual column order
in the game's own data.

| Type (PSP US) | PSX label | PSP Japanese | PSP US |
|---|---|---|---|
| Element | IGNIS | 火炎 | Fire |
| Element | AQUA | 氷結 | Ice |
| Element | AIR | 疾風 | Wind |
| Element | TERRA | 地震 | Earth |
| Force | PHOTON | 電撃 | Electric |
| Force | GREWON | 核熱 | Nuclear |
| Force | GRAVITON | 重力 | Gravity |
| Force | WEAKBOSON | 衝撃 | Blast |
| Light | EXORCISM | 破魔 | Expel |
| Light | SIGN | 天啓 | Prayer |
| Light | BLESS | 祝福 | Bless |
| Light | WONDER | 奇跡 | Miracle |
| Dark | CURSE | 呪殺 | Death |
| Dark | AWAKE | 覚醒 | Occult |
| Dark | NERVE | 神経 | Nerve |
| Dark | NECROMANCY | 降魔 | Curse |

**CURSE is a particularly easy false friend:** the source maps PSX subtype
`CURSE` to PSP-US **Death**, while PSP-US **Curse** corresponds to PSX
`NECROMANCY`. Do not match these solely by identical English spelling.

The supplied screenshot lists these opposing subtype pairs: Fire–Ice,
Wind–Earth, Electric–Nuclear, and Gravity–Blast. It lists Element–Force and
Light–Dark as opposing type pairs. These pairings are reference information,
not a substitute for the specific Japanese text being localized.

## Other element terms

The supplied minor-elements page lists these Japanese and English terms for
Megami Ibunroku Persona. They are useful search terms; they do not establish
that every Japanese affinity phrase maps to exactly one listed element.

| Japanese | English term in supplied source |
|---|---|
| 対ボ | Anti-Boss |
| 弓矢 | Arrow |
| 祝福 | Bless |
| 降魔 | Curse |
| 拳闘具 | Fist |
| 重力 | Gravity |
| ハンドガン | Handgun |
| マシンガン | Machine Gun |
| 奇跡 | Miracle |
| 覚醒 | Occult |
| 天啓 | Prayer |
| ライフル | Rifle |
| ショットガン | Shotgun |
| 片手剣 | Sword |
| 両手剣 | Two-Hand |
| 鞭 | Whip |

The source also discusses non-elemental attacks, but explicitly marks their
classification as needing research. Do not treat that entry as verified.

## Reported mechanics: verify before relying on them

The supplied wiki describes general tendencies, with exceptions:

- Element and Force resist their own type and are weak to each other.
- Light and Dark resist Element, Force, and their own type, but are weak to
  each other and physical attacks.
- Element and Force subtypes greatly resist their own subtype and are weak to
  its opposite; Light and Dark subtypes may add other resistances and
  weaknesses.
- Fusion outcomes and skill inheritance can also depend on type or subtype.

These are broad claims, not a complete description of each individual target.
In particular, the PSX Japanese affinity description, PSP-US description, and
actual PSX battle behavior may disagree. For example, the PSX line
`ぶつりこうげきをはんしゃ` says physical attacks are reflected, while its
corresponding PSP-US line says `Repel: 50% Physical` and `Weak: Magic`.
That difference does not, by itself, prove either game's actual combat
behavior. Preserve the distinction when researching or writing a description.

The manual worklist is `translation/manual/SLPS_005.00.tsv`; its affinity
rows contain the PSX Japanese and PSP-US source texts in their notes.
