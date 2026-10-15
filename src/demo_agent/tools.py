"""Tools the demo agent can call, plus their JSON schemas.

Two parts:
- the implementations (`TOOL_IMPLS`), which always use the canonical argument
  names (order_id, category);
- the schemas shown to the model (`tool_schemas`). Variants of the schema let us
  seed "changed tool schema" regressions: the model follows the schema, the
  implementation does not change, so calls break.
"""

from __future__ import annotations

from .data import ORDERS, POLICIES, money


def lookup_order(order_id: str) -> dict:
    o = ORDERS.get(order_id)
    if o is None:
        return {"error": "not_found", "order_id": order_id}
    return {"order_id": order_id, "items": o["items"], "total": o["total"], "category": o["category"], "status": o["status"]}


def track_shipment(order_id: str) -> dict:
    o = ORDERS.get(order_id)
    if o is None:
        return {"error": "not_found", "order_id": order_id}
    return {"order_id": order_id, "status": o["status"], "carrier": o.get("carrier"), "eta": o.get("eta"), "delivered_days_ago": o.get("delivered_days_ago")}


def calc_refund(order_id: str) -> dict:
    o = ORDERS.get(order_id)
    if o is None:
        return {"error": "not_found", "order_id": order_id}
    window, fee = POLICIES[o["category"]]
    ago = o.get("delivered_days_ago")
    if ago is None:  # not delivered yet: can be cancelled for the full price
        amount, eligible = o["total"], True
    else:
        eligible = window > 0 and ago <= window
        amount = round(o["total"] * (1 - fee), 2) if eligible else 0.0
    return {"order_id": order_id, "category": o["category"], "eligible": eligible, "refund_amount": amount, "refund_text": money(amount)}


def check_refund_policy(category: str) -> dict:
    """Tiny retrieval step: look up the policy text for a category."""
    pol = POLICIES.get(category.lower())
    if pol is None:
        return {"error": "unknown_category", "category": category}
    days, fee = pol
    return {"category": category.lower(), "return_days": days, "restocking_fee": fee}


TOOL_IMPLS = {
    "lookup_order": lookup_order,
    "track_shipment": track_shipment,
    "calc_refund": calc_refund,
    "check_refund_policy": check_refund_policy,
}

# tools whose spans are "retrieval" rather than "tool"
RETRIEVAL_TOOLS = {"check_refund_policy"}


def _schema(name: str, description: str, arg: str, arg_desc: str) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": {arg: {"type": "string", "description": arg_desc}}, "required": [arg]},
    }


def tool_schemas(variant: str = "v1") -> list[dict]:
    """Schemas shown to the model.

    Variants (used to seed regressions):
      v1                    correct schemas
      renamed_order_id      order tools now say `id` instead of `order_id`
      dropped_calc_refund   the refund calculator is no longer offered
      renamed_policy_arg    policy tool now says `item_type` instead of `category`
    """
    order_arg = "id" if variant == "renamed_order_id" else "order_id"
    policy_arg = "item_type" if variant == "renamed_policy_arg" else "category"
    schemas = [
        _schema("lookup_order", "Get items, total and status of an order.", order_arg, "Order id like ORD-1001"),
        _schema("track_shipment", "Get carrier and delivery status of an order.", order_arg, "Order id like ORD-1001"),
        _schema("calc_refund", "Compute the refund amount for returning an order.", order_arg, "Order id like ORD-1001"),
        _schema("check_refund_policy", "Get the return window for a product category.", policy_arg, "electronics, clothing, grocery, books or furniture"),
    ]
    if variant == "dropped_calc_refund":
        schemas = [s for s in schemas if s["name"] != "calc_refund"]
    return schemas
