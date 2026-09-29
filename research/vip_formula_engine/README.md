# VIP Formula Engine Research v1

This is an isolated, read-only research area. It is not imported by the
production collector, backtest engine, or strategy laboratory.

The LevelDB reader inspects only `jnd28:vip-saved-algorithms` and extracts
`id`, `name`, `formulaText`, and `createdAt`. It intentionally does not read or
process authentication, token, or cookie keys. The SQLite snapshot uses a
read-only URI and writes only JSON results under this directory.

The parser documents observed syntax (`[]`, `+`, `|`, `=`, `#`) without
assigning business meaning. Evaluation is disabled until a rule is supported
by independent, chronological comparisons against Le28 output.
