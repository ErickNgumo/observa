Put the user's OHLCV CSV here: timestamp,open,high,low,close,volume
(timestamp chronological, e.g. RFC 3339 or "YYYY-MM-DD HH:MM:SS+00:00").

To avoid duplicating data, the bundled deterministic sample is provided by the
installed package instead:
    import observa; observa.sample_data_path()
