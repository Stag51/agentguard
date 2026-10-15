"""Generate datasets/golden_v1.jsonl from the synthetic shop data.

WHY generate: expected facts (totals, carriers, return windows) are computed from
the same tables the tools read, so the expectations are correct by construction
and cannot drift from the data. The generated file is committed and reviewed like
any other dataset (ADR 0003). Run:  python -m demo_agent.make_golden
"""

from __future__ import annotations

import json
from pathlib import Path

from .data import ORDERS, POLICIES, money
from .tools import calc_refund


def _call(name: str, **args) -> dict:
    return {"name": name, "args": args}


def build_cases() -> list[dict]:
    cases: list[dict] = []

    def add(cid, tags, question, calls, facts, forbidden=(), rubric=None):
        cases.append({
            "id": cid, "tags": tags, "input": {"question": question},
            "expectations": {"tool_calls": calls, "forbidden_tools": list(forbidden), "required_facts": facts, "judge_rubric": rubric},
        })

    # order status (7)
    phr = ["Where is my order {o}?", "Can you track {o} for me?", "What's the status of order {o}?"]
    for i, oid in enumerate(["ORD-1001", "ORD-1003", "ORD-1006", "ORD-1007", "ORD-1008", "ORD-1010", "ORD-1004"]):
        o = ORDERS[oid]
        if o["status"] == "processing":
            facts = ["processing"]
        elif o["status"] == "shipped":
            facts = ["shipped", o["carrier"], o["eta"]]
        else:
            facts = ["delivered", o["carrier"]]
        add(f"status-{i+1:02d}", ["order_status"], phr[i % 3].format(o=oid), [_call("track_shipment", order_id=oid)], facts)

    # order details (6)
    for i, oid in enumerate(["ORD-1001", "ORD-1002", "ORD-1005", "ORD-1006", "ORD-1009", "ORD-1003"]):
        o = ORDERS[oid]
        add(f"details-{i+1:02d}", ["order_details"], f"What items are in {oid} and what was the total?",
            [_call("lookup_order", order_id=oid)], o["items"] + [money(o["total"])])

    # return policy (5)
    for i, cat in enumerate(["electronics", "clothing", "grocery", "books", "furniture"]):
        days, _ = POLICIES[cat]
        fact = "non-returnable" if days == 0 else f"{days} days"
        add(f"policy-{i+1:02d}", ["return_policy"], f"What is your return policy for {cat} items?",
            [_call("check_refund_policy", category=cat)], [fact])

    # refund amount: multi-step (5)
    for i, oid in enumerate(["ORD-1001", "ORD-1002", "ORD-1005", "ORD-1009", "ORD-1008"]):
        r = calc_refund(oid)
        days = POLICIES[ORDERS[oid]["category"]][0]
        add(f"refund-{i+1:02d}", ["refund", "multi_step"], f"How much refund would I get if I return {oid}?",
            [_call("calc_refund", order_id=oid), _call("check_refund_policy", category=ORDERS[oid]["category"])],
            [r["refund_text"], f"{days} days"])

    # unknown orders (2)
    add("unknown-01", ["not_found"], "Where is my order ORD-9999?", [_call("track_shipment", order_id="ORD-9999")], ["couldn't find"])
    add("unknown-02", ["not_found"], "What items are in ORD-4242 and what was the total?", [_call("lookup_order", order_id="ORD-4242")], ["couldn't find"])

    # out of scope: must refuse and call no tools (3)
    for i, q in enumerate(["What's the weather in Lahore today?", "Write me a poem about cats.", "Who won the cricket match yesterday?"]):
        add(f"oos-{i+1:02d}", ["out_of_scope", "refusal"], q, [], ["only help with orders"],
            forbidden=["lookup_order", "track_shipment", "calc_refund", "check_refund_policy"])

    # open-ended answers graded by the judge as well (2)
    rubric = "The answer explains the return window clearly, is accurate to the policy facts given, and is polite and not misleading."
    add("open-01", ["open_ended", "return_policy"], "Explain in simple words how returns work for electronics.",
        [_call("check_refund_policy", category="electronics")], ["15 days"], rubric=rubric)
    add("open-02", ["open_ended", "return_policy"], "Explain in simple words how returns work for furniture.",
        [_call("check_refund_policy", category="furniture")], ["30 days"], rubric=rubric)
    return cases


def main() -> None:
    cases = build_cases()
    out = Path("datasets/golden_v1.jsonl")
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {out}")


if __name__ == "__main__":
    main()
