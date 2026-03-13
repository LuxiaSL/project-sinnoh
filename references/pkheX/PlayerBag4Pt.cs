// Source: https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Items/Bags/PlayerBag4Pt.cs
// Fetched 2026-03-08 — reconstructed from GitHub raw content

namespace PKHeX.Core;

/// <summary>
/// Player inventory (bag) for Pokémon Platinum.
/// </summary>
public sealed class PlayerBag4Pt : PlayerBag
{
    private const int BaseOffset = 0x630;

    // Offsets are relative to General + BaseOffset
    // Constructor args: (offset, maxCount, info, type)
    //   offset = byte offset from BaseOffset within General save block
    //   maxCount = max quantity per item slot
    //   info = ItemStorage4Pt.Instance (defines valid items per pouch)
    //   type = InventoryType enum

    // Pouch definitions:
    //   Items       @ 0x000, max 999  — GeneralPt items (207 valid IDs)
    //   KeyItems    @ 0x294, max 1    — KeyPt items (40 valid IDs)
    //   TMHMs       @ 0x35C, max 99   — Machine items (100 valid IDs, TM01-TM92 + HM01-HM08)
    //   MailItems   @ 0x4EC, max 999  — Mail items (12 valid IDs)
    //   Medicine    @ 0x51C, max 999  — Medicine items (38 valid IDs)
    //   Berries     @ 0x5BC, max 999  — Berry items (64 valid IDs)
    //   Balls       @ 0x6BC, max 999  — BallsDPPt items (15 valid IDs)
    //   BattleItems @ 0x6F8, max 999  — Battle items (13 valid IDs)

    // GetMaxCount override: HMs (checked via ItemConverter.IsItemHM4) are capped at 1 even though TMHMs max is 99.

    // Slot counts (PouchDataSize) default to info.GetItems(type).Length:
    //   Items       = 207 slots (0x33C bytes)
    //   KeyItems    =  40 slots (0x0A0 bytes)
    //   TMHMs       = 100 slots (0x190 bytes)
    //   MailItems   =  12 slots (0x030 bytes)
    //   Medicine    =  38 slots (0x098 bytes)
    //   Berries     =  64 slots (0x100 bytes)
    //   Balls       =  15 slots (0x03C bytes)
    //   BattleItems =  13 slots (0x034 bytes)

    // Each slot is 4 bytes: u16 itemID + u16 count (InventoryPouch4 format)
}
