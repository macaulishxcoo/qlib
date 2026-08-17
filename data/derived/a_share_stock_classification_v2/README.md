# A-share monthly stock classification v2

One row represents one historically listed security on one completed month-end
(`asof_date`).  Join on `(asof_date, ts_code)`; do not join historical work to
today's classifications.

| Dimension | Main fields | Rule / caveat |
|---|---|---|
| Security | `security_name`, `exchange`, `market_board`, `list_date`, `delist_date`, `listing_age_days` | Current Tushare security master; board is treated as stable. |
| Board | `board` | `sse_main`, `szse_main`, `chinext`, `star`, `bse`. |
| Industry | `l1_*`, `l2_*`, `l3_*`, `industry_*_date`, `industry_gap_fill` | Shenwan history effective on `asof_date`; a gap-filled label is explicitly marked. |
| Size | `free_float_mv_10k_cny`, `free_float_mv_percentile`, `size_bucket` | Within-month free-float market-value rank: small ≤40%, mid 40–80%, large >80%. |
| Index | `is_csi300/500/800/1000`, matching `*_weight` | Historical Tushare `index_weight` month-end snapshots. |
| Risk | `is_st`, `is_delist_phase`, `risk_status` | PIT interval status on `asof_date`. |
| Trading | `is_suspended_asof`, `trading_status` | Suspended means no `daily_basic` observation on month-end. |
| Turnover | `turnover_rate*`, `turnover_liquidity_bucket` | Month-end free-float turnover percentile: low ≤30%, normal 30–70%, high >70%; it is not a capacity measure. |
| Quality | `market_data_date`, `market_data_age_days`, `size_data_quality` | Size price/share uses last available observation; `stale` is older than 31 days. |

For an investable monthly universe, normally exclude `risk_status != normal`,
`trading_status != trading`, and `size_data_quality != fresh`, then apply the
strategy's separate 20-day average-amount capacity rule.
