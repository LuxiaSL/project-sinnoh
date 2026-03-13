"""Gen 4 character encoding table.

Gen 4 NDS games (Diamond/Pearl/Platinum/HGSS) use a custom 16-bit character
encoding, NOT standard Unicode. Strings are terminated with 0xFFFF.

This table maps Gen 4 character codes to Unicode characters and vice versa.
Built from Bulbapedia's Gen IV character encoding documentation and verified
against in-game data (rival name "AAAAAAA" = 0x012B × 7).
"""

# Gen 4 char code → Unicode character
# Based on Bulbapedia Gen IV encoding tables
# Covers printable ASCII range + common special characters
_GEN4_TO_UNICODE: dict[int, str] = {
    # Digits 0-9: 0x0121-0x012A
    0x0121: "0", 0x0122: "1", 0x0123: "2", 0x0124: "3", 0x0125: "4",
    0x0126: "5", 0x0127: "6", 0x0128: "7", 0x0129: "8", 0x012A: "9",
    # Uppercase A-Z: 0x012B-0x0144
    0x012B: "A", 0x012C: "B", 0x012D: "C", 0x012E: "D", 0x012F: "E",
    0x0130: "F", 0x0131: "G", 0x0132: "H", 0x0133: "I", 0x0134: "J",
    0x0135: "K", 0x0136: "L", 0x0137: "M", 0x0138: "N", 0x0139: "O",
    0x013A: "P", 0x013B: "Q", 0x013C: "R", 0x013D: "S", 0x013E: "T",
    0x013F: "U", 0x0140: "V", 0x0141: "W", 0x0142: "X", 0x0143: "Y",
    0x0144: "Z",
    # Lowercase a-z: 0x0145-0x015E
    0x0145: "a", 0x0146: "b", 0x0147: "c", 0x0148: "d", 0x0149: "e",
    0x014A: "f", 0x014B: "g", 0x014C: "h", 0x014D: "i", 0x014E: "j",
    0x014F: "k", 0x0150: "l", 0x0151: "m", 0x0152: "n", 0x0153: "o",
    0x0154: "p", 0x0155: "q", 0x0156: "r", 0x0157: "s", 0x0158: "t",
    0x0159: "u", 0x015A: "v", 0x015B: "w", 0x015C: "x", 0x015D: "y",
    0x015E: "z",
    # Punctuation and special characters (save block / name entry)
    0x0000: " ",  # space (save block context)
    0x00A5: "…",  # ellipsis
    0x00B0: "♂",  # male sign
    0x00B1: "♀",  # female sign
    0x00B2: "♠",
    0x00B3: "♣",
    0x00B4: "♥",
    0x00B5: "♦",
    0x00B6: "★",
    0x00B7: "◎",
    0x00B8: "○",
    0x00B9: "□",
    0x00BA: "△",
    0x00BB: "◇",
    0x00E8: "!",
    0x00E9: "?",
    0x00EA: ".",
    0x00EB: "-",
    0x00F1: "&",
    0x00F5: "+",
    0x015F: "!",
    0x0160: "?",
    0x0161: ",",
    0x0162: ".",
    0x0163: "…",
    0x0164: "·",
    0x0165: "/",
    0x0166: "'",
    0x0167: "'",
    0x0168: '"',
    0x0169: '"',
    0x016A: "(",
    0x016B: ")",
    0x016E: "+",
    0x016F: "-",
    0x0170: "*",
    0x0171: "#",
    0x0172: "=",
    0x0173: "&",
    0x0174: "~",
    0x0175: ":",
    0x0176: ";",
    # Message text punctuation — from PKHeX StringConverter4Util.cs TableINT
    # Range 0x0180-0x019F: accented lowercase (à-ÿ, Œ, œ, Ş, ş, etc.)
    0x0188: "é",  # Pokémon accent (confirmed)
    # Range 0x01A0-0x01AF: symbols and punctuation
    0x01A0: "œ", 0x01A1: "Ş", 0x01A2: "ş",
    0x01A3: "ª", 0x01A4: "º",
    0x01A8: "$", 0x01A9: "¡", 0x01AA: "¿",
    0x01AB: "!",  # exclamation mark (NOT apostrophe — was wrong!)
    0x01AC: "?",  # question mark (NOT apostrophe — was wrong!)
    0x01AD: ",",  # comma
    0x01AE: ".",  # period
    # Range 0x01B0-0x01BF: more punctuation
    0x01B0: "·", 0x01B1: "/",
    0x01B2: "'",  # right single quote / apostrophe
    0x01B3: "'",  # apostrophe (contractions: I'm, you'll)
    0x01B4: '"',  # left double quote
    0x01B5: '"',  # right double quote
    0x01B6: "„",  # low double quote
    0x01B7: "«",  # left guillemet
    0x01B8: "»",  # right guillemet
    0x01B9: "(",  # opening paren
    0x01BA: ")",  # closing paren
    # Range 0x01C0-0x01CF: more symbols
    0x01BD: "+", 0x01BE: "-", 0x01BF: "*",
    0x01C0: "#", 0x01C1: "=", 0x01C2: "&",
    0x01C3: "~", 0x01C4: ":", 0x01C5: ";",
    0x01D0: "@", 0x01D2: "%",
    0x01DE: " ",  # SPACE in message text (confirmed)
    # Common symbols
    0x0190: "/",
    0x0191: "\\",
    # Control codes mapped to readable characters
    0xE000: "\n",  # newline in dialogue
    0x25BC: "\n",  # clear screen (page break)
    # 0x25BD = scroll up (skipped in dialogue reader)
    # 0xFFFE = format placeholder (variable substitution)
    # 0xFFFF = terminator
}

# Reverse mapping: Unicode char → Gen 4 code
_UNICODE_TO_GEN4: dict[str, int] = {}
for _code, _char in _GEN4_TO_UNICODE.items():
    if _char not in _UNICODE_TO_GEN4:
        _UNICODE_TO_GEN4[_char] = _code

# Use the primary mappings for common chars
_UNICODE_TO_GEN4.update({
    " ": 0x0000,
    "A": 0x012B, "B": 0x012C, "C": 0x012D, "D": 0x012E, "E": 0x012F,
    "F": 0x0130, "G": 0x0131, "H": 0x0132, "I": 0x0133, "J": 0x0134,
    "K": 0x0135, "L": 0x0136, "M": 0x0137, "N": 0x0138, "O": 0x0139,
    "P": 0x013A, "Q": 0x013B, "R": 0x013C, "S": 0x013D, "T": 0x013E,
    "U": 0x013F, "V": 0x0140, "W": 0x0141, "X": 0x0142, "Y": 0x0143,
    "Z": 0x0144,
})

TERMINATOR = 0xFFFF


def decode_gen4_string(char_codes: list[int]) -> str:
    """Decode a list of Gen 4 character codes to a Python string."""
    result: list[str] = []
    for code in char_codes:
        if code == TERMINATOR:
            break
        char = _GEN4_TO_UNICODE.get(code)
        if char is not None:
            result.append(char)
        elif code == 0:
            # Skip null bytes (padding after terminator)
            continue
        else:
            result.append(f"?{code:04X}")
    return "".join(result)


def encode_gen4_string(text: str, max_len: int = 8) -> list[int]:
    """Encode a Python string to Gen 4 character codes (with terminator)."""
    codes: list[int] = []
    for char in text[:max_len]:
        code = _UNICODE_TO_GEN4.get(char)
        if code is not None:
            codes.append(code)
        else:
            # Unknown character, skip or use space
            codes.append(0x0000)
    codes.append(TERMINATOR)
    return codes
