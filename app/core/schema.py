"""Prediction-market target schema + legacy (single target_wallet) config seed."""

from typing import Optional

from app.targets import GROUP_ADVANCED, VENUE_PREDICTIONS, Field, VenueSchema

MODE_FIXED = "fixed"
MODE_PERCENT = "percent_of_target"

PREDICTIONS_SCHEMA = VenueSchema(
    id=VENUE_PREDICTIONS,
    label="Prediction markets",
    wallet_label="Polymarket wallet",
    wallet_placeholder="0x… (proxy wallet from the trader's profile)",
    close_label="Mirror sells",
    fields=(
        Field(
            key="mode", label="Sizing mode", type="select", default=MODE_FIXED,
            options=((MODE_FIXED, "Fixed USD per copy"), (MODE_PERCENT, "Percent of target's spend")),
        ),
        Field(
            key="fixed_usd_per_fill", label="Order size", type="number", default=10.0,
            min=0.01, step=0.5, unit="USD", show_if=("mode", MODE_FIXED),
            help="USD spent on each copied buy.",
        ),
        Field(
            key="percent_of_target", label="Percent of target", type="number", default=5.0,
            min=0.01, max=100.0, step=0.5, unit="%", show_if=("mode", MODE_PERCENT),
            help="Share of the target's USD spend on each batched chunk.",
        ),
        Field(
            key="max_open_usd", label="Max open exposure", type="number", default=100.0,
            min=1.0, step=10.0, unit="USD",
            help="Cap on the cost basis of this target's open positions.",
        ),
        Field(
            key="min_target_shares_to_copy", label="Batch threshold", type="number", default=10.0,
            min=0.01, step=1.0, unit="shares", group=GROUP_ADVANCED,
            help="Accumulate the target's buys per market until this many shares, then copy. "
                 "Use ~1 for short-lived markets.",
        ),
    ),
)


def legacy_seed(cfg: dict) -> Optional[dict]:
    """Translate the pre-multi-target config (target_wallet + sizing) into a
    single target entry, so existing configs keep working unchanged."""
    wallet = cfg.get("target_wallet")
    if not wallet:
        return None
    sizing = cfg.get("sizing") or {}
    seed_sizing = {
        "mode": sizing.get("mode", MODE_FIXED),
        "fixed_usd_per_fill": sizing.get("fixed_usd_per_fill", 10.0),
        # Legacy stored a fraction (0.05); the schema uses percent (5).
        "percent_of_target": float(sizing.get("percent_of_target", 0.05)) * 100,
        "max_open_usd": sizing.get("max_usd_total_in_positions", 100.0),
        "min_target_shares_to_copy": sizing.get("min_target_shares_to_copy", 10.0),
    }
    return {
        "name": "default",
        "venue": VENUE_PREDICTIONS,
        "wallet": wallet,
        "enabled": True,
        "copy_closes": (cfg.get("execution") or {}).get("copy_sells", True),
        "sizing": seed_sizing,
    }
