"""Perps target schema (Polymarket Perps, api.perpetuals.polymarket.com)."""

from app.targets import VENUE_PERPS, Field, VenueSchema

MODE_PERCENT = "percent_of_target"
MODE_FIXED = "fixed_notional"

PERPS_SCHEMA = VenueSchema(
    id=VENUE_PERPS,
    label="Perps",
    wallet_label="Perps account",
    wallet_placeholder="0x… (account address from the Perps leaderboard / profile)",
    close_label="Mirror reductions & closes",
    fields=(
        Field(
            key="mode", label="Sizing mode", type="select", default=MODE_PERCENT,
            options=((MODE_PERCENT, "Percent of target's size"), (MODE_FIXED, "Fixed notional per entry")),
        ),
        Field(
            key="percent_of_target", label="Percent of target", type="number", default=10.0,
            min=0.01, max=1000.0, step=1.0, unit="%", show_if=("mode", MODE_PERCENT),
            help="Our size change = target's size change × this percent.",
        ),
        Field(
            key="fixed_notional_usd", label="Order size", type="number", default=50.0,
            min=1.0, step=10.0, unit="USD", show_if=("mode", MODE_FIXED),
            help="Each time the target opens or adds, open this much notional.",
        ),
        Field(
            key="max_open_notional_usd", label="Max open notional", type="number", default=500.0,
            min=1.0, step=50.0, unit="USD",
            help="Cap on the entry notional of this target's open positions.",
        ),
        Field(
            key="leverage", label="Leverage", type="number", default=3.0,
            min=1.0, max=100.0, step=1.0, unit="x",
            help="Applied per instrument before opening from flat (clamped to the instrument max).",
        ),
    ),
)
