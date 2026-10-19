from app.demo_data import load_demo_store


def test_demo_store_is_synthetic_and_covers_multiple_customers() -> None:
    store = load_demo_store()
    customer_ids = {c.id for c in store.customers}
    assert len(customer_ids) >= 2
    assert all(o.customer_id in customer_ids for o in store.orders)
    assert all(c.display_name.startswith("Demo Customer") for c in store.customers)
    statuses = {o.status for o in store.orders}
    assert {"processing", "shipped", "delivered"} <= statuses
