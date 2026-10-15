"""Synthetic shop data for the demo agent.

Everything here is invented. No employer or customer data. The golden dataset
facts are generated from these tables, so expected answers are correct by
construction.
"""

from __future__ import annotations

ORDERS: dict[str, dict] = {
    "ORD-1001": dict(items=["Wireless Earbuds", "Phone Case"], total=89.98, category="electronics", status="delivered", carrier="BlueDart", delivered_days_ago=5),
    "ORD-1002": dict(items=["Running Shoes"], total=64.50, category="clothing", status="delivered", carrier="Leopards", delivered_days_ago=12),
    "ORD-1003": dict(items=["Basmati Rice 5kg", "Green Tea"], total=31.20, category="grocery", status="shipped", carrier="TCS", eta="2026-10-20"),
    "ORD-1004": dict(items=["Python Cookbook"], total=42.00, category="books", status="delivered", carrier="Leopards", delivered_days_ago=3),
    "ORD-1005": dict(items=["Standing Desk"], total=349.00, category="furniture", status="delivered", carrier="TCS", delivered_days_ago=20),
    "ORD-1006": dict(items=["Laptop Sleeve", "USB-C Hub"], total=75.49, category="electronics", status="processing", carrier=None),
    "ORD-1007": dict(items=["Denim Jacket"], total=58.00, category="clothing", status="shipped", carrier="BlueDart", eta="2026-10-22"),
    "ORD-1008": dict(items=["Novel Set"], total=27.99, category="books", status="delivered", carrier="TCS", delivered_days_ago=40),
    "ORD-1009": dict(items=["Smart Watch"], total=199.99, category="electronics", status="delivered", carrier="BlueDart", delivered_days_ago=20),
    "ORD-1010": dict(items=["Office Chair"], total=189.00, category="furniture", status="shipped", carrier="Leopards", eta="2026-10-25"),
}

# category -> (return window in days, restocking fee fraction)
POLICIES: dict[str, tuple[int, float]] = {
    "electronics": (15, 0.10),
    "clothing": (30, 0.0),
    "grocery": (0, 0.0),  # 0 days == non-returnable
    "books": (14, 0.0),
    "furniture": (30, 0.15),
}


def money(x: float) -> str:
    return f"${x:,.2f}"
