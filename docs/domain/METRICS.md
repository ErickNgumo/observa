# Metrics Domain

## Purpose

Derive statistics from the equity curve and trade log without making the frontend the source of truth.

## Current documented metrics

- Total return
- Annualised return
- Maximum drawdown
- Sharpe ratio
- Calmar ratio
- Win rate
- Profit factor
- Expectancy
- Average win/loss
- Largest win/loss

## Equity sampling

The source KB records a major correction: equity snapshots must occur on every bar rather than only at trade close.

## Sharpe implementation recorded in the source KB

- Sample standard deviation using N-1.
- Compound conversion of annual risk-free rate.
- Near-zero volatility epsilon guard.
- Minimum observation threshold of 30.
- 15-minute forex annualisation assumption: 96 × 252 = 24,192 observations per year.

## Open research issue

The source KB reports a Sharpe result around 11 for a 28-trade sample after earlier errors were corrected, and acknowledges that small samples can make the statistic unreliable. The correct MVP presentation/gating policy remains an open research question.

## Future metrics explicitly listed

- Sortino ratio
- VaR
- Expected Shortfall

These are not MVP commitments.
