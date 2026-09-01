from scripts.seed_demo import _demo_config, _demo_products


def test_large_demo_catalog_matches_configuration_and_has_unique_skus() -> None:
    config = _demo_config()
    products = _demo_products()

    expected = len(config["featured_products"]) + config["product_generation"]["count"]
    skus = [sku for sku, _name, _price in products]

    assert len(products) == expected
    assert len(products) >= 500
    assert len(skus) == len(set(skus))


def test_large_demo_transaction_volumes_are_intentionally_substantial() -> None:
    counts = _demo_config()["counts"]

    assert counts["customers"] >= 200
    assert counts["suppliers"] >= 100
    assert counts["leads"] >= 250
    assert counts["opportunities"] >= 150
    assert counts["sales_orders"] >= 500
    assert counts["purchase_orders"] >= 200
