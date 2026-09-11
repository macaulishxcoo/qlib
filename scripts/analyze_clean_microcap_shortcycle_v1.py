#!/usr/bin/env python3
"""实验二：Z1 短周期 enhance 专项（协议 clean_microcap_final_dual_protocol_v1 §3）。

Z1 信号，10/15 日持有期，enhance 全池加权，vs 月度对照。
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 复用实验一的加载与信号（exec 方式合并成本高，直接重新构建 Z1 与域）
exec(open('/home/xiaocong/worksapces/qlib/scripts/analyze_clean_microcap_fusion_v1.py').read().split("# ---------------- 实验一: 相关归并")[0])

OUT2.mkdir(parents=True, exist_ok=True)
BT = pd.Timestamp('2022-01-04')
trading_days = cal[cal >= BT]


def run_enhance_period(signal_df, period: int, cost: float):
    """period 日调仓的 enhance 全池（域内）回测，日度净值。"""
    o_next = O.shift(-1)
    cash, holdings, navs, turns = 1.0, {}, [], []
    days = list(trading_days)
    next_reb = days[0]
    for idx in range(len(days)):
        t = days[idx]
        if idx >= len(days) - 3:
            navs.append((t, cash, len(holdings)))
            continue
        dom = domain_for(t)
        if dom and t >= next_reb:
            bad = bad_at(t)
            cands = [s for s in C.columns if s in dom and s not in bad]
            if len(cands) >= 50:
                z = signal_df.loc[t].reindex(cands).dropna()
                if len(z) >= 50:
                    w = 1.0 + 0.5 * (z.rank(pct=True) - 0.5)
                    w = w / w.sum()
                    # T+1 开盘成交
                    bp = days[min(idx + 1, len(days) - 1)]
                    o_row = O.loc[bp]
                    new_h = {s: wv for s, wv in w.items()
                             if pd.notna(o_row.get(s, np.nan)) and o_row.get(s, 0) > 0}
                    old, new = set(holdings), set(new_h)
                    to = (len(old - new) + len(new - old)) / 2 / max(len(new), 1) if new else 1.0
                    cash *= (1 - cost * to)
                    turns.append(to)
                    holdings = new_h
            next_reb = days[min(idx + period, len(days) - 1)]
        if holdings:
            rets, wsum = [], 0.0
            for s, w in holdings.items():
                c0 = C.shift(1).at[t, s] if s in C.columns else np.nan
                c1 = C.at[t, s] if s in C.columns else np.nan
                if pd.notna(c0) and pd.notna(c1) and c0 > 0:
                    rets.append(w * (c1 / c0 - 1))
                    wsum += w
            pr = sum(rets) / wsum if wsum > 0 else 0.0
        else:
            pr = 0.0
        cash *= (1 + pr)
        navs.append((t, cash, len(holdings)))
    return pd.DataFrame(navs, columns=['datetime', 'nav', 'n']).set_index('datetime'), (float(np.mean(turns)) if turns else np.nan)


print('\n[exp2] Z1 短周期 enhance ...', flush=True)
rows, nav_store = [], {}
COSTS = {'base': 0.0015, 'stress': 0.0040, 'microcap': 0.0080}
PERIODS = {'p10': 10, 'p15': 15, 'monthly': 21}

for (pname, period), (cname, cost) in itertools.product(PERIODS.items(), COSTS.items()):
    df, to = run_enhance_period(Z1, period, cost)
    r = df['nav'].pct_change().dropna()
    years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = df['nav'].iloc[-1] ** (1 / years) - 1
    mdd = (df['nav'] / df['nav'].cummax() - 1).min()
    ir = r.mean() / r.std() * np.sqrt(243) if r.std() > 0 else np.nan
    rows.append({'arm': f'z1_{pname}', 'cost': cname, 'CAGR': cagr, 'IR': ir,
                 'MDD': mdd, 'final_nav': df['nav'].iloc[-1], 'avg_daily_turnover': to})
    nav_store[f'z1_{pname}_{cname}'] = df['nav']
    print(f'  z1_{pname} {cname}: CAGR={cagr:+.1%} IR={ir:.2f} MDD={mdd:.1%} 换手/期={to:.1%}', flush=True)

bt2 = pd.DataFrame(rows)
bt2.to_csv(OUT2 / 'backtest_summary.csv', index=False)

print('\n[exp2] 判定（microcap vs 月度对照）...', flush=True)
mon_mc = bt2[(bt2['arm'] == 'z1_monthly') & (bt2['cost'] == 'microcap')].iloc[0]
for _, r in bt2[bt2['cost'] == 'microcap'].iterrows():
    if r['arm'] == 'z1_monthly':
        continue
    ex = r['CAGR'] - mon_mc['CAGR']
    tier = ('short_cycle_viable' if (ex >= 0.01 and r['IR'] >= 0.4)
            else 'short_cycle_closed')
    print(f"  {r['arm']}: CAGR={r['CAGR']:+.1%} vs 月度 {mon_mc['CAGR']:+.1%} -> 差 {ex:+.1%} IR={r['IR']:.2f} -> {tier}")

summary = {'protocol': 'research/protocols/clean_microcap_final_dual_protocol_v1.md',
           'arms': bt2.to_dict('records')}
(OUT2 / 'decision.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'done': True}, ensure_ascii=False))
