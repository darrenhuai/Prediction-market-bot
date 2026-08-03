def remove_vig(yes_price, no_price):
    """Normalize YES/NO prices into fair probabilities that sum to 1.

    Kalshi's yes_price + no_price typically exceeds 100 cents (the "vig"),
    so the raw prices overstate the combined probability. Rescale each side
    proportionally so they sum to 1, preserving their relative weighting.
    Falls back to an even 50/50 split if both prices are 0.
    """
    raw_yes = yes_price / 100.0
    raw_no = no_price / 100.0
    total = raw_yes + raw_no
    if total == 0:
        return 0.5, 0.5
    return raw_yes / total, raw_no / total


def ev_yes(fair_prob, yes_price_cents):
    """Expected profit (in dollars per $1 of exposure) from buying a YES contract.

    If YES resolves (probability fair_prob), the contract pays $1, for a
    profit of (1 - cost). If it doesn't (probability 1 - fair_prob), the
    contract pays $0, for a loss of cost. So:
        EV = fair_prob * (1 - cost) + (1 - fair_prob) * (-cost)
           = fair_prob - cost
    """
    cost = yes_price_cents / 100.0
    return fair_prob - cost


def ev_no(fair_prob_no, no_price_cents):
    """Expected profit (in dollars per $1 of exposure) from buying a NO contract.

    Same derivation as ev_yes, with fair_prob_no as the probability NO
    resolves: EV = fair_prob_no - cost.
    """
    cost = no_price_cents / 100.0
    return fair_prob_no - cost


def kelly_fraction(prob: float, payout_multiple: float, fraction: float = 0.25) -> float:
    """Fractional-Kelly stake as a proportion of bankroll.

    Full Kelly is (b*p - q) / b, clamped to 0 for a non-positive edge, then
    scaled by `fraction` (default: quarter-Kelly) to reduce variance.
    """
    b = payout_multiple
    if b == 0:
        return 0.0
    q = 1 - prob
    kelly = (b * prob - q) / b
    return max(0.0, kelly * fraction)


def fmt_pct(v: float, decimals: int = 1) -> str:
    return f"{v * 100:.{decimals}f}%"


def fmt_cents(c: float) -> str:
    return f"${c / 100:.2f}"
