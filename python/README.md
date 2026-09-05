# Observa (Python API)

Deterministic, event-driven backtesting backed by the canonical Rust Engine.

```python
import observa

class MyStrategy(observa.Strategy):
    def initialize(self, params=None):
        self.n = int(params.get("n", 5)) if params else 5

    def on_bar(self, bar, portfolio, history):
        if not portfolio["has_open_position"]:
            return [{"direction": "buy", "size": 1.0}]
        return []

result = observa.run(MyStrategy(), "data.csv", config=observa.Config())
print(result.final_equity)
result.save("runs/test-01")
```
