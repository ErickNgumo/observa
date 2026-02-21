# Observa

> A visual backtesting engine for algorithmic traders who need to *see* 
> their strategy execute, not just trust the numbers.

## What This Is

Observa is an event-driven backtesting platform that replays market data 
bar by bar, showing fills, exits, indicators, and strategy decisions as 
they happen. Instead of returning a Sharpe ratio and asking you to trust 
it, Observa lets you watch your strategy think — and catch what the 
numbers hide.

## Project Status

> Early development — core architecture and design phase.

---

## Problem Statement

Algorithmic trading strategies fail in live markets for two reasons that 
are almost never caught during backtesting: silent logic errors in code, 
and unrealistic simulation assumptions.

Current backtesting tools produce a result — a return figure, a Sharpe 
ratio, an equity curve — but offer little to no way of verifying that the 
strategy behaved correctly to produce that result. A trader has no way of 
seeing, bar by bar, whether entries fired at the right moment, whether 
indicators were calculated correctly, or whether exit logic triggered as 
intended. The code either runs or it doesn't. The number either looks good 
or it doesn't. There is no middle ground where a trader can observe the 
strategy thinking.

This creates a dangerous illusion of validation.

## Why Current Tools Fail

The failure isn't accidental — it reflects a fundamental assumption baked 
into every major backtesting platform: that the output is the truth, and 
the process that generated it is a black box the trader should trust.

MT5 offers visual replay, but locks traders into MQL5 — a C-like language 
hostile to most traders, painful to write custom plots in, and entirely 
platform-dependent. A strategy built in MQL5 cannot easily transfer to a 
broker outside the MT5 ecosystem. The majority of algorithmic traders work 
in Python. MT5 simply doesn't serve them.

Python-native tools like Backtrader and QuantConnect offer flexibility but 
treat visualization as an afterthought, or exclude it entirely. A trader 
running a backtest in these environments receives numbers. They do not see 
their strategy execute. They cannot step through a losing trade and 
understand why it lost.

The deeper failure is this: none of these tools are built around the idea 
that seeing is understanding. They are calculators dressed up as research 
platforms.

## The Truth This System Is Built to Reveal

Two things must be true for a strategy to be worth trading: the code must 
do exactly what the trader intends, and it must remain viable when exposed 
to real market conditions — spreads, slippage, commission, invalid stop 
distances, partial fills.

Neither truth can be confirmed by looking at a number. They can only be 
confirmed by watching.

This system exists to make strategy execution fully observable — bar by 
bar, fill by fill, indicator by indicator — so a trader can see with their 
own eyes whether their logic is sound, whether their intuition translated 
correctly into code, and whether their strategy can survive contact with a 
real market.

The goal is not a better backtest. The goal is the end of blind trust.

---

## Roadmap

- [x] Problem definition & invariants  
- [ ] Domain model & event taxonomy  
- [ ] Core engine (Rust)  
- [ ] Strategy interface (Python)  
- [ ] Visual replay layer  
- [ ] MVP release