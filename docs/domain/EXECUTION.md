# Execution Domain

## Purpose

Simulate the broker-side behavior between strategy intent and actual fill.

## Current documented MVP behavior

- Market orders only.
- Fill at next bar open according to the documented default.
- Fixed spread.
- Fixed slippage.
- Commission.
- Minimum and maximum lot validation.
- Margin validation.
- Stop/target distance validation after actual fill price is calculated.

## Price behavior

Buy:

`fill = open + spread + slippage`

Sell:

`fill = open - spread - slippage`

The source KB describes close orders as using the open with minimal slippage behavior.

## SL / TP behavior

- SL gets slippage.
- TP does not.
- If both are hit in one bar, the source implementation gives SL priority.

## Configuration

Execution parameters live in `config.yaml` rather than CLI flags.

## Not MVP

- dynamic spread/slippage
- order-book simulation
- limit orders
- stop orders
