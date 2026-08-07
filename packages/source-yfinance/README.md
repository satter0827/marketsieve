# marketsieve-source-yfinance

No-key yfinance batch acquisition for the MarketSieve market matrix. The adapter fetches the exact
requested symbols and records partial or failed observations without switching providers. Exchange
calendars identify the actual close for each trading date, including scheduled shortened sessions;
they do not supply market values.

Yahoo Finance data is intended for personal use. Review the upstream terms before using downloaded
data outside a local research workflow.
