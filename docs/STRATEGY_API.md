# Observa Python Strategy API

> **STATUS: CURRENT CONTRACT SUMMARY — VERIFY AGAINST SOURCE CODE BEFORE CHANGING IMPLEMENTATION**
>
> The original knowledge base explicitly warned that an earlier strategy document was aspirational and that the actual Python contract must stay synchronized with `portfolio_to_py()` / `bar_to_py()` in the implementation.

## Strategy class

```python
class MyStrategy:
    def initialize(self, params=None) -> None:
        ...

    def on_bar(self, bar: dict, portfolio: dict, history: list) -> list | dict:
        ...

    def teardown(self) -> None:
        ...
```

## Bar

- `open`
- `high`
- `low`
- `close`
- `volume` or `None`
- `timestamp` as ISO 8601 string

## Portfolio

- `balance`
- `equity`
- `has_open_position`
- `unrealised_pnl`
- `open_positions`

## Open position

- `ticket`
- `direction`
- `size`
- `entry_price`
- `unrealised_pnl`
- `sl`
- `tp`

## History

History is oldest-first and contains only bars available before the current strategy decision. The design intent is that future bars are structurally inaccessible.

## Return values

### Signals only

```python
return [
    {
        "direction": "buy",
        "size": 1.0,
    }
]
```

### Signals plus drawings

```python
return {
    "signals": [...],
    "drawings": [...],
}
```

## Signal fields

- `direction`: `buy`, `sell`, or `close`
- `size`: required
- `price`: optional
- `sl`: optional
- `tp`: optional
- `reason`: optional
- `ticket`: required for `close`

## Current gaps from the source KB

- `on_fill()` is not yet wired through the Python bridge.
- Python-side indicator registration is not implemented.
- Strategies are currently single-threaded.

## Synchronization rule

Any change to `bar_to_py()` or `portfolio_to_py()` must update this contract and its tests in the same change set.
