from scripts.check_governed_assets import check


def test_受控数据资产哈希与保留策略未漂移() -> None:
    assert check() == []
