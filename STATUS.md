# SharedSignals Status

- Repo initialized, collectors symlinked
- Git origin: https://github.com/NicholasHan1226/SharedSignals.git
- Collectors (symlinked from MarketGraph/08-Market-Interfaces/tools/collectors/):
  pm_polymarket_collector.py, crypto_binance_collector.py, pm_parquet_loader.py
- storage/schema.py: documents marketdata.sqlite schema (11 tables)
- marketdata.sqlite: 75MB, 11 tables, operational
- staging: 6 streams, active
- Pending: extract remaining collectors, unify ingest interface
