"""Pokemon evolution levels for Gen 4.

Maps species ID -> level at which it evolves (level-up evolutions only).
Species that evolve by stone, trade, happiness, etc. are NOT included.
"""

from __future__ import annotations

# species_id -> evolution_level
EVOLUTION_LEVELS: dict[int, int] = {
    # Gen 1 ------------------------------------------------------------------
    1: 16,      # Bulbasaur -> Ivysaur
    2: 32,      # Ivysaur -> Venusaur
    4: 16,      # Charmander -> Charmeleon
    5: 36,      # Charmeleon -> Charizard
    7: 16,      # Squirtle -> Wartortle
    8: 36,      # Wartortle -> Blastoise
    10: 7,      # Caterpie -> Metapod
    11: 10,     # Metapod -> Butterfree
    13: 7,      # Weedle -> Kakuna
    14: 10,     # Kakuna -> Beedrill
    16: 18,     # Pidgey -> Pidgeotto
    17: 36,     # Pidgeotto -> Pidgeot
    19: 20,     # Rattata -> Raticate
    21: 20,     # Spearow -> Fearow
    23: 22,     # Ekans -> Arbok
    27: 22,     # Sandshrew -> Sandslash
    29: 16,     # Nidoran F -> Nidorina
    32: 16,     # Nidoran M -> Nidorino
    41: 22,     # Zubat -> Golbat
    43: 21,     # Oddish -> Gloom
    46: 24,     # Paras -> Parasect
    48: 31,     # Venonat -> Venomoth
    50: 26,     # Diglett -> Dugtrio
    52: 28,     # Meowth -> Persian
    54: 33,     # Psyduck -> Golduck
    56: 28,     # Mankey -> Primeape
    60: 25,     # Poliwag -> Poliwhirl
    63: 16,     # Abra -> Kadabra
    66: 28,     # Machop -> Machoke
    69: 21,     # Bellsprout -> Weepinbell
    72: 30,     # Tentacool -> Tentacruel
    74: 25,     # Geodude -> Graveler
    77: 40,     # Ponyta -> Rapidash
    79: 37,     # Slowpoke -> Slowbro
    81: 30,     # Magnemite -> Magneton
    84: 31,     # Doduo -> Dodrio
    86: 34,     # Seel -> Dewgong
    88: 38,     # Grimer -> Muk
    92: 25,     # Gastly -> Haunter
    96: 26,     # Drowzee -> Hypno
    98: 28,     # Krabby -> Kingler
    100: 30,    # Voltorb -> Electrode
    104: 28,    # Cubone -> Marowak
    109: 35,    # Koffing -> Weezing
    111: 42,    # Rhyhorn -> Rhydon
    116: 32,    # Horsea -> Seadra
    118: 33,    # Goldeen -> Seaking
    129: 20,    # Magikarp -> Gyarados
    138: 40,    # Omanyte -> Omastar
    140: 40,    # Kabuto -> Kabutops
    147: 30,    # Dratini -> Dragonair
    148: 55,    # Dragonair -> Dragonite
    # Gen 2 ------------------------------------------------------------------
    152: 16,    # Chikorita -> Bayleef
    153: 32,    # Bayleef -> Meganium
    155: 14,    # Cyndaquil -> Quilava
    156: 36,    # Quilava -> Typhlosion
    158: 18,    # Totodile -> Croconaw
    159: 30,    # Croconaw -> Feraligatr
    161: 15,    # Sentret -> Furret
    163: 20,    # Hoothoot -> Noctowl
    165: 18,    # Ledyba -> Ledian
    167: 22,    # Spinarak -> Ariados
    170: 27,    # Chinchou -> Lanturn
    177: 25,    # Natu -> Xatu
    179: 15,    # Mareep -> Flaaffy
    180: 30,    # Flaaffy -> Ampharos
    183: 18,    # Marill -> Azumarill
    194: 20,    # Wooper -> Quagsire
    204: 31,    # Pineco -> Forretress
    209: 23,    # Snubbull -> Granbull
    218: 38,    # Slugma -> Magcargo
    220: 33,    # Swinub -> Piloswine
    228: 24,    # Houndour -> Houndoom
    231: 25,    # Phanpy -> Donphan
    246: 30,    # Larvitar -> Pupitar
    247: 55,    # Pupitar -> Tyranitar
    # Gen 3 ------------------------------------------------------------------
    252: 16,    # Treecko -> Grovyle
    253: 36,    # Grovyle -> Sceptile
    255: 16,    # Torchic -> Combusken
    256: 36,    # Combusken -> Blaziken
    258: 16,    # Mudkip -> Marshtomp
    259: 36,    # Marshtomp -> Swampert
    261: 18,    # Poochyena -> Mightyena
    263: 20,    # Zigzagoon -> Linoone
    265: 7,     # Wurmple -> Silcoon/Cascoon
    266: 10,    # Silcoon -> Beautifly
    268: 10,    # Cascoon -> Dustox
    270: 14,    # Lotad -> Lombre
    273: 14,    # Seedot -> Nuzleaf
    276: 22,    # Taillow -> Swellow
    278: 25,    # Wingull -> Pelipper
    280: 20,    # Ralts -> Kirlia
    281: 30,    # Kirlia -> Gardevoir
    283: 22,    # Surskit -> Masquerain
    285: 23,    # Shroomish -> Breloom
    287: 18,    # Slakoth -> Vigoroth
    288: 36,    # Vigoroth -> Slaking
    290: 20,    # Nincada -> Ninjask (+ Shedinja)
    293: 20,    # Whismur -> Loudred
    294: 40,    # Loudred -> Exploud
    296: 24,    # Makuhita -> Hariyama
    304: 32,    # Aron -> Lairon
    305: 42,    # Lairon -> Aggron
    307: 37,    # Meditite -> Medicham
    309: 26,    # Electrike -> Manectric
    316: 26,    # Gulpin -> Swalot
    318: 30,    # Carvanha -> Sharpedo
    320: 40,    # Wailmer -> Wailord
    322: 33,    # Numel -> Camerupt
    325: 32,    # Spoink -> Grumpig
    328: 35,    # Trapinch -> Vibrava
    329: 45,    # Vibrava -> Flygon
    331: 32,    # Cacnea -> Cacturne
    333: 35,    # Swablu -> Altaria
    339: 30,    # Barboach -> Whiscash
    341: 30,    # Corphish -> Crawdaunt
    343: 36,    # Baltoy -> Claydol
    345: 40,    # Lileep -> Cradily
    347: 40,    # Anorith -> Armaldo
    353: 37,    # Shuppet -> Banette
    355: 37,    # Duskull -> Dusclops
    360: 15,    # Wynaut -> Wobbuffet
    361: 42,    # Snorunt -> Glalie
    363: 32,    # Spheal -> Sealeo
    364: 44,    # Sealeo -> Walrein
    371: 30,    # Bagon -> Shelgon
    372: 50,    # Shelgon -> Salamence
    374: 20,    # Beldum -> Metang
    375: 45,    # Metang -> Metagross
    # Gen 4 ------------------------------------------------------------------
    387: 18,    # Turtwig -> Grotle
    388: 32,    # Grotle -> Torterra
    390: 14,    # Chimchar -> Monferno
    391: 36,    # Monferno -> Infernape
    393: 16,    # Piplup -> Prinplup
    394: 36,    # Prinplup -> Empoleon
    396: 14,    # Starly -> Staravia
    397: 34,    # Staravia -> Staraptor
    399: 15,    # Bidoof -> Bibarel
    401: 10,    # Kricketot -> Kricketune
    403: 15,    # Shinx -> Luxio
    404: 30,    # Luxio -> Luxray
    408: 30,    # Cranidos -> Rampardos
    410: 30,    # Shieldon -> Bastiodon
    412: 20,    # Burmy -> Wormadam/Mothim
    418: 26,    # Buizel -> Floatzel
    420: 25,    # Cherubi -> Cherrim
    422: 30,    # Shellos -> Gastrodon
    425: 28,    # Drifloon -> Drifblim
    431: 38,    # Glameow -> Purugly
    434: 34,    # Stunky -> Skuntank
    436: 33,    # Bronzor -> Bronzong
    443: 24,    # Gible -> Gabite
    444: 48,    # Gabite -> Garchomp
    449: 34,    # Hippopotas -> Hippowdon
    451: 40,    # Skorupi -> Drapion
    453: 37,    # Croagunk -> Toxicroak
    459: 40,    # Snover -> Abomasnow
}
