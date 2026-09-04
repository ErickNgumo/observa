import yfinance as yf
import pandas as pd

print("Libraries imported.")

print("Downloading data...")



# Parameters
TICKER = "eurusd=X"
INTERVAL = "15m"
BARS = 1500

# Download data
df = yf.download(
    TICKER,
    period="60d",      # 15m data is only available for recent history
    interval=INTERVAL,
    auto_adjust=False,
    progress=False
)

# Keep only the latest 1500 bars
df = df.tail(BARS)

# Clean column names if using newer yfinance versions
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

# Reset index
df = df.reset_index()
df = df.rename(columns={
    "Datetime": "timestamp",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
})# Save to CSV
df.to_csv("EURUSD_M15.csv", index=False)

print(df.head())
print(f"\nDownloaded {len(df)} bars.")
print("Saved to EURUSD_M15.csv")