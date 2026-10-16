import sys, os, tempfile, observa
sys.path.insert(0, "/home/erick/Documents/observa/harness/finance")
from trust_edge_probes import base_rows, Trader
root = tempfile.mkdtemp(dir=sys.argv[1])
def case(name, mut, tsfmt=None):
    rows = base_rows()
    mut(rows)
    p = os.path.join(root, name + ".csv")
    with open(p, "w") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        for x in rows:
            ts = x["timestamp"] if tsfmt is None else tsfmt(x["timestamp"])
            f.write(f"{ts},{x['open']!r},{x['high']!r},{x['low']!r},{x['close']!r},{x['volume']}\n")
    try:
        observa.run(Trader(), p, config=observa.Config(interval="1h"), output=os.path.join(root, name))
        print(f"{name:34s} accepted")
    except Exception as e:
        print(f"{name:34s} error {getattr(e,'code',None)} {str(e)[:110]}")
case("csv_close_above_high_1e-12", lambda r: r[7].update(close=r[7]["high"] + 1e-12))
case("csv_naive_space", lambda r: None, lambda t: t.replace("T", " ").rstrip("Z"))
case("csv_negative_low", lambda r: r[7].update(low=-0.5))
case("csv_inf_high", lambda r: r[7].update(high=float("inf")))
