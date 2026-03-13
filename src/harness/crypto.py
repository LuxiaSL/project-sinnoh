"""Gen 4 Pokemon data cryptography.

Handles PRNG-based encryption/decryption and block unshuffling
for the 236-byte Pokemon data structure used in Gen 4 games.

Reference: PKHeX PokeCrypto / PK4.cs
"""

from __future__ import annotations

# PRNG constants
PRNG_MULT = 0x41C64E6D
PRNG_ADD = 0x6073
PRNG_MASK = 0xFFFFFFFF

# Block shuffle table — 24 possible orderings based on PID
SHUFFLE_TABLE: list[str] = [
    "ABCD", "ABDC", "ACBD", "ACDB", "ADBC", "ADCB",
    "BACD", "BADC", "BCAD", "BCDA", "BDAC", "BDCA",
    "CABD", "CADB", "CBAD", "CBDA", "CDAB", "CDBA",
    "DABC", "DACB", "DBAC", "DBCA", "DCAB", "DCBA",
]

# Block positions in the 236-byte structure
BLOCK_START = 0x08
BLOCK_SIZE = 0x20  # 32 bytes per block
BLOCK_END = 0x88   # 4 blocks × 32 bytes = 128 bytes
BATTLE_STATS_START = 0x88
BATTLE_STATS_END = 0xEC


def prng_next(seed: int) -> int:
    """Gen 4 PRNG: linear congruential generator."""
    return (PRNG_MULT * seed + PRNG_ADD) & PRNG_MASK


def decrypt_blocks(raw: bytearray, checksum: int) -> bytearray:
    """Decrypt blocks A-D (bytes 0x08-0x87) using checksum as PRNG seed."""
    seed = checksum
    for i in range(BLOCK_START, BLOCK_END, 2):
        seed = prng_next(seed)
        xor_val = (seed >> 16) & 0xFFFF
        word = int.from_bytes(raw[i:i + 2], "little")
        word ^= xor_val
        raw[i:i + 2] = word.to_bytes(2, "little")
    return raw


def decrypt_battle_stats(raw: bytearray, pid: int) -> bytearray:
    """Decrypt battle stats (bytes 0x88-0xEB) using PID as PRNG seed."""
    seed = pid
    for i in range(BATTLE_STATS_START, BATTLE_STATS_END, 2):
        seed = prng_next(seed)
        xor_val = (seed >> 16) & 0xFFFF
        word = int.from_bytes(raw[i:i + 2], "little")
        word ^= xor_val
        raw[i:i + 2] = word.to_bytes(2, "little")
    return raw


def unshuffle_blocks(raw: bytearray, pid: int) -> bytearray:
    """Unshuffle blocks A-D based on PID to canonical ABCD order."""
    shift = ((pid >> 0xD) & 0x1F) % 24
    order = SHUFFLE_TABLE[shift]

    result = bytearray(raw)
    target_positions = {"A": 0x08, "B": 0x28, "C": 0x48, "D": 0x68}

    for i, block_letter in enumerate(order):
        src_start = BLOCK_START + i * BLOCK_SIZE
        dst_start = target_positions[block_letter]
        result[dst_start:dst_start + BLOCK_SIZE] = raw[src_start:src_start + BLOCK_SIZE]

    return result


def decrypt_pokemon(raw: bytearray) -> bytearray:
    """Full decryption pipeline for a 236-byte Pokemon structure.

    1. Extract PID and checksum from unencrypted header
    2. Decrypt blocks A-D using checksum as seed
    3. Unshuffle blocks to canonical ABCD order
    4. Decrypt battle stats using PID as seed

    Returns the fully decrypted bytearray.
    """
    pid = int.from_bytes(raw[0x00:0x04], "little")
    checksum = int.from_bytes(raw[0x06:0x08], "little")

    raw = decrypt_blocks(raw, checksum)
    raw = unshuffle_blocks(raw, pid)
    raw = decrypt_battle_stats(raw, pid)

    return raw
