from roughcut.watcher.folder_watcher import _explicit_part_key, _has_explicit_part_continuity


def test_explicit_part_continuity_accepts_numbered_unboxing_series() -> None:
    left = {"source_name": "IMG_0172 Olight Predator 2mini unboxing part1.MOV"}
    right = {"source_name": "IMG_0174 Olight Predator 2mini unboxing part2.MOV"}

    assert _has_explicit_part_continuity(left, right)


def test_explicit_part_continuity_rejects_same_product_different_shoots() -> None:
    left = {"source_name": "IMG_0025 Foxbat FXX1 small bag unboxing.MOV"}
    right = {"source_name": "IMG_0181 Foxbat FXX1 Sunday strap update.MOV"}

    assert not _has_explicit_part_continuity(left, right)


def test_explicit_part_key_ignores_unnumbered_unboxing() -> None:
    assert _explicit_part_key("IMG_0025 Foxbat FXX1 small bag unboxing.MOV") is None
