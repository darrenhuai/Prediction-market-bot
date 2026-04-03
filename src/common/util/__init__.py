def remove_vig(yes_price,no_price):
    raw_yes=yes_price/100.0
    raw_no=no_price/100.0
    total=raw_yes+raw_no
    return raw_yes/total,raw_no/total
def ev_yes(fair_prob,yes_price_cents):
    cost=yes_price_cents/100.0
    return fair_prob*1.0-(1-fair_prob)*cost
def ev_no(fair_prob_no,no_price_cents):
    cost=no_price_cents/100.0
    return fair_prob_no*1.0-(1-fair_prob_no)*cost
def kelly_fraction(prob,payout_multiple,fraction=0.25):
    b=payout_multiple
    q=1-prob
    kelly=(b*prob-q)/b
    return max(0.0,kelly*fraction)
def fmt_pct(v,decimals=1):
    return f"{v*100:.{decimals}f}%"
def fmt_cents(c):
    return f"${c/100:.2f}"
