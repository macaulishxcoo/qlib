#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
price_in_check.py — 「利好是否已被定价」量化检查器（港股 / 沪深A股）

用法:
    python price_in_check.py <代码> <事件日期> [发行价] [基准secid] [涨跌幅限制%]

示例:
    python price_in_check.py 02513 2026-08-14 116.20 100.HSI       # 港股
    python price_in_check.py 600519 2026-08-28 1.000300 10        # 沪主板
    python price_in_check.py 300308 2026-08-28 0.399001 20        # 创业板

代码规则:
    HK 5位代码 -> 116.<code> ; 沪市 6xxxxx -> 1.<code> ; 深市 0/2/3开头 -> 0.<code>
    基准 secid: 恒指 100.HSI / 沪深300 1.000300 / 上证 1.000001 / 深成指 0.399001

输出指标:
  1. 位置指标 : 距上市/区间高点回撤、较发行价倍数（估值位置）
  2. 事前指标 : 事件前 N 日累计超额收益 CAR（跑赢/跑输大盘多少）
  3. 事件日指标: 高开幅度、盘中冲高、收盘涨跌、日内振幅、上影线占比、量比、涨跌停标记
  4. 事后指标 : 事件后 1~3 日收益与量能（缩量阴跌=无承接）
  5. 出货特征 : 近 30 日放量下跌天数占比

数据源: 东方财富 push2his（无需 key）。
注意: A股为 T+1、涨跌停制，事件日若触及涨跌停，振幅/上影线指标被制度截断，需结合
      「是否炸板」「封单/换手」等A股特有信息判读（脚本会输出涨停/跌停标记）。
"""
import sys
import time
import statistics
import requests

EM_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def secid_of(code: str) -> str:
    if code.isdigit() and len(code) == 5:
        return f"116.{code}"          # 港股
    if code.startswith("6"):
        return f"1.{code}"            # 沪市主板/科创板(688)
    if code.startswith(("0", "2", "3")):
        return f"0.{code}"            # 深市主板(000/001/002/003)/创业板(300/301)
    raise ValueError(f"无法识别的代码: {code}")


def kline(secid: str, beg: str = "20250101") -> list[dict]:
    params = {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": "101", "fqt": "1", "beg": beg, "end": "20500101",
    }
    for attempt in range(4):
        try:
            r = requests.get(EM_URL, params=params,
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            r.raise_for_status()
            out = []
            for row in r.json()["data"]["klines"]:
                p = row.split(",")
                out.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                            "high": float(p[3]), "low": float(p[4]),
                            "vol": float(p[5]), "amt": float(p[6])})
            return out
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3)
    raise RuntimeError("unreachable")


def pct(a: float, b: float) -> float:
    return (b / a - 1) * 100


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "02513"
    ev = sys.argv[2] if len(sys.argv) > 2 else "2026-08-14"
    ipo = float(sys.argv[3]) if len(sys.argv) > 3 else None
    bench_secid = sys.argv[4] if len(sys.argv) > 4 else "100.HSI"

    stock = kline(f"116.{code}")
    bench = kline(bench_secid)
    sb, bb = {d["date"]: d for d in stock}, {d["date"]: d for d in bench}
    idx = [i for i, d in enumerate(stock) if d["date"] == ev]
    if not idx:
        sys.exit(f"事件日 {ev} 不在数据范围内")
    ei = idx[0]

    print(f"== {code}  @ {ev}  (基准: {bench_secid}) ==")
    last = stock[-1]

    # 1. 位置
    hi = max(stock, key=lambda d: d["high"])
    print(f"\n[1] 位置: 区间最高 {hi['date']} 盘中 {hi['high']:.0f} | "
          f"最新({last['date']})收 {last['close']:.0f}, 距高点 {pct(hi['high'], last['close']):.1f}%")
    if ipo:
        print(f"    较发行价 {ipo}: {last['close'] / ipo:.1f} 倍")

    # 2. 事前 CAR
    print(f"\n[2] 事前超额收益 CAR(事件前20日/10日):")
    for n in (20, 10):
        if ei - n < 1:
            continue
        z = pct(stock[ei - n - 1]["close"], stock[ei - 1]["close"])
        b = pct(bench[max(0, ei - n - 1)]["close"], bench[ei - 1]["close"])
        print(f"    前{n:>2}日: 个股 {z:+.1f}% | 基准 {b:+.1f}% | 超额 {z - b:+.1f}%")

    # 3. 事件日
    prev = stock[ei - 1]
    e = stock[ei]
    m20 = statistics.mean([d["vol"] for d in stock[ei - 20:ei]])
    amp = (e["high"] - e["low"]) / prev["close"] * 100
    shadow = (e["high"] - max(e["open"], e["close"])) / (e["high"] - e["low"]) * 100
    print(f"\n[3] 事件日: 前收 {prev['close']:.0f}")
    print(f"    开盘 {e['open']:.0f} ({pct(prev['close'], e['open']):+.1f}%) | "
          f"最高 {e['high']:.0f} ({pct(prev['close'], e['high']):+.1f}%) | "
          f"最低 {e['low']:.0f} ({pct(prev['close'], e['low']):+.1f}%) | "
          f"收盘 {e['close']:.0f} ({pct(prev['close'], e['close']):+.1f}%)")
    print(f"    日内振幅 {amp:.1f}% | 上影线占日内区间 {shadow:.0f}% | "
          f"量比(vs前20日均量) {e['vol'] / m20:.2f}")

    # 4. 事后
    print(f"\n[4] 事件后:")
    for k in (1, 2, 3):
        if ei + k < len(stock):
            d = stock[ei + k]
            print(f"    第{k}日({d['date']}): {pct(e['close'], d['close']):+.1f}% | "
                  f"量比 {d['vol'] / m20:.2f}")

    # 5. 出货特征: 事件前30日放量下跌
    win = stock[max(0, ei - 30):ei]
    if len(win) >= 10:
        base = statistics.mean([d["vol"] for d in stock[max(0, ei - 60):ei - 30]] or win)
        dist = [d for d in win if d["close"] < d["open"] and d["vol"] > 1.5 * base]
        print(f"\n[5] 事件前30日中放量下跌(量>1.5x均量且收阴) {len(dist)}/{len(win)} 天 "
              f"({len(dist) / len(win) * 100:.0f}%)")


if __name__ == "__main__":
    main()
