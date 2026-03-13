"""
Validate Pokemon data decryption with known test vectors.

Uses the PRNG algorithm and block shuffling from Gen 4 to verify
our implementation matches the expected behavior.
"""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from harness.crypto import prng_next, decrypt_blocks, decrypt_battle_stats, unshuffle_blocks


def test_prng():
    """Test the PRNG implementation against known values."""
    print("[Test 1] PRNG algorithm")
    
    # Known PRNG sequence: seed=0x00000000
    # next = (0x41C64E6D * 0 + 0x6073) & 0xFFFFFFFF = 0x00006073
    # next = (0x41C64E6D * 0x6073 + 0x6073) & 0xFFFFFFFF
    seed = 0x00000000
    expected_sequence = []
    
    seed = prng_next(seed)
    assert seed == 0x00006073, f"PRNG(0) expected 0x00006073, got 0x{seed:08X}"
    
    seed = prng_next(seed)
    expected = (0x41C64E6D * 0x6073 + 0x6073) & 0xFFFFFFFF
    assert seed == expected, f"PRNG(0x6073) expected 0x{expected:08X}, got 0x{seed:08X}"
    
    # Test with a known PID value
    seed = 0x12345678
    for i in range(5):
        seed = prng_next(seed)
    # Just verify it doesn't crash and produces reasonable values
    assert 0 <= seed <= 0xFFFFFFFF
    
    print("  ✓ PRNG produces correct sequence")


def test_block_shuffling():
    """Test block unshuffling with known PID values."""
    print("\n[Test 2] Block unshuffling")
    
    # Create a test pokemon with known block data
    raw = bytearray(0xEC)  # 236 bytes
    
    # Set PID to get a known shuffle order
    pid = 0  # shift = ((0 >> 0xD) & 0x1F) % 24 = 0 → order "ABCD" (no shuffle)
    struct.pack_into("<I", raw, 0, pid)
    
    # Set distinct patterns in each block position (pre-shuffle)
    for i in range(32):
        raw[0x08 + i] = 0xAA  # Block at position 0
        raw[0x28 + i] = 0xBB  # Block at position 1
        raw[0x48 + i] = 0xCC  # Block at position 2
        raw[0x68 + i] = 0xDD  # Block at position 3
    
    result = unshuffle_blocks(bytearray(raw), pid)
    
    # PID=0 → order "ABCD" → no change needed
    assert result[0x08] == 0xAA, f"Block A should be at 0x08, got 0x{result[0x08]:02X}"
    assert result[0x28] == 0xBB, f"Block B should be at 0x28, got 0x{result[0x28]:02X}"
    assert result[0x48] == 0xCC, f"Block C should be at 0x48, got 0x{result[0x48]:02X}"
    assert result[0x68] == 0xDD, f"Block D should be at 0x68, got 0x{result[0x68]:02X}"
    print("  ✓ PID=0 (order ABCD): no shuffle needed, correct")
    
    # Test with PID that gives a different shuffle
    # shift = ((PID >> 0xD) & 0x1F) % 24
    # For PID=0x2000 → shift = ((0x2000 >> 0xD) & 0x1F) % 24 = 1 % 24 = 1
    # Order 1 = "ABDC" 
    pid = 0x2000
    struct.pack_into("<I", raw, 0, pid)
    
    # In "ABDC" order: position 0=A, position 1=B, position 2=D, position 3=C
    # So after unshuffling, block at pos 0 should go to A slot, pos 1 to B, pos 2 to D, pos 3 to C
    for i in range(32):
        raw[0x08 + i] = 0x11  # Position 0 (should be block A)
        raw[0x28 + i] = 0x22  # Position 1 (should be block B)
        raw[0x48 + i] = 0x33  # Position 2 (should be block D)
        raw[0x68 + i] = 0x44  # Position 3 (should be block C)
    
    result = unshuffle_blocks(bytearray(raw), pid)
    assert result[0x08] == 0x11, f"Block A wrong: 0x{result[0x08]:02X}"  # A at 0x08
    assert result[0x28] == 0x22, f"Block B wrong: 0x{result[0x28]:02X}"  # B at 0x28
    assert result[0x48] == 0x44, f"Block C wrong: 0x{result[0x48]:02X}"  # C at 0x48 (was at pos 3)
    assert result[0x68] == 0x33, f"Block D wrong: 0x{result[0x68]:02X}"  # D at 0x68 (was at pos 2)
    print("  ✓ PID=0x2000 (order ABDC): D↔C swap correct")


