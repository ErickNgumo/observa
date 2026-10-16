import sys, os, tempfile, observa
sys.path.insert(0, "/home/erick/Documents/observa/harness/finance")
from trust_edge_probes import base_rows
class K:
    def initialize(self, params=None): self.kept = {}; self.bad = []; self.first = []
    def on_bar(self, bar, portfolio, history):
        i = len(history)
        self.kept[i] = history
        for t, v in self.kept.items():
            ts = [h["timestamp"] for h in v]
            if len(v) != t or (t and v[-1]["timestamp"] != self.first[t - 1]) or ts != self.first[:t]:
                self.bad.append((i, t))
        self.first.append(bar["timestamp"])
        return []
    def teardown(self): pass
k = K()
observa.run(k, base_rows(60), config=observa.Config(interval="1h"), output=os.path.join(tempfile.mkdtemp(dir=sys.argv[1]), "r"))
print("retained views checked:", sum(range(61)), "violations:", len(k.bad))
