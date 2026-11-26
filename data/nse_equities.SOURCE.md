`nse_equities.csv` is a snapshot of the NSE "list of equity securities" (the public EQUITY_L file the exchange publishes), taken from a
public mirror (github.com/pkjmesra/PKScreener, `results/Indices/EQUITY_L.csv`) because nseindia.com was not reachable when it was
prepared. The newest listing in it is from late December 2025, so recently listed companies and symbol changes after that date are
missing. The search box also queries Yahoo Finance live (when the internet is reachable) to cover newer listings and BSE stocks.
To refresh it, download https://archives.nseindia.com/content/equities/EQUITY_L.csv and keep the columns symbol, name, isin
(`make refresh-symbols` does this when NSE is reachable).