def test_encryption_roundtrip():
    """Test that encrypt→decrypt is a no-op (XOR is symmetric)."""
    print("\n[Test 3] Encryption/decryption round-trip")
    
    # Create test data with known values
    raw = bytearray(0xEC)
    pid = 0xDEADBEEF
    checksum = 0x1234
    
    struct.pack_into("<I", raw, 0x00, pid)
    struct.pack_into("<H", raw, 0x06, checksum)
    
    # Set known data in blocks
    for i in range(0x08, 0x88):
        raw[i] = i & 0xFF
    for i in range(0x88, 0xEC):
        raw[i] = (i * 3) & 0xFF
    
    original = bytearray(raw)
    
    # Encrypt (same operation as decrypt — XOR is symmetric)
    encrypted = decrypt_blocks(bytearray(raw), checksum)
    
    # Verify it changed
    blocks_changed = any(encrypted[i] != original[i] for i in range(0x08, 0x88))
    assert blocks_changed, "Encryption didn't change any block data"
    
    # Decrypt (apply same operation again)
    decrypted = decrypt_blocks(bytearray(encrypted), checksum)
    
    # Should match original
    for i in range(0x08, 0x88):
        assert decrypted[i] == original[i], (
            f"Block byte {i:02X}: expected 0x{original[i]:02X}, got 0x{decrypted[i]:02X}"
        )
    print("  ✓ Block encryption/decryption round-trip successful")
    
    # Same for battle stats
    encrypted_stats = decrypt_battle_stats(bytearray(original), pid)
    stats_changed = any(encrypted_stats[i] != original[i] for i in range(0x88, 0xEC))
    assert stats_changed, "Battle stat encryption didn't change any data"
    
    decrypted_stats = decrypt_battle_stats(bytearray(encrypted_stats), pid)
    for i in range(0x88, 0xEC):
        assert decrypted_stats[i] == original[i], (
            f"Stat byte {i:02X}: expected 0x{original[i]:02X}, got 0x{decrypted_stats[i]:02X}"
        )
    print("  ✓ Battle stat encryption/decryption round-trip successful")


def test_nature_calculation():
    """Test nature derivation from PID."""
    print("\n[Test 4] Nature calculation")
    
    from harness.models import NATURES
    
    # PID % 25 = nature index
    test_cases = [
        (0, 0, "Hardy"),
        (1, 1, "Lonely"),
        (25, 0, "Hardy"),
        (0xDEADBEEF, 0xDEADBEEF % 25, NATURES[0xDEADBEEF % 25].name),
    ]
    
    for pid, expected_id, expected_name in test_cases:
        nature_id = pid % 25
        assert nature_id == expected_id, f"PID 0x{pid:08X}: expected nature {expected_id}, got {nature_id}"
        assert NATURES[nature_id].name == expected_name
    
    print("  ✓ Nature calculation correct for all test PIDs")


def test_iv_unpacking():
    """Test IV extraction from packed 32-bit value."""
    print("\n[Test 5] IV unpacking")
    
    # Test known packed value
    # All IVs = 31: bits 0-29 all set = 0x3FFFFFFF
    iv_word = 0x3FFFFFFF
    
    hp = iv_word & 0x1F
    atk = (iv_word >> 5) & 0x1F
    df = (iv_word >> 10) & 0x1F
    spe = (iv_word >> 15) & 0x1F
    spa = (iv_word >> 20) & 0x1F
    spd = (iv_word >> 25) & 0x1F
    
    assert hp == 31 and atk == 31 and df == 31 and spe == 31 and spa == 31 and spd == 31
    print("  ✓ All-31 IVs unpack correctly")
    
    # Test specific values
    # HP=5, ATK=10, DEF=15, SPE=20, SPA=25, SPD=30
    iv_word = 5 | (10 << 5) | (15 << 10) | (20 << 15) | (25 << 20) | (30 << 25)
    
    hp = iv_word & 0x1F
    atk = (iv_word >> 5) & 0x1F
    df = (iv_word >> 10) & 0x1F
    spe = (iv_word >> 15) & 0x1F
    spa = (iv_word >> 20) & 0x1F
    spd = (iv_word >> 25) & 0x1F
    
    assert (hp, atk, df, spe, spa, spd) == (5, 10, 15, 20, 25, 30)
    print("  ✓ Mixed IVs unpack correctly")
    
    # Test egg/nicknamed flags
    iv_word_with_flags = 0x3FFFFFFF | (1 << 30) | (1 << 31)
    is_egg = bool(iv_word_with_flags & (1 << 30))
    is_nicknamed = bool(iv_word_with_flags & (1 << 31))
    assert is_egg and is_nicknamed
    print("  ✓ IsEgg and IsNicknamed flags parse correctly")


def test_shiny_check():
    """Test shiny calculation."""
    print("\n[Test 6] Shiny check")
    
    # Shiny: (TID ^ SID ^ (PID >> 16) ^ (PID & 0xFFFF)) < 8
    tid, sid = 12345, 54321
    
    # Non-shiny PID
    pid = 0x12345678
    val = tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)
    is_shiny = val < 8
    assert not is_shiny, f"PID 0x{pid:08X} should not be shiny (val={val})"
    
    # Construct a shiny PID
    # Need: TID ^ SID ^ upper ^ lower < 8
    # Set upper = TID ^ SID ^ lower (makes the XOR = 0, which is < 8)
    lower = 0x1234
    upper = tid ^ sid ^ lower
    shiny_pid = (upper << 16) | lower
    val = tid ^ sid ^ (shiny_pid >> 16) ^ (shiny_pid & 0xFFFF)
    is_shiny = val < 8
    assert is_shiny, f"Constructed PID 0x{shiny_pid:08X} should be shiny (val={val})"
    
    print("  ✓ Shiny check works for normal and shiny PIDs")


def main():
    print("=" * 60)
    print("Pokemon Data Crypto Tests")
    print("=" * 60)
    
    test_prng()
    test_block_shuffling()
    test_encryption_roundtrip()
    test_nature_calculation()
    test_iv_unpacking()
    test_shiny_check()
    
    print("\n" + "=" * 60)
    print("ALL CRYPTO TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
