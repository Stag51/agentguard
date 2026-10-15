"""Named agent versions used by the CLI and the seeded-regression experiment.

`REGRESSIONS` change behaviour for the worse and SHOULD be blocked by the gate.
`BENIGN` change wording or price but not quality and should NOT be blocked.
`base` is the reference version.
"""

from __future__ import annotations

from dataclasses import replace

from .agent import AgentConfig

BASE = AgentConfig(name="base")

REGRESSIONS: dict[str, AgentConfig] = {
    "R01_terse_prompt": replace(BASE, name="R01_terse_prompt", prompt="terse"),
    "R02_verbose_prompt": replace(BASE, name="R02_verbose_prompt", prompt="verbose"),
    "R03_schema_renamed_order_id": replace(BASE, name="R03_schema_renamed_order_id", tools="renamed_order_id"),
    "R04_schema_dropped_calc_refund": replace(BASE, name="R04_schema_dropped_calc_refund", tools="dropped_calc_refund"),
    "R05_cheaper_model": replace(BASE, name="R05_cheaper_model", model="cheap"),
    "R06_cheaper_model_terse": replace(BASE, name="R06_cheaper_model_terse", model="cheap", prompt="terse"),
    "R07_overeager_tools": replace(BASE, name="R07_overeager_tools", prompt="overeager"),
    "R08_no_refusal": replace(BASE, name="R08_no_refusal", prompt="no_refusal"),
    "R09_slow_model": replace(BASE, name="R09_slow_model", model="slow"),
    "R10_schema_renamed_policy_arg": replace(BASE, name="R10_schema_renamed_policy_arg", tools="renamed_policy_arg"),
    "R11_truncated_ids": replace(BASE, name="R11_truncated_ids", prompt="truncate_id"),
    "R12_cheaper_model_verbose": replace(BASE, name="R12_cheaper_model_verbose", model="cheap", prompt="verbose"),
}

BENIGN: dict[str, AgentConfig] = {
    "B01_polite_wording": replace(BASE, name="B01_polite_wording", prompt="polite"),
    "B02_equivalent_cheaper_model": replace(BASE, name="B02_equivalent_cheaper_model", model="base2"),
    "B03_shorter_prompt": replace(BASE, name="B03_shorter_prompt", prompt="concise_ok"),
    "B04_identical_rerun": replace(BASE, name="B04_identical_rerun"),
}

ALL: dict[str, AgentConfig] = {"base": BASE, **REGRESSIONS, **BENIGN}


def get_config(name: str, backend: str = "mock") -> AgentConfig:
    if name not in ALL:
        raise KeyError(f"unknown agent '{name}'. choices: {', '.join(ALL)}")
    return replace(ALL[name], backend=backend)
