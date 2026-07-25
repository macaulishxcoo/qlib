# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
LightGBM 静态训练结果可视化分析脚本（静态训练阶段专用）
运行 qrun workflow_config_lightgbm_Alpha158.yaml 后，用此脚本分析保存的结果

用法：
    conda activate qlib
    python analyze_static_results.py                              # 自动找 mlruns_static 最新运行
    python analyze_static_results.py --mlruns-dir output/mlruns    # 指定 mlruns 目录
"""

import pickle
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无图形界面环境也能画图
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# 英文显示（避免 WSL 无中文字体问题）
plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# 脚本所在目录（mlruns 和产物都在 output/ 里）
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def find_latest_run(mlruns_name: str = "mlruns_static") -> dict:
    """自动找到最近一次训练运行的所有产物文件，返回 (文件dict, visualization目录)"""
    mlruns = OUTPUT_DIR / mlruns_name
    # 找到所有实验目录（排除 meta.yaml 所在的 0 目录）
    exp_dirs = [d for d in mlruns.iterdir() if d.is_dir() and d.name not in ("0", ".trash", "rolling_visualization")]
    if not exp_dirs:
        raise FileNotFoundError("未找到任何训练运行记录，请先执行 qrun")

    # 对于滚动训练，优先选择包含完整产物的实验（合并结果）
    def _exp_score(exp_dir):
        """优先选择含完整分析产物（sig_analysis/ic.pkl）的实验：
        滚动训练的子窗口实验只有 pred.pkl，合并结果实验才有 IC/回测分析"""
        recs = [d for d in exp_dir.iterdir() if d.is_dir()]
        has_full = any((r / "artifacts" / "sig_analysis" / "ic.pkl").exists() for r in recs)
        return (1 if has_full else 0, exp_dir.stat().st_mtime)

    exp_dir = sorted(exp_dirs, key=_exp_score)[-1]
    # 取有最完整产物的 recorder
    rec_dirs = [d for d in exp_dir.iterdir() if d.is_dir()]

    def _rec_score(r):
        arts = r / "artifacts"
        return sum([
            (arts / "pred.pkl").exists(),
            (arts / "label.pkl").exists(),
            (arts / "portfolio_analysis" / "report_normal_1day.pkl").exists(),
            (arts / "sig_analysis" / "ic.pkl").exists(),
        ])

    rec_dir = sorted(rec_dirs, key=_rec_score)[-1]

    artifacts = rec_dir / "artifacts"
    # 可视化图片保存在 recorder 目录下的 visualization/
    vis_dir = rec_dir / "visualization"
    vis_dir.mkdir(exist_ok=True)

    print(f"Loading run: {rec_dir.name}")
    print(f"  Experiment ID: {exp_dir.name}")
    print(f"  Recorder ID:   {rec_dir.name}")
    print(f"  Visualization: {vis_dir.relative_to(OUTPUT_DIR)}")
    print()

    files = {
        "pred": artifacts / "pred.pkl",
        "label": artifacts / "label.pkl",
        "model": artifacts / "params.pkl",
        "ic": artifacts / "sig_analysis" / "ic.pkl",
        "ric": artifacts / "sig_analysis" / "ric.pkl",
        "report": artifacts / "portfolio_analysis" / "report_normal_1day.pkl",
        "positions": artifacts / "portfolio_analysis" / "positions_normal_1day.pkl",
        "indicator": artifacts / "portfolio_analysis" / "indicator_analysis_1day.pkl",
        "port_analysis": artifacts / "portfolio_analysis" / "port_analysis_1day.pkl",
    }
    return {k: v for k, v in files.items() if v.exists()}, vis_dir


def load_pkl(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)


# ─────────────────────────────────────────────────────────────
# 图1：预测信号分析（IC 序列）
# ─────────────────────────────────────────────────────────────
def plot_ic_analysis(ic_df: pd.DataFrame, ric_df: pd.DataFrame, vis_dir: Path):
    """绘制 IC / Rank IC 的时序图和分布图"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 9))
    fig.suptitle("Prediction Signal Quality (IC / Rank IC)", fontsize=14, fontweight="bold")

    # IC 时序
    ax = axes[0, 0]
    ic_series = ic_df.iloc[:, 0] if isinstance(ic_df, pd.DataFrame) else ic_df
    colors = ["green" if v > 0 else "red" for v in ic_series]
    ax.bar(range(len(ic_series)), ic_series, color=colors, alpha=0.6, linewidth=0)
    ax.axhline(y=ic_series.mean(), color="blue", linestyle="--", linewidth=1.5,
               label=f"均值 = {ic_series.mean():.4f}")
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title(f"IC Time Series (IC={ic_series.mean():.4f}, ICIR={ic_series.mean()/ic_series.std():.4f})")
    ax.set_xlabel("Trading Day")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Rank IC 时序
    ax = axes[0, 1]
    ric_series = ric_df.iloc[:, 0] if isinstance(ric_df, pd.DataFrame) else ric_df
    colors = ["green" if v > 0 else "red" for v in ric_series]
    ax.bar(range(len(ric_series)), ric_series, color=colors, alpha=0.6, linewidth=0)
    ax.axhline(y=ric_series.mean(), color="blue", linestyle="--", linewidth=1.5,
               label=f"均值 = {ric_series.mean():.4f}")
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title(f"Rank IC Time Series (RIC={ric_series.mean():.4f}, RICIR={ric_series.mean()/ric_series.std():.4f})")
    ax.set_xlabel("Trading Day")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # IC 分布直方图
    ax = axes[1, 0]
    ax.hist(ic_series, bins=50, color="steelblue", alpha=0.7, edgecolor="black", linewidth=0.5)
    ax.axvline(x=ic_series.mean(), color="red", linestyle="--", linewidth=1.5,
               label=f"均值 = {ic_series.mean():.4f}")
    ax.axvline(x=0, color="black", linewidth=0.5)
    ax.set_title("IC Distribution")
    ax.set_xlabel("IC Value")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # IC 累计和（趋势稳定性）
    ax = axes[1, 1]
    ic_cumsum = ic_series.cumsum()
    ax.plot(ic_cumsum.values, color="steelblue", linewidth=1.5)
    ax.fill_between(range(len(ic_cumsum)), ic_cumsum.values, alpha=0.3, color="steelblue")
    ax.set_title(f"IC Cumulative Sum (Trend Stability, final = {ic_cumsum.iloc[-1]:.2f})")
    ax.set_xlabel("Trading Day")
    ax.set_ylabel("Cumulative IC")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(vis_dir / "ic_analysis.png", dpi=150, bbox_inches="tight")
    plt.show()


# ─────────────────────────────────────────────────────────────
# 图2：累计收益与超额收益
# ─────────────────────────────────────────────────────────────
def plot_return_analysis(report_df: pd.DataFrame, vis_dir: Path):
    """绘制策略收益、基准收益、超额收益曲线"""
    fig, axes = plt.subplots(3, 1, figsize=(16, 14))
    fig.suptitle("Backtest Analysis", fontsize=14, fontweight="bold")

    # 累计收益对比
    ax = axes[0]
    cum_return = report_df["return"].cumsum()
    cum_bench = report_df["bench"].cumsum()
    cum_return_cost = (report_df["return"] - report_df["cost"]).cumsum()

    ax.plot(cum_return.index, cum_return, label="Strategy (no cost)", color="steelblue", linewidth=1.5)
    ax.plot(cum_return_cost.index, cum_return_cost, label="Strategy (with cost)", color="orange", linewidth=1.5)
    ax.plot(cum_bench.index, cum_bench, label="Benchmark (CSI300)", color="gray", linewidth=1.5, alpha=0.7)
    ax.set_title(f"Cumulative Return  |  Strategy={cum_return_cost.iloc[-1]*100:.1f}%  Benchmark={cum_bench.iloc[-1]*100:.1f}%")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.set_ylabel("Cumulative Return")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    # 超额收益
    ax = axes[1]
    excess_return = (report_df["return"] - report_df["bench"]).cumsum()
    excess_return_cost = (report_df["return"] - report_df["bench"] - report_df["cost"]).cumsum()
    ax.plot(excess_return.index, excess_return, label="Excess (no cost)", color="green", linewidth=1.5)
    ax.plot(excess_return_cost.index, excess_return_cost, label="Excess (with cost)", color="darkgreen", linewidth=1.5)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_title(f"Excess Return (vs CSI300)  |  with cost = {excess_return_cost.iloc[-1]*100:.1f}%")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.set_ylabel("Excess Return")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    # 回撤
    ax = axes[2]
    excess_cum = (report_df["return"] - report_df["bench"] - report_df["cost"]).cumsum()
    drawdown = excess_cum - excess_cum.cummax()
    ax.fill_between(drawdown.index, drawdown, 0, color="red", alpha=0.4)
    ax.plot(drawdown.index, drawdown, color="darkred", linewidth=1)
    ax.set_title(f"Excess Return Drawdown  |  Max DD = {drawdown.min()*100:.1f}%")
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    plt.tight_layout()
    plt.savefig(vis_dir / "return_analysis.png", dpi=150, bbox_inches="tight")
    plt.show()


# ─────────────────────────────────────────────────────────────
# 图3：换手率分析
# ─────────────────────────────────────────────────────────────
def plot_turnover(report_df: pd.DataFrame, vis_dir: Path):
    """绘制换手率时序图"""
    fig, axes = plt.subplots(2, 1, figsize=(16, 8))
    fig.suptitle("Turnover & Transaction Cost Analysis", fontsize=14, fontweight="bold")

    ax = axes[0]
    turnover = report_df["turnover"]
    ax.plot(turnover.index, turnover, color="steelblue", linewidth=0.8, alpha=0.7)
    ax.fill_between(turnover.index, turnover, alpha=0.3, color="steelblue")
    avg_turnover = turnover.mean()
    ax.axhline(y=avg_turnover, color="red", linestyle="--", linewidth=1.5,
               label=f"平均换手率 = {avg_turnover:.3f}")
    ax.set_title("Daily Turnover")
    ax.set_ylabel("Turnover")
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    # 交易成本
    ax = axes[1]
    cost = report_df["cost"]
    ax.plot(cost.index, cost.cumsum(), color="darkred", linewidth=1.5)
    ax.set_title(f"Cumulative Transaction Cost = {cost.sum()*100:.2f}% (of initial capital)")
    ax.set_ylabel("Cumulative Cost")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    plt.tight_layout()
    plt.savefig(vis_dir / "turnover_analysis.png", dpi=150, bbox_inches="tight")
    plt.show()


# ─────────────────────────────────────────────────────────────
# 图4：月度收益热力图
# ─────────────────────────────────────────────────────────────
def plot_monthly_return(report_df: pd.DataFrame, vis_dir: Path):
    """绘制月度收益热力图"""
    import matplotlib.colors as mcolors

    def _monthly(series_func):
        # 按 年-月 聚合日频序列（单利求和，与累计收益曲线口径一致）
        m = report_df.groupby([report_df.index.year, report_df.index.month]).apply(series_func)
        m_df = m.unstack(level=1)
        m_df.columns = [f"{c}M" for c in m_df.columns]
        return m_df

    # 策略净收益（已扣手续费）= return - cost
    strategy_df = _monthly(lambda x: (x["return"] - x["cost"]).sum())
    # 基准收益（指数本身无手续费）= bench
    bench_df = _monthly(lambda x: x["bench"].sum())
    # 超额收益（已扣手续费）= 策略净收益 - 基准 = return - cost - bench
    excess_monthly_df = _monthly(lambda x: (x["return"] - x["bench"] - x["cost"]).sum())

    fig, axes = plt.subplots(3, 1, figsize=(16, 12))
    fig.suptitle("Monthly Return Heatmap", fontsize=14, fontweight="bold")

    norm = mcolors.TwoSlopeNorm(vmin=-0.05, vcenter=0, vmax=0.05)

    def _draw(ax, df, title):
        im = ax.imshow(df.values * 100, cmap="RdYlGn", norm=norm, aspect="auto")
        ax.set_xticks(range(len(df.columns)))
        ax.set_xticklabels(df.columns, fontsize=9)
        ax.set_yticks(range(len(df.index)))
        ax.set_yticklabels(df.index)
        ax.set_title(title)
        for i in range(len(df.index)):
            for j in range(len(df.columns)):
                val = df.values[i, j]
                if not np.isnan(val):
                    ax.text(j, i, f"{val*100:.1f}", ha="center", va="center", fontsize=8,
                            color="black" if abs(val) < 0.03 else "white", fontweight="bold")
        plt.colorbar(im, ax=ax, shrink=0.8)

    # 策略净收益 - 基准 = 超额，三张图口径自洽
    _draw(axes[0], strategy_df, "Strategy Monthly Return (net of cost) (%)")
    _draw(axes[1], bench_df, "Benchmark Monthly Return (CSI300) (%)")
    _draw(axes[2], excess_monthly_df, "Monthly Excess Return (Strategy net - Benchmark) (%)")

    plt.tight_layout()
    plt.savefig(vis_dir / "monthly_return.png", dpi=150, bbox_inches="tight")
    plt.show()


# ─────────────────────────────────────────────────────────────
# 图5：特征重要性 Top20
# ─────────────────────────────────────────────────────────────
_ALPHA158_NAMES = [
    'KMID','KLEN','KMID2','KUP','KUP2','KLOW','KLOW2','KSFT','KSFT2',
    'OPEN0','HIGH0','LOW0','VWAP0',
    'ROC5','ROC10','ROC20','ROC30','ROC60',
    'MA5','MA10','MA20','MA30','MA60',
    'STD5','STD10','STD20','STD30','STD60',
    'BETA5','BETA10','BETA20','BETA30','BETA60',
    'RSQR5','RSQR10','RSQR20','RSQR30','RSQR60',
    'RESI5','RESI10','RESI20','RESI30','RESI60',
    'MAX5','MAX10','MAX20','MAX30','MAX60',
    'MIN5','MIN10','MIN20','MIN30','MIN60',
    'QTLU5','QTLU10','QTLU20','QTLU30','QTLU60',
    'QTLD5','QTLD10','QTLD20','QTLD30','QTLD60',
    'RANK5','RANK10','RANK20','RANK30','RANK60',
    'RSV5','RSV10','RSV20','RSV30','RSV60',
    'IMAX5','IMAX10','IMAX20','IMAX30','IMAX60',
    'IMIN5','IMIN10','IMIN20','IMIN30','IMIN60',
    'IMXD5','IMXD10','IMXD20','IMXD30','IMXD60',
    'CORR5','CORR10','CORR20','CORR30','CORR60',
    'CORD5','CORD10','CORD20','CORD30','CORD60',
    'CNTP5','CNTP10','CNTP20','CNTP30','CNTP60',
    'CNTN5','CNTN10','CNTN20','CNTN30','CNTN60',
    'CNTD5','CNTD10','CNTD20','CNTD30','CNTD60',
    'SUMP5','SUMP10','SUMP20','SUMP30','SUMP60',
    'SUMN5','SUMN10','SUMN20','SUMN30','SUMN60',
    'SUMD5','SUMD10','SUMD20','SUMD30','SUMD60',
    'VMA5','VMA10','VMA20','VMA30','VMA60',
    'VSTD5','VSTD10','VSTD20','VSTD30','VSTD60',
    'WVMA5','WVMA10','WVMA20','WVMA30','WVMA60',
    'VSUMP5','VSUMP10','VSUMP20','VSUMP30','VSUMP60',
    'VSUMN5','VSUMN10','VSUMN20','VSUMN30','VSUMN60',
    'VSUMD5','VSUMD10','VSUMD20','VSUMD30','VSUMD60',
]


def plot_feature_importance(model_path: Path, vis_dir: Path):
    """绘制特征重要性 Top20"""
    model = load_pkl(model_path)
    booster = model.model
    importance = booster.feature_importance(importance_type='gain')

    # 映射 Column_i → Alpha158 短名
    names = [_ALPHA158_NAMES[i] if i < len(_ALPHA158_NAMES) else f'Col_{i}' for i in range(len(importance))]
    df = pd.DataFrame({'name': names, 'importance': importance})
    df = df.sort_values('importance', ascending=True).tail(20)

    fig, ax = plt.subplots(figsize=(10, 8))
    bars = ax.barh(range(len(df)), df['importance'], color='steelblue', alpha=0.8)
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df['name'], fontsize=9)
    ax.set_xlabel('Importance (gain)')
    ax.set_title('Feature Importance Top 20 (LightGBM, by gain)')

    # 在柱子右边标注数值
    total = df['importance'].sum()
    for i, (_, row) in enumerate(df.iterrows()):
        pct = row['importance'] / total * 100
        ax.text(row['importance'] + total * 0.01, i, f"{pct:.1f}%", va='center', fontsize=8)

    ax.grid(True, axis='x', alpha=0.3)
    plt.tight_layout()
    plt.savefig(vis_dir / "feature_importance.png", dpi=150, bbox_inches="tight")
    plt.show()


# ─────────────────────────────────────────────────────────────
# 图6：分组收益（5分位）
# ─────────────────────────────────────────────────────────────
def plot_group_return(pred_df: pd.DataFrame, label_df: pd.DataFrame, vis_dir: Path):
    """每天按预测分数分5组，绘制各组平均收益"""
    # 合并预测和标签
    merged = pred_df.join(label_df, how='inner')
    merged.columns = ['score', 'label']

    # 每天分组计算平均收益
    daily_groups = {}
    for dt, day_df in merged.groupby(level='datetime'):
        if len(day_df) < 10:
            continue
        day_df = day_df.sort_values('score')
        groups = pd.qcut(day_df['score'], 5, labels=False, duplicates='drop')
        group_ret = day_df.groupby(groups)['label'].mean()
        daily_groups[dt] = group_ret

    if not daily_groups:
        print("  Skipping group return: not enough data")
        return

    result = pd.DataFrame.from_dict(daily_groups, orient='index')
    result.index = pd.to_datetime(result.index)
    result = result.sort_index()
    avg_ret = result.mean()

    # 绘图
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Quintile Return Analysis', fontsize=14, fontweight='bold')

    # 左图：各组平均收益柱状图
    ax = axes[0]
    colors = ['#d73027', '#fc8d59', '#fee090', '#91bfdb', '#4575b4']
    labels = ['Q1 (Low)', 'Q2', 'Q3', 'Q4', 'Q5 (High)']
    x_pos = range(len(avg_ret))
    bars = ax.bar(x_pos, avg_ret * 100, color=colors[:len(avg_ret)], alpha=0.85, edgecolor='black', linewidth=0.5)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels[:len(avg_ret)])
    ax.set_ylabel('Avg Daily Return (%)')
    ax.set_title(f'Quintile Avg Return  |  Q5-Q1 = {(avg_ret.iloc[-1]-avg_ret.iloc[0])*100:.3f}%')
    ax.axhline(y=0, color='black', linewidth=0.5)
    for i, v in enumerate(avg_ret):
        ax.text(i, v * 100 + 0.005, f'{v*100:.3f}%', ha='center', fontsize=9)
    ax.grid(True, alpha=0.3, axis='y')

    # 右图：各组累计收益曲线
    ax = axes[1]
    cum_ret = result.cumsum() * 100
    for i in range(len(avg_ret)):
        lw = 2.0 if i in [0, len(avg_ret)-1] else 1.0
        alpha = 1.0 if i in [0, len(avg_ret)-1] else 0.5
        ax.plot(cum_ret.index, cum_ret.iloc[:, i], label=labels[i],
                color=colors[i], linewidth=lw, alpha=alpha)
    ax.set_ylabel('Cumulative Return (%)')
    ax.set_xlabel('Trading Day')
    ax.set_title('Cumulative Return by Quintile')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(vis_dir / "group_return.png", dpi=150, bbox_inches="tight")
    plt.show()


# ─────────────────────────────────────────────────────────────
# 图5：指标汇总表
# ─────────────────────────────────────────────────────────────
def print_summary(port_analysis_path: Path):
    """打印完整的结果汇总"""
    data = load_pkl(port_analysis_path)
    print("=" * 70)
    print("                    LightGBM Training Results Summary")
    print("=" * 70)
    for key, value in data.items():
        print(f"\n[{key}]")
        if hasattr(value, "to_string"):
            print(value.to_string())
        else:
            print(value)
    print("=" * 70)


# ─────────────────────────────────────────────────────────────
# 量化分析报告
# ─────────────────────────────────────────────────────────────
def generate_report(files: dict, vis_dir: Path):
    """生成精确的量化分析报告，保存到 vis_dir/analysis_report.txt"""
    lines = []
    W = 72

    def section(title):
        lines.append("")
        lines.append("=" * W)
        lines.append(f"  {title}")
        lines.append("=" * W)

    def subsection(title):
        lines.append("")
        lines.append(f"--- {title} ---")

    # ── 1. 信号质量 ──
    if "ic" in files and "ric" in files:
        ic_series = load_pkl(files["ic"])
        ric_series = load_pkl(files["ric"])
        ic = ic_series.iloc[:, 0] if isinstance(ic_series, pd.DataFrame) else ic_series
        ric = ric_series.iloc[:, 0] if isinstance(ric_series, pd.DataFrame) else ric_series

        section("1. 预测信号质量  →  ic_analysis.png")

        ic_mean, ic_std = ic.mean(), ic.std()
        icir = ic_mean / ic_std
        ric_mean, ric_std = ric.mean(), ric.std()
        ricir = ric_mean / ric_std
        ic_positive_ratio = (ic > 0).sum() / len(ic) * 100
        ic_cumsum = ic.cumsum()

        lines.append(f"  IC       均值={ic_mean:.4f}   标准差={ic_std:.4f}   ICIR={icir:.4f}")
        lines.append(f"  Rank IC  均值={ric_mean:.4f}   标准差={ric_std:.4f}   RICIR={ricir:.4f}")
        lines.append(f"  IC>0 天数占比: {ic_positive_ratio:.1f}%  ({(ic > 0).sum()}/{len(ic)} 个交易日)")
        lines.append(f"  IC 累计和: {ic_cumsum.iloc[-1]:.2f}  (共 {len(ic)} 个交易日)")

        subsection("结论")
        if ic_mean >= 0.05:
            lines.append(f"  [强] IC={ic_mean:.4f} >= 0.05，信号强度高，可放心使用。")
        elif ic_mean >= 0.02:
            lines.append(f"  [中] IC={ic_mean:.4f} 在 [0.02, 0.05) 区间，信号可用但不够强。")
        else:
            lines.append(f"  [弱] IC={ic_mean:.4f} < 0.02，信号不可靠，建议重新审视模型或特征。")

        if icir >= 0.5:
            lines.append(f"  [强] ICIR={icir:.4f} >= 0.5，信号非常稳定。")
        elif icir >= 0.3:
            lines.append(f"  [中] ICIR={icir:.4f} 在 [0.3, 0.5) 区间，信号基本稳定。")
        else:
            lines.append(f"  [弱] ICIR={icir:.4f} < 0.3，信号波动过大。")

        if ic_positive_ratio >= 60:
            lines.append(f"  [好] IC>0 占比 {ic_positive_ratio:.1f}% >= 60%，信号多数时间为正。")
        elif ic_positive_ratio >= 50:
            lines.append(f"  [一般] IC>0 占比 {ic_positive_ratio:.1f}% 在 [50%,60%)，仅略优于随机。")
        else:
            lines.append(f"  [差] IC>0 占比 {ic_positive_ratio:.1f}% < 50%，信号经常为负。")

        # IC 衰减分析
        n = len(ic)
        ic_first = ic.iloc[:n//3].mean()
        ic_last = ic.iloc[-n//3:].mean()
        lines.append(f"")
        lines.append(f"  IC 时序稳定性:")
        lines.append(f"    前 1/3 (早期):  IC={ic_first:.4f}")
        lines.append(f"    后 1/3 (近期):  IC={ic_last:.4f}")
        if ic_last < ic_first * 0.5:
            lines.append(f"    [警告] IC 在测试期内衰减了 {(1-ic_last/ic_first)*100:.0f}%。")
            lines.append(f"           模型对近期数据的预测能力明显下降，建议滚动训练或加入时间特征。")
        else:
            lines.append(f"    [正常] IC 无明显衰减，信号稳定性良好。")

    # ── 2. 回测收益 ──
    if "report" in files:
        report_df = load_pkl(files["report"])
        section("2. 回测收益表现  →  return_analysis.png")

        cum_ret = (report_df["return"] - report_df["cost"]).cumsum()
        cum_bench = report_df["bench"].cumsum()
        excess = (report_df["return"] - report_df["bench"] - report_df["cost"]).cumsum()
        dd = excess - excess.cummax()

        total_days = len(report_df)
        start_date = report_df.index[0].strftime("%Y-%m-%d")
        end_date = report_df.index[-1].strftime("%Y-%m-%d")
        years = total_days / 252

        strat_total = cum_ret.iloc[-1] * 100
        bench_total = cum_bench.iloc[-1] * 100
        excess_total = excess.iloc[-1] * 100
        max_dd = dd.min() * 100
        max_dd_date = dd.idxmin().strftime("%Y-%m-%d")

        ann_excess = excess_total / years
        ann_bench = bench_total / years
        ann_strat = strat_total / years

        daily_ret = report_df["return"] - report_df["bench"] - report_df["cost"]
        sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252)

        lines.append(f"  测试区间: {start_date} ~ {end_date}  (共 {total_days} 个交易日, {years:.1f} 年)")
        lines.append(f"")
        lines.append(f"  策略 (含手续费):  累计={strat_total:.1f}%   年化={ann_strat:.1f}%")
        lines.append(f"  基准 (CSI300):    累计={bench_total:.1f}%   年化={ann_bench:.1f}%")
        lines.append(f"  超额 (含手续费):  累计={excess_total:.1f}%   年化={ann_excess:.1f}%")
        lines.append(f"  最大超额回撤:     {max_dd:.1f}%  (发生在 {max_dd_date})")
        lines.append(f"  夏普比率 (超额):  {sharpe:.2f}")

        subsection("结论")
        if excess_total > 0:
            lines.append(f"  [盈利] 超额收益 {excess_total:.1f}% > 0，策略在 {years:.1f} 年内跑赢基准。")
        else:
            lines.append(f"  [亏损] 超额收益 {excess_total:.1f}% < 0，策略跑输基准。")

        if max_dd > -5:
            lines.append(f"  [低风险] 最大回撤 {max_dd:.1f}% < 5%，回撤控制良好。")
        elif max_dd > -15:
            lines.append(f"  [中风险] 最大回撤 {max_dd:.1f}% < 15%，回撤在可接受范围。")
        else:
            lines.append(f"  [高风险] 最大回撤 {max_dd:.1f}% 超过 15%，实盘中可能难以持有。")

        if sharpe >= 1.5:
            lines.append(f"  [优秀] 夏普比率 {sharpe:.2f} >= 1.5，风险调整后收益很高。")
        elif sharpe >= 0.8:
            lines.append(f"  [良好] 夏普比率 {sharpe:.2f} 在 [0.8, 1.5)，风险调整后收益合理。")
        else:
            lines.append(f"  [较差] 夏普比率 {sharpe:.2f} < 0.8，收益不足以补偿风险。")

    # ── 3. 换手率分析 ──
    if "report" in files:
        report_df = load_pkl(files["report"])
        section("3. 换手率与交易成本  →  turnover_analysis.png")

        turnover = report_df["turnover"]
        avg_turnover = turnover.mean()
        max_turnover = turnover.max()
        min_turnover = turnover.min()
        total_cost = report_df["cost"].sum() * 100
        years_tr = len(report_df) / 252

        lines.append(f"  日均换手率: {avg_turnover:.3f} (每日更换持仓组合的 {avg_turnover*100:.1f}%)")
        lines.append(f"  最大换手率: {max_turnover:.3f} (发生在 {turnover.idxmax().strftime('%Y-%m-%d')})")
        lines.append(f"  最小换手率: {min_turnover:.3f} (发生在 {turnover.idxmin().strftime('%Y-%m-%d')})")
        lines.append(f"  累计交易成本: {total_cost:.2f}% (占初始本金)")

        subsection("结论")
        if avg_turnover < 0.1:
            lines.append(f"  [低换手] 日均换手 {avg_turnover:.3f} < 0.1，换手较少，交易成本低。")
        elif avg_turnover < 0.3:
            lines.append(f"  [适中] 日均换手 {avg_turnover:.3f} 在 [0.1, 0.3)，换手率适中。")
        else:
            lines.append(f"  [高换手] 日均换手 {avg_turnover:.3f} >= 0.3，换手频繁，交易成本较高。")

        if total_cost / years_tr > 5:
            lines.append(f"  [注意] 年均交易成本 {total_cost/years_tr:.1f}%，对年化收益侵蚀较大。")
        else:
            lines.append(f"  [正常] 年均交易成本 {total_cost/years_tr:.1f}%，交易成本影响较小。")

    # ── 3. 月度表现 ──
    if "report" in files:
        report_df = load_pkl(files["report"])
        section("4. 月度表现拆解  →  monthly_return.png")

        monthly_excess = report_df.groupby(
            [report_df.index.year, report_df.index.month]
        ).apply(lambda x: (x["return"] - x["bench"] - x["cost"]).sum())

        pos_months = (monthly_excess > 0).sum()
        neg_months = (monthly_excess <= 0).sum()
        total_months = len(monthly_excess)
        best = monthly_excess.max() * 100
        worst = monthly_excess.min() * 100
        best_idx = monthly_excess.idxmax()
        worst_idx = monthly_excess.idxmin()

        lines.append(f"  正超额月份: {pos_months}/{total_months}  ({pos_months/total_months*100:.0f}%)")
        lines.append(f"  最佳月份:  +{best:.1f}%  ({best_idx[0]}-{best_idx[1]:02d})")
        lines.append(f"  最差月份:  {worst:.1f}%  ({worst_idx[0]}-{worst_idx[1]:02d})")

        subsection("各年度超额收益")
        yearly = report_df.groupby(report_df.index.year).apply(
            lambda x: (x["return"] - x["bench"] - x["cost"]).sum()
        )
        for year, ret in yearly.items():
            flag = "+" if ret > 0 else ""
            lines.append(f"    {year}:  {flag}{ret*100:.1f}%")

        subsection("结论")
        if pos_months / total_months >= 0.6:
            lines.append(f"  [稳定] 正超额月份占比 {pos_months/total_months*100:.0f}% >= 60%，策略多数月份跑赢基准。")
        elif pos_months / total_months >= 0.5:
            lines.append(f"  [一般] 正超额月份占比 {pos_months/total_months*100:.0f}%，胜率勉强过半。")
        else:
            lines.append(f"  [差] 正超额月份占比仅 {pos_months/total_months*100:.0f}%，策略经常跑输基准。")

        # 年度稳定性
        all_years_pos = all(ret > 0 for ret in yearly.values)
        worst_year = yearly.idxmin()
        worst_year_ret = yearly.min() * 100
        if all_years_pos:
            lines.append(f"  [稳健] 每个年度均正超额，最差年份 {worst_year} 仍有 +{worst_year_ret:.1f}%。")
        else:
            lines.append(f"  [波动] 存在负超额年份，最弱年份 {worst_year} 超额 {worst_year_ret:.1f}%。")

    # ── 4. 特征重要性 ──
    if "model" in files:
        model = load_pkl(files["model"])
        booster = model.model
        importance = booster.feature_importance(importance_type='gain')
        total_imp = importance.sum()

        fi_data = []
        for i in range(len(importance)):
            name = _ALPHA158_NAMES[i] if i < len(_ALPHA158_NAMES) else f'Col_{i}'
            fi_data.append((name, importance[i], importance[i]/total_imp*100))
        fi_data.sort(key=lambda x: -x[1])

        section("5. 特征重要性分析  →  feature_importance.png")

        top5_share = sum(x[2] for x in fi_data[:5])
        top10_share = sum(x[2] for x in fi_data[:10])
        top20_share = sum(x[2] for x in fi_data[:20])

        lines.append(f"  总特征数: {len(importance)}")
        lines.append(f"  Top 5  特征重要性占比: {top5_share:.1f}%")
        lines.append(f"  Top 10 特征重要性占比: {top10_share:.1f}%")
        lines.append(f"  Top 20 特征重要性占比: {top20_share:.1f}%")

        subsection("Top 10 特征 (按 gain 排序)")
        for rank, (name, imp, pct) in enumerate(fi_data[:10], 1):
            bar = "#" * int(pct * 2)
            lines.append(f"    {rank:2d}. {name:8s}  {pct:5.1f}%  {bar}")

        # 按因子类别统计
        subsection("按因子类别统计")
        categories = {
            "K线形态 (KMID/KLEN/KUP/KLOW/KSFT)": [],
            "价格水位 (OPEN/HIGH/LOW/VWAP)": [],
            "动量 (ROC)": [],
            "均线 (MA)": [],
            "波动率 (STD/BETA)": [],
            "回归残差 (RSQR/RESI)": [],
            "区间位置 (MAX/MIN/RSV/QTLU/QTLD/RANK)": [],
            "时间位置 (IMAX/IMIN/IMXD)": [],
            "量价相关 (CORR/CORD)": [],
            "涨跌天数 (CNTP/CNTN/CNTD)": [],
            "涨跌累加 (SUMP/SUMN/SUMD)": [],
            "量能均线/波动 (VMA/VSTD/WVMA)": [],
            "量能趋势 (VSUMP/VSUMN/VSUMD)": [],
        }
        cat_map = {
            'KMI': 0, 'KLE': 0, 'KUP': 0, 'KLO': 0, 'KSF': 0,
            'OPE': 1, 'HIG': 1, 'LOW': 1, 'VWA': 1,
            'ROC': 2,
            'MA': 3,
            'STD': 4, 'BET': 4,
            'RSQ': 5, 'RES': 5,
            'MAX': 6, 'MIN': 6, 'RSV': 6, 'QTL': 6, 'RAN': 6,
            'IMA': 7, 'IMI': 7, 'IMX': 7,
            'COR': 8,
            'CNT': 9,
            'SUM': 10,
            'VMA': 11, 'VST': 11, 'WVM': 11,
            'VSU': 12,
        }
        cat_idx = list(categories.keys())
        cat_imp = [0.0] * len(cat_idx)
        for name, imp, pct in fi_data:
            prefix = name[:3]
            if prefix in cat_map:
                cat_imp[cat_map[prefix]] += pct
        for cat_name, imp in sorted(zip(cat_idx, cat_imp), key=lambda x: -x[1]):
            if imp > 0.5:
                bar = "#" * int(imp)
                lines.append(f"    {cat_name:50s} {imp:5.1f}%  {bar}")

        subsection("结论")
        if top5_share >= 40:
            lines.append(f"  [集中] Top 5 特征 = {top5_share:.1f}%，模型过度依赖少数因子，存在过拟合风险。")
            lines.append(f"  建议: 尝试剔除低重要性特征以降低噪声。")
        elif top5_share >= 25:
            lines.append(f"  [均衡] Top 5 特征 = {top5_share:.1f}%，模型综合使用了多种信号。")
        else:
            lines.append(f"  [分散] Top 5 特征 = {top5_share:.1f}%，没有单一因子占据主导地位，模型较为稳健。")

    # ── 5. 分组收益 ──
    if "pred" in files and "label" in files:
        pred_df = load_pkl(files["pred"])
        label_df = load_pkl(files["label"])
        merged = pred_df.join(label_df, how='inner')
        merged.columns = ['score', 'label']

        daily_groups = {}
        for dt, day_df in merged.groupby(level='datetime'):
            if len(day_df) < 10:
                continue
            day_df = day_df.sort_values('score')
            groups = pd.qcut(day_df['score'], 5, labels=False, duplicates='drop')
            group_ret = day_df.groupby(groups)['label'].mean()
            daily_groups[dt] = group_ret

        if daily_groups:
            result = pd.DataFrame.from_dict(daily_groups, orient='index')
            result.index = pd.to_datetime(result.index)
            result = result.sort_index()
            avg_ret = result.mean()

            section("6. 5分位分组收益  →  group_return.png")
            labels = ['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)']
            for i in range(len(avg_ret)):
                ann = avg_ret.iloc[i] * 252 * 100
                lines.append(f"  {labels[i]:12s}  日均={avg_ret.iloc[i]*100:+.4f}%   年化={ann:+.1f}%")

            spread = (avg_ret.iloc[-1] - avg_ret.iloc[0]) * 100
            spread_ann = spread * 252
            lines.append(f"")
            lines.append(f"  Q5-Q1 价差:  {spread:.3f}%/天   年化={spread_ann:.1f}%")

            # 单调性检验
            is_monotonic = all(avg_ret.iloc[i] <= avg_ret.iloc[i+1] for i in range(len(avg_ret)-1))
            subsection("结论")
            if is_monotonic:
                lines.append(f"  [完美] 收益从 Q1 到 Q5 严格单调递增。")
                lines.append(f"         模型预测具有优秀的排序能力。")
            else:
                violations = []
                for i in range(len(avg_ret)-1):
                    if avg_ret.iloc[i] > avg_ret.iloc[i+1]:
                        violations.append(f"{labels[i]}({avg_ret.iloc[i]*100:.3f}%) > {labels[i+1]}({avg_ret.iloc[i+1]*100:.3f}%)")
                lines.append(f"  [不完美] 存在 {len(violations)} 处单调性违反:")
                for v in violations:
                    lines.append(f"    {v}")

            if spread_ann >= 30:
                lines.append(f"  [强] 年化价差 {spread_ann:.1f}% >= 30%，信号非常可利用。")
            elif spread_ann >= 15:
                lines.append(f"  [可用] 年化价差 {spread_ann:.1f}% 在 [15%,30%)，可用于组合构建。")
            else:
                lines.append(f"  [弱] 年化价差 {spread_ann:.1f}% < 15%，可能无法覆盖交易成本。")

    # ── 6. 综合评估 ──
    section("7. 综合评估")
    lines.append("")
    lines.append("  本报告与 6 张可视化图表配套生成，")
    lines.append("  所有文件均保存在同一目录下。")
    lines.append("")

    report_text = "\n".join(lines)
    report_path = vis_dir / "analysis_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\nQuantitative report saved: {report_path.relative_to(OUTPUT_DIR)}")
    print(report_text)


# ─────────────────────────────────────────────────────────────
# 滚动训练专属：解析子模型时间窗口 + 绘制窗口图 + 生成报告
# ─────────────────────────────────────────────────────────────
import re as _re
from datetime import datetime as _dt


def parse_rolling_windows(mlruns_dir: Path) -> list:
    """解析滚动训练子模型的时间窗口，返回按 test_start 排序的列表"""
    sub_exp = None
    for d in mlruns_dir.iterdir():
        if d.is_dir() and d.name not in ("0", ".trash", "rolling_visualization"):
            # 检查是否包含多个 recorder（子模型实验）
            recs = [r for r in d.iterdir() if r.is_dir()]
            if len(recs) > 1:
                sub_exp = d
                break
    if sub_exp is None:
        return []

    windows = []
    for rec in sorted(sub_exp.iterdir()):
        if not rec.is_dir():
            continue
        params_dir = rec / "params"
        train_file = params_dir / "dataset.kwargs.segments.train"
        test_file = params_dir / "dataset.kwargs.segments.test"
        if not train_file.exists() or not test_file.exists():
            continue

        def _parse_ts(text):
            m = _re.findall(r"Timestamp\('([^']+)'", text)
            return [_dt.strptime(s[:10], "%Y-%m-%d") for s in m]

        train_ts = _parse_ts(train_file.read_text())
        test_ts = _parse_ts(test_file.read_text())
        if len(train_ts) == 2 and len(test_ts) == 2:
            windows.append({
                "train_start": train_ts[0], "train_end": train_ts[1],
                "test_start": test_ts[0], "test_end": test_ts[1],
                "recorder": rec.name[:8],
            })
    windows.sort(key=lambda w: w["test_start"])
    return windows


def plot_rolling_windows(windows: list, vis_dir: Path):
    """绘制滚动训练窗口示意图（类似甘特图）"""
    if not windows:
        return

    fig, ax = plt.subplots(figsize=(16, max(5, len(windows) * 0.55)))
    fig.suptitle("Rolling Training Windows", fontsize=14, fontweight="bold")

    n = len(windows)
    y_positions = list(range(n))

    for i, w in enumerate(windows):
        # 训练窗口（蓝色）
        train_width = (w["train_end"] - w["train_start"]).days
        ax.barh(i, train_width, left=mdates.date2num(w["train_start"]),
                height=0.4, color="steelblue", alpha=0.6, label="Train" if i == 0 else "")
        # 测试窗口（橙色）
        test_width = (w["test_end"] - w["test_start"]).days
        ax.barh(i, test_width, left=mdates.date2num(w["test_start"]),
                height=0.4, color="orange", alpha=0.85, label="Test" if i == 0 else "")
        # 标注
        ax.text(mdates.date2num(w["train_start"]) - 15, i,
                f"Step {i+1}", va="center", ha="right", fontsize=7, color="#555")

    ax.set_yticks(y_positions)
    ax.set_yticklabels([
        f"{w['test_start'].strftime('%Y-%m')} ~ {w['test_end'].strftime('%Y-%m')}"
        for w in windows
    ], fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.set_xlabel("Date")
    ax.legend(loc="upper right")
    ax.invert_yaxis()
    ax.grid(True, axis="x", alpha=0.3)

    plt.tight_layout()
    plt.savefig(vis_dir / "rolling_windows.png", dpi=150, bbox_inches="tight")
    plt.show()


def _load_static_for_comparison() -> dict:
    """尝试加载静态训练的结果用于对比，返回 files dict 或空 dict"""
    static_dir = OUTPUT_DIR / "mlruns_static"
    if not static_dir.exists():
        return {}
    try:
        exp_dirs = [d for d in static_dir.iterdir() if d.is_dir() and d.name not in ("0", ".trash")]
        if not exp_dirs:
            return {}
        exp_dir = sorted(exp_dirs, key=lambda d: d.stat().st_mtime)[-1]
        rec_dirs = [d for d in exp_dir.iterdir() if d.is_dir()]
        rec_dir = sorted(rec_dirs, key=lambda d: d.stat().st_mtime)[-1]
        artifacts = rec_dir / "artifacts"
        files = {}
        for key, rel in [("ic", "sig_analysis/ic.pkl"), ("report", "portfolio_analysis/report_normal_1day.pkl")]:
            p = artifacts / rel
            if p.exists():
                files[key] = p
        return files
    except Exception:
        return {}


def generate_rolling_html_report(files: dict, vis_dir: Path, windows: list):
    """生成滚动训练专属 HTML 报告：窗口图 + 合并结果分析 + 静态 vs 滚动对比"""
    sections = []

    # ── 0. 滚动训练概览 + 窗口图 ──
    win_rows = ""
    for i, w in enumerate(windows):
        train_months = (w["train_end"].year - w["train_start"].year) * 12 + w["train_end"].month - w["train_start"].month
        test_months = (w["test_end"].year - w["test_start"].year) * 12 + w["test_end"].month - w["test_start"].month
        win_rows += (f'<tr><td>Step {i+1}</td>'
                     f'<td>{w["train_start"].strftime("%Y-%m")} ~ {w["train_end"].strftime("%Y-%m")} ({train_months}月)</td>'
                     f'<td>{w["test_start"].strftime("%Y-%m")} ~ {w["test_end"].strftime("%Y-%m")} ({test_months}月)</td></tr>\n')

    metrics = f"""
    <table class="metrics-table">
      <tr><td>子模型数量</td><td><b>{len(windows)}</b></td><td>每个子模型覆盖一个测试窗口</td></tr>
      <tr><td>训练起始</td><td>{windows[0]['train_start'].strftime('%Y-%m-%d')}</td><td>所有子模型共享同一训练起点</td></tr>
      <tr><td>测试范围</td><td><b>{windows[0]['test_start'].strftime('%Y-%m')} ~ {windows[-1]['test_end'].strftime('%Y-%m')}</b></td><td>拼接后覆盖完整测试期</td></tr>
    </table>
    <h4>各 Step 时间窗口明细</h4>
    <table class="metrics-table">
      <tr><th>Step</th><th>训练区间</th><th>测试区间</th></tr>
      {win_rows}
    </table>"""

    conclusions = []
    conclusions.append(_conclusion_html("提示",
        f"滚动训练共产生 <b>{len(windows)}</b> 个子模型，每个子模型用不断扩展的历史数据训练，"
        "然后预测未来约 3 个月的股票收益。最终把所有子模型的预测拼接起来，得到完整的回测结果。"
        "这就像你在实际交易中，每隔一段时间就用最新数据重新训练模型一样。"))
    conclusions.append(_conclusion_html("提示",
        "上方窗口图展示了每个 Step 的训练区间（蓝色）和测试区间（橙色）。"
        "训练窗口不断扩展（expanding window），测试窗口连续拼接覆盖整个测试期。"))

    img_b64 = _img_to_base64(vis_dir / "rolling_windows.png")
    sections.append(("1. 滚动训练窗口概览", img_b64, metrics, "\n".join(conclusions),
        "滚动训练的核心思想：用「过去的数据」训练模型，预测「未来」的收益，然后定期用最新数据重新训练。"
        "这样能避免模型学到已经过时的市场规律（静态训练中常见的 IC 衰减问题）。"))

    # ── 1-6: 合并结果分析（复用 generate_html_report 的图表） ──
    # 先调用 generate_html_report 获取标准分析段落，然后截取 sections 1-6
    # 为避免重复代码，直接在这里构建合并结果的分析
    if "ic" in files and "ric" in files:
        ic_s = load_pkl(files["ic"])
        ric_s = load_pkl(files["ric"])
        ic = ic_s.iloc[:, 0] if isinstance(ic_s, pd.DataFrame) else ic_s
        ric = ric_s.iloc[:, 0] if isinstance(ric_s, pd.DataFrame) else ric_s
        ic_mean, ic_std = ic.mean(), ic.std()
        icir = ic_mean / ic_std
        ric_mean, ric_std = ric.mean(), ric.std()
        ricir = ric_mean / ric_std
        ic_pos_ratio = (ic > 0).sum() / len(ic) * 100
        ic_cumsum = ic.cumsum()
        n = len(ic)
        ic_first = ic.iloc[:n//3].mean()
        ic_last = ic.iloc[-n//3:].mean()
        decay_pct = (1 - ic_last / ic_first) * 100 if ic_first != 0 else 0

        metrics = f"""
        <table class="metrics-table">
          <tr><td>IC 均值</td><td><b>{ic_mean:.4f}</b></td><td>滚动合并后的信号强度</td></tr>
          <tr><td>ICIR</td><td><b>{icir:.4f}</b></td><td>信号信噪比</td></tr>
          <tr><td>Rank IC</td><td>{ric_mean:.4f}</td><td>秩相关 IC</td></tr>
          <tr><td>IC>0 占比</td><td>{ic_pos_ratio:.1f}%</td><td>信号为正的交易日比例</td></tr>
          <tr><td>IC 累计和</td><td>{ic_cumsum.iloc[-1]:.2f}</td><td>累积预测能力</td></tr>
        </table>"""

        conclusions = []
        if ic_mean >= 0.05:
            conclusions.append(_conclusion_html("强",
                f"滚动合并后 IC={ic_mean:.4f} ≥ 0.05，说明滚动训练成功恢复了信号强度。"
                "每个子模型都用了最新数据训练，因此整体信号比静态训练更强。"))
        elif ic_mean >= 0.02:
            conclusions.append(_conclusion_html("中",
                f"滚动合并后 IC={ic_mean:.4f}，信号可用但不算强。"
                "对比静态训练的 IC 看是否有提升（见下方对比表）。"))
        else:
            conclusions.append(_conclusion_html("弱",
                f"滚动合并后 IC={ic_mean:.4f} < 0.02，即使滚动训练也没能改善信号，需要回到因子优化。"))

        if ic_last < ic_first * 0.5:
            conclusions.append(_conclusion_html("警告",
                f"IC 仍然衰减了 {decay_pct:.0f}%（早期 {ic_first:.4f} → 近期 {ic_last:.4f}）。"
                "这说明即使用了滚动训练，信号仍在衰减——问题可能在于因子本身在近期市场失效，而不仅仅是模型过时。"))
        else:
            conclusions.append(_conclusion_html("正常",
                f"IC 无明显衰减（早期 {ic_first:.4f} → 近期 {ic_last:.4f}），滚动训练成功维持了信号稳定性。"))

        img_b64 = _img_to_base64(vis_dir / "ic_analysis.png")
        sections.append(("2. 预测信号质量（滚动合并）", img_b64, metrics, "\n".join(conclusions),
            "这里是所有子模型预测结果拼接后的 IC 分析。与静态训练不同，每个时间段的预测都来自「当时最新」的模型，"
            "所以 IC 时序图应该更平稳、衰减更少。"))

    # 回测收益
    if "report" in files:
        report_df = load_pkl(files["report"])
        cum_ret = (report_df["return"] - report_df["cost"]).cumsum()
        cum_bench = report_df["bench"].cumsum()
        excess = (report_df["return"] - report_df["bench"] - report_df["cost"]).cumsum()
        dd = excess - excess.cummax()
        years = len(report_df) / 252
        strat_total = cum_ret.iloc[-1] * 100
        bench_total = cum_bench.iloc[-1] * 100
        excess_total = excess.iloc[-1] * 100
        max_dd = dd.min() * 100
        max_dd_date = dd.idxmin().strftime("%Y-%m-%d")
        ann_excess = excess_total / years
        daily_ret = report_df["return"] - report_df["bench"] - report_df["cost"]
        sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252)

        metrics = f"""
        <table class="metrics-table">
          <tr><td>测试区间</td><td>{report_df.index[0].strftime('%Y-%m-%d')} ~ {report_df.index[-1].strftime('%Y-%m-%d')}</td><td>{len(report_df)} 个交易日 ({years:.1f}年)</td></tr>
          <tr><td>策略累计 (含手续费)</td><td><b>{strat_total:.1f}%</b></td><td>年化 {strat_total/years:.1f}%</td></tr>
          <tr><td>基准累计 (CSI300)</td><td>{bench_total:.1f}%</td><td>年化 {bench_total/years:.1f}%</td></tr>
          <tr><td>超额 (含手续费)</td><td><b>{excess_total:.1f}%</b></td><td>年化 {ann_excess:.1f}%</td></tr>
          <tr><td>最大超额回撤</td><td><b>{max_dd:.1f}%</b></td><td>发生在 {max_dd_date}</td></tr>
          <tr><td>夏普比率</td><td><b>{sharpe:.2f}</b></td><td>收益/风险比</td></tr>
        </table>"""

        conclusions = []
        conclusions.append(_conclusion_html("盈利" if excess_total > 0 else "亏损",
            f"滚动训练合并后超额收益 {excess_total:.1f}%（年化 {ann_excess:.1f}%），"
            "这是更接近真实实盘表现的数字——因为每个时间段的预测都来自「当时最新」的模型，没有未来数据泄露。"))

        if max_dd > -5:
            conclusions.append(_conclusion_html("低风险",
                f"最大超额回撤仅 {max_dd:.1f}%，滚动训练后回撤控制比静态训练更好。"))
        elif max_dd > -15:
            conclusions.append(_conclusion_html("中风险",
                f"最大超额回撤 {max_dd:.1f}%，在可接受范围。"))
        else:
            conclusions.append(_conclusion_html("高风险",
                f"最大超额回撤 {max_dd:.1f}%，需要进一步优化。"))

        if sharpe >= 1.5:
            conclusions.append(_conclusion_html("优秀",
                f"夏普比率 {sharpe:.2f} ≥ 1.5，风险调整后收益很高，策略具备实盘部署条件。"))
        elif sharpe >= 0.8:
            conclusions.append(_conclusion_html("良好",
                f"夏普比率 {sharpe:.2f}，风险调整后收益合理，可用于实盘。"))
        else:
            conclusions.append(_conclusion_html("较差",
                f"夏普比率 {sharpe:.2f} < 0.8，建议回到迭代优化阶段。"))

        img_b64 = _img_to_base64(vis_dir / "return_analysis.png")
        sections.append(("3. 回测收益表现（滚动合并）", img_b64, metrics, "\n".join(conclusions),
            "这是滚动训练的「真实」回测结果。与静态训练的关键区别：静态训练一次性用所有数据训练，"
            "模型可能学到未来信息；滚动训练每个时间段只用「过去」数据训练，所以这里的结果更可信。"))

        # 换手率
        turnover = report_df["turnover"]
        avg_to = turnover.mean()
        total_cost = report_df["cost"].sum() * 100
        ann_cost = total_cost / years

        metrics = f"""
        <table class="metrics-table">
          <tr><td>日均换手率</td><td><b>{avg_to:.3f}</b></td><td>每日更换 {avg_to*100:.1f}% 持仓</td></tr>
          <tr><td>年均交易成本</td><td>{ann_cost:.1f}%</td><td>对收益的侵蚀</td></tr>
        </table>"""
        conclusions = [_conclusion_html("适中" if avg_to < 0.3 else "高换手",
            f"日均换手 {avg_to:.3f}，年均交易成本 {ann_cost:.1f}%。" +
            ("换手率适中，交易成本影响较小。" if ann_cost < 5 else "交易成本较高，注意对收益的侵蚀。"))]
        img_b64 = _img_to_base64(vis_dir / "turnover_analysis.png")
        sections.append(("4. 换手率与交易成本", img_b64, metrics, "\n".join(conclusions),
            "换手率反映策略的交易频率，高换手 = 高成本。"))

        # 月度表现
        monthly_excess = report_df.groupby(
            [report_df.index.year, report_df.index.month]
        ).apply(lambda x: (x["return"] - x["bench"] - x["cost"]).sum())
        pos_months = (monthly_excess > 0).sum()
        total_months = len(monthly_excess)
        yearly = report_df.groupby(report_df.index.year).apply(
            lambda x: (x["return"] - x["bench"] - x["cost"]).sum()
        )
        yearly_rows = "".join(
            f'<tr><td>{y}</td><td>{"+" if r>0 else ""}{r*100:.1f}%</td></tr>'
            for y, r in yearly.items()
        )
        metrics = f"""
        <table class="metrics-table">
          <tr><td>正超额月份</td><td><b>{pos_months}/{total_months} ({pos_months/total_months*100:.0f}%)</b></td></tr>
          <tr><td>最佳月份</td><td>+{monthly_excess.max()*100:.1f}%</td></tr>
          <tr><td>最差月份</td><td>{monthly_excess.min()*100:.1f}%</td></tr>
        </table>
        <h4>各年度超额收益</h4>
        <table class="metrics-table">{yearly_rows}</table>"""
        conclusions = []
        all_pos = all(r > 0 for r in yearly.values)
        conclusions.append(_conclusion_html("稳定" if pos_months/total_months >= 0.6 else "一般",
            f"正超额月份占比 {pos_months/total_months*100:.0f}%。"))
        if all_pos:
            conclusions.append(_conclusion_html("稳健",
                f"每个年度均正超额，最差年份 {yearly.idxmin()} 仍有 +{yearly.min()*100:.1f}%。"))
        img_b64 = _img_to_base64(vis_dir / "monthly_return.png")
        sections.append(("5. 月度表现拆解", img_b64, metrics, "\n".join(conclusions),
            "月度热力图展示策略逐月表现，绿色=跑赢基准，红色=跑输。"))

    # 分组收益
    if "pred" in files and "label" in files:
        pred_df = load_pkl(files["pred"])
        label_df = load_pkl(files["label"])
        merged = pred_df.join(label_df, how='inner')
        merged.columns = ['score', 'label']
        daily_groups = {}
        for dt, day_df in merged.groupby(level='datetime'):
            if len(day_df) < 10:
                continue
            day_df = day_df.sort_values('score')
            groups = pd.qcut(day_df['score'], 5, labels=False, duplicates='drop')
            group_ret = day_df.groupby(groups)['label'].mean()
            daily_groups[dt] = group_ret
        if daily_groups:
            result = pd.DataFrame.from_dict(daily_groups, orient='index')
            result.index = pd.to_datetime(result.index)
            result = result.sort_index()
            avg_ret = result.mean()
            labels = ['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)']
            q_rows = "".join(
                f'<tr><td>{labels[i]}</td><td>{avg_ret.iloc[i]*100:+.4f}%</td>'
                f'<td>{avg_ret.iloc[i]*252*100:+.1f}%</td></tr>'
                for i in range(len(avg_ret))
            )
            spread = (avg_ret.iloc[-1] - avg_ret.iloc[0]) * 100
            spread_ann = spread * 252
            is_monotonic = all(avg_ret.iloc[i] <= avg_ret.iloc[i+1] for i in range(len(avg_ret)-1))
            metrics = f"""
            <table class="metrics-table">
              <tr><th>分位</th><th>日均收益</th><th>年化收益</th></tr>
              {q_rows}
              <tr><td><b>Q5-Q1</b></td><td><b>{spread:.3f}%/天</b></td><td><b>年化 {spread_ann:.1f}%</b></td></tr>
            </table>"""
            conclusions = []
            if is_monotonic:
                conclusions.append(_conclusion_html("完美",
                    "收益从 Q1 到 Q5 严格单调递增，模型排序能力优秀。"))
            else:
                conclusions.append(_conclusion_html("不完美",
                    "存在单调性违反，但 Q1 和 Q5 的分化仍然明显。"))
            if spread_ann >= 30:
                conclusions.append(_conclusion_html("强",
                    f"年化价差 {spread_ann:.1f}%，多空分化非常可观。"))
            img_b64 = _img_to_base64(vis_dir / "group_return.png")
            sections.append(("6. 5分位分组收益", img_b64, metrics, "\n".join(conclusions),
                "分组收益展示模型选股能力：Q5=模型看好的股票，Q1=模型不看好的。"))

    # ── 7. 静态 vs 滚动对比 ──
    static_files = _load_static_for_comparison()
    if static_files and "ic" in static_files and "ic" in files:
        s_ic = load_pkl(static_files["ic"])
        s_ic = s_ic.iloc[:, 0] if isinstance(s_ic, pd.DataFrame) else s_ic
        s_ic_mean = s_ic.mean()
        s_icir = s_ic_mean / s_ic.std()
        s_n = len(s_ic)
        s_ic_first = s_ic.iloc[:s_n//3].mean()
        s_ic_last = s_ic.iloc[-s_n//3:].mean()
        s_decay = (1 - s_ic_last / s_ic_first) * 100 if s_ic_first != 0 else 0

        r_ic = load_pkl(files["ic"])
        r_ic = r_ic.iloc[:, 0] if isinstance(r_ic, pd.DataFrame) else r_ic
        r_ic_mean = r_ic.mean()
        r_icir = r_ic_mean / r_ic.std()
        r_n = len(r_ic)
        r_ic_first = r_ic.iloc[:r_n//3].mean()
        r_ic_last = r_ic.iloc[-r_n//3:].mean()
        r_decay = (1 - r_ic_last / r_ic_first) * 100 if r_ic_first != 0 else 0

        # 收益对比
        s_sharpe_str, r_sharpe_str = "N/A", "N/A"
        s_excess_str, r_excess_str = "N/A", "N/A"
        s_dd_str, r_dd_str = "N/A", "N/A"
        if "report" in static_files and "report" in files:
            s_rpt = load_pkl(static_files["report"])
            r_rpt = load_pkl(files["report"])
            s_exc = (s_rpt["return"] - s_rpt["bench"] - s_rpt["cost"]).cumsum()
            r_exc = (r_rpt["return"] - r_rpt["bench"] - r_rpt["cost"]).cumsum()
            s_yrs = len(s_rpt) / 252
            r_yrs = len(r_rpt) / 252
            s_excess_str = f"{s_exc.iloc[-1]*100:.1f}% (年化 {s_exc.iloc[-1]/s_yrs*100:.1f}%)"
            r_excess_str = f"{r_exc.iloc[-1]*100:.1f}% (年化 {r_exc.iloc[-1]/r_yrs*100:.1f}%)"
            s_dd = s_exc - s_exc.cummax()
            r_dd = r_exc - r_exc.cummax()
            s_dd_str = f"{s_dd.min()*100:.1f}%"
            r_dd_str = f"{r_dd.min()*100:.1f}%"
            s_dr = s_rpt["return"] - s_rpt["bench"] - s_rpt["cost"]
            r_dr = r_rpt["return"] - r_rpt["bench"] - r_rpt["cost"]
            s_sharpe_str = f"{s_dr.mean()/s_dr.std()*np.sqrt(252):.2f}"
            r_sharpe_str = f"{r_dr.mean()/r_dr.std()*np.sqrt(252):.2f}"

        metrics = f"""
        <table class="metrics-table" style="font-size:1em;">
          <tr><th style="width:25%">指标</th><th style="width:30%">静态训练</th><th style="width:30%">滚动训练</th><th>变化</th></tr>
          <tr><td>IC 均值</td><td>{s_ic_mean:.4f}</td><td><b>{r_ic_mean:.4f}</b></td>
              <td>{"+" if r_ic_mean>s_ic_mean else ""}{(r_ic_mean-s_ic_mean):.4f}</td></tr>
          <tr><td>ICIR</td><td>{s_icir:.4f}</td><td><b>{r_icir:.4f}</b></td>
              <td>{"+" if r_icir>s_icir else ""}{(r_icir-s_icir):.4f}</td></tr>
          <tr><td>IC 衰减</td><td>{s_decay:.0f}%</td><td><b>{r_decay:.0f}%</b></td>
              <td>{"改善" if r_decay < s_decay else "无改善"}</td></tr>
          <tr><td>超额收益</td><td>{s_excess_str}</td><td><b>{r_excess_str}</b></td><td>-</td></tr>
          <tr><td>最大回撤</td><td>{s_dd_str}</td><td><b>{r_dd_str}</b></td><td>-</td></tr>
          <tr><td>夏普比率</td><td>{s_sharpe_str}</td><td><b>{r_sharpe_str}</b></td><td>-</td></tr>
        </table>"""

        conclusions = []
        ic_change = r_ic_mean - s_ic_mean
        if ic_change > 0.005:
            conclusions.append(_conclusion_html("改善",
                f"IC 从 {s_ic_mean:.4f} 提升到 {r_ic_mean:.4f}（+{ic_change:.4f}），"
                "滚动训练成功提升了信号强度。这证明市场规律在演变，定期重新训练是有效的。"))
        elif ic_change > -0.005:
            conclusions.append(_conclusion_html("持平",
                f"IC 从 {s_ic_mean:.4f} 变为 {r_ic_mean:.4f}，变化不大（{ic_change:+.4f}）。"
                "滚动训练没有显著提升 IC，但至少没有恶化。滚动训练的核心价值不在于提升 IC，"
                "而在于提供更真实的实盘预期。"))
        else:
            conclusions.append(_conclusion_html("退化",
                f"IC 从 {s_ic_mean:.4f} 下降到 {r_ic_mean:.4f}（{ic_change:.4f}）。"
                "滚动训练后 IC 反而下降，可能原因：(1) 近期市场风格变化导致因子失效；"
                "(2) 训练数据不够多（检查数据是否更新到最新）。"))

        if r_decay < s_decay * 0.8:
            conclusions.append(_conclusion_html("改善",
                f"IC 衰减从 {s_decay:.0f}% 降到 {r_decay:.0f}%，滚动训练成功减缓了信号衰减。"
                "这意味着策略在近期的表现更可靠。"))
        else:
            conclusions.append(_conclusion_html("提示",
                f"IC 衰减情况类似（静态 {s_decay:.0f}% vs 滚动 {r_decay:.0f}%），"
                "问题可能不在模型而在因子本身——需要考虑更新因子集。"))

        conclusions.append(_conclusion_html("下一步",
            "如果滚动训练的夏普 ≥ 0.8、年化超额 ≥ 8%、最大回撤 > -15%，"
            "策略已具备实盘部署条件，可进入【阶段7-实盘信号生成】。"
            "否则回到【阶段5-迭代优化】继续调优。"))

        sections.append(("7. 静态 vs 滚动对比", "", metrics, "\n".join(conclusions),
            "这是最关键的对比：同样的因子+模型，静态训练 vs 滚动训练的表现差异。"
            "静态训练的结果通常过于乐观（有未来信息泄露），滚动训练的结果才是你对实盘表现的合理预期。"))
    else:
        conclusions = [_conclusion_html("提示",
            "未找到静态训练结果（mlruns_static），无法进行对比。"
            "如需对比，请先确保静态训练产物存在。")]
        sections.append(("7. 静态 vs 滚动对比", "", "", "\n".join(conclusions), ""))

    # ── 组装 HTML ──
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>Rolling Training Analysis Report</title>",
        "<style>",
        "  body { font-family: -apple-system, 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; "
        "         max-width: 1100px; margin: 0 auto; padding: 20px 30px; "
        "         background: #fafafa; color: #333; line-height: 1.7; }",
        "  h1 { text-align: center; color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 12px; }",
        "  h2 { color: #1565c0; border-left: 5px solid #1565c0; padding-left: 12px; margin-top: 50px; }",
        "  h4 { color: #555; margin: 12px 0 6px; }",
        "  .section { background: white; border-radius: 8px; padding: 24px; margin: 20px 0; "
        "             box-shadow: 0 2px 8px rgba(0,0,0,0.08); }",
        "  .chart-container { text-align: center; margin: 16px 0; }",
        "  .chart-container img { max-width: 100%; border: 1px solid #e0e0e0; border-radius: 4px; }",
        "  .explain { background: #e8eaf6; border-radius: 6px; padding: 12px 16px; "
        "             font-size: 0.92em; color: #37474f; margin: 12px 0; }",
        "  .metrics-table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.95em; }",
        "  .metrics-table td, .metrics-table th { padding: 6px 12px; border-bottom: 1px solid #e0e0e0; text-align: left; }",
        "  .metrics-table th { background: #f5f5f5; font-weight: 600; }",
        "  .metrics-table td:first-child { color: #555; min-width: 140px; }",
        "  .metrics-table td:last-child { color: #888; font-size: 0.9em; }",
        "  .conclusions { margin-top: 16px; }",
        "  .conclusions h3 { color: #2e7d32; font-size: 1.05em; margin-bottom: 8px; }",
        "  .conclusion-item { display: flex; align-items: flex-start; gap: 10px; "
        "                     padding: 8px 0; border-bottom: 1px solid #f0f0f0; }",
        "  .tag { display: inline-block; padding: 2px 10px; border-radius: 4px; color: white; "
        "         font-size: 0.85em; font-weight: 600; white-space: nowrap; min-width: 50px; text-align: center; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>LightGBM + Alpha158 滚动训练分析报告</h1>",
        '<p style="text-align:center;color:#666;">滚动训练通过定期重新训练模型来对抗信号衰减，提供更接近真实实盘的表现评估。</p>',
    ]

    for title, img_b64, metrics_html, conclusions_html, explain_text in sections:
        html_parts.append(f'<div class="section">')
        html_parts.append(f"<h2>{title}</h2>")
        if explain_text:
            html_parts.append(f'<div class="explain">{explain_text}</div>')
        if img_b64:
            html_parts.append(f'<div class="chart-container"><img src="{img_b64}" alt="{title}"></div>')
        if metrics_html:
            html_parts.append(f'<h4>核心指标</h4>{metrics_html}')
        if conclusions_html:
            html_parts.append(f'<div class="conclusions"><h3>结论与解读</h3>{conclusions_html}</div>')
        html_parts.append("</div>")

    html_parts.extend(["</body>", "</html>"])

    html_text = "\n".join(html_parts)
    html_path = vis_dir / "rolling_analysis_report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"\nRolling HTML report saved: {html_path.relative_to(OUTPUT_DIR)}")
    return html_path


# ─────────────────────────────────────────────────────────────
# HTML 综合报告（图表 + 详细结论一体化）
# ─────────────────────────────────────────────────────────────
def _img_to_base64(path: Path) -> str:
    """将图片文件转为 base64 data URI"""
    import base64
    if not path.exists():
        return ""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


def _conclusion_html(label: str, text: str) -> str:
    """生成单条结论 HTML，根据标签着色"""
    color_map = {
        "强": "#2e7d32", "优秀": "#2e7d32", "好": "#2e7d32", "盈利": "#2e7d32",
        "完美": "#2e7d32", "稳定": "#2e7d32", "稳健": "#2e7d32", "良好": "#2e7d32",
        "分散": "#2e7d32", "低风险": "#2e7d32", "正常": "#2e7d32", "低换手": "#2e7d32",
        "中": "#e65100", "中风险": "#e65100", "适中": "#e65100", "均衡": "#e65100",
        "可用": "#e65100", "一般": "#e65100",
        "弱": "#c62828", "差": "#c62828", "差": "#c62828", "亏损": "#c62828",
        "高风险": "#c62828", "高换手": "#c62828", "较差": "#c62828", "波动": "#c62828",
        "集中": "#c62828", "不完美": "#e65100",
        "警告": "#c62828", "注意": "#e65100",
        "通过": "#2e7d32", "达标": "#2e7d32",
        "未达标": "#c62828", "待优化": "#e65100",
        "下一步": "#1565c0", "提示": "#1565c0",
        "改善": "#2e7d32", "退化": "#c62828", "持平": "#e65100",
    }
    color = color_map.get(label, "#333")
    return f'<div class="conclusion-item"><span class="tag" style="background:{color}">{label}</span><span>{text}</span></div>'


def generate_html_report(files: dict, vis_dir: Path):
    """生成 HTML 综合报告：每章节嵌入图片 + 详细中文结论"""
    sections = []  # 每个元素是 (title, img_b64, metrics_html, conclusions_html)

    # ── 1. 预测信号质量 ──
    if "ic" in files and "ric" in files:
        ic_s = load_pkl(files["ic"])
        ric_s = load_pkl(files["ric"])
        ic = ic_s.iloc[:, 0] if isinstance(ic_s, pd.DataFrame) else ic_s
        ric = ric_s.iloc[:, 0] if isinstance(ric_s, pd.DataFrame) else ric_s
        ic_mean, ic_std = ic.mean(), ic.std()
        icir = ic_mean / ic_std
        ric_mean, ric_std = ric.mean(), ric.std()
        ricir = ric_mean / ric_std
        ic_pos_ratio = (ic > 0).sum() / len(ic) * 100
        ic_cumsum = ic.cumsum()
        n = len(ic)
        ic_first = ic.iloc[:n//3].mean()
        ic_last = ic.iloc[-n//3:].mean()
        decay_pct = (1 - ic_last / ic_first) * 100 if ic_first != 0 else 0

        metrics = f"""
        <table class="metrics-table">
          <tr><td>IC 均值</td><td><b>{ic_mean:.4f}</b></td><td>模型预测排名 vs 真实排名的线性相关度</td></tr>
          <tr><td>IC 标准差</td><td>{ic_std:.4f}</td><td>IC 的日间波动幅度</td></tr>
          <tr><td>ICIR</td><td><b>{icir:.4f}</b></td><td>IC均值/IC标准差，信号的信噪比</td></tr>
          <tr><td>Rank IC 均值</td><td>{ric_mean:.4f}</td><td>用秩相关计算的 IC，对异常值更鲁棒</td></tr>
          <tr><td>Rank ICIR</td><td>{ricir:.4f}</td><td>Rank IC 的信噪比</td></tr>
          <tr><td>IC>0 占比</td><td>{ic_pos_ratio:.1f}%</td><td>{(ic>0).sum()}/{len(ic)} 天信号为正</td></tr>
          <tr><td>IC 累计和</td><td>{ic_cumsum.iloc[-1]:.2f}</td><td>累积预测能力，越高越好</td></tr>
        </table>"""

        conclusions = []
        # IC 强度
        if ic_mean >= 0.05:
            conclusions.append(_conclusion_html("强",
                f"IC={ic_mean:.4f} ≥ 0.05，信号强度高。模型每天对全市场股票的排序预测与真实收益排序高度相关，可直接用于实盘选股。"))
        elif ic_mean >= 0.02:
            conclusions.append(_conclusion_html("中",
                f"IC={ic_mean:.4f}，处于 [0.02, 0.05) 区间。信号可用但不够强——模型有一定选股能力，但预测噪声较大。"
                "在实盘中需要通过分散持仓（如持有 30-50 只股票）来利用大数定律放大微弱信号。"
                "建议进入【阶段5-迭代优化】尝试提升：(1) 剔除低重要性因子减少噪声；(2) 调参提升模型拟合能力。"))
        else:
            conclusions.append(_conclusion_html("弱",
                f"IC={ic_mean:.4f} < 0.02，信号不可靠。模型几乎没有排序能力，需要回到【阶段2-因子构建】重新审视因子集和标签定义。"))

        # ICIR
        if icir >= 0.5:
            conclusions.append(_conclusion_html("强",
                f"ICIR={icir:.4f} ≥ 0.5，信号非常稳定。说明模型不是偶尔猜对，而是持续稳定地输出有效信号。"))
        elif icir >= 0.3:
            conclusions.append(_conclusion_html("中",
                f"ICIR={icir:.4f}，处于 [0.3, 0.5) 区间。信号基本稳定但波动较大——某些市场环境下模型会失效。"
                "这个值在量化领域属于中等水平，可通过滚动训练来改善稳定性。"))
        else:
            conclusions.append(_conclusion_html("弱",
                f"ICIR={icir:.4f} < 0.3，信号波动过大。即使 IC 均值看着还行，但日间波动太大，实盘中难以稳定获利。"))

        # IC 正占比
        if ic_pos_ratio >= 60:
            conclusions.append(_conclusion_html("好",
                f"IC>0 占比 {ic_pos_ratio:.1f}%，超过 60% 的交易日信号为正。说明模型在大多数市场环境下都能选到好股票。"))
        elif ic_pos_ratio >= 50:
            conclusions.append(_conclusion_html("一般",
                f"IC>0 占比 {ic_pos_ratio:.1f}%，仅略优于抛硬币。接近一半的时间模型在做反向预测，需检查因子或模型是否适配当前市场。"))
        else:
            conclusions.append(_conclusion_html("差",
                f"IC>0 占比仅 {ic_pos_ratio:.1f}%，模型经常做出反向预测。"))

        # IC 衰减
        if ic_last < ic_first * 0.5:
            conclusions.append(_conclusion_html("警告",
                f"IC 在测试期内从 {ic_first:.4f} 衰减到 {ic_last:.4f}，衰减了 {decay_pct:.0f}%。"
                "这意味着模型在早期数据上表现好，但在近期数据上能力大幅下降。"
                "这是量化交易中非常典型的现象——市场规律随时间演变（政策变化、风格切换）。"
                f"<b>这就是你下一步要做滚动训练的核心原因</b>：滚动训练通过定期用最新数据重新训练模型，"
                "来对抗这种信号衰减，模拟真实的实盘体验。"))
        else:
            conclusions.append(_conclusion_html("正常",
                f"IC 无明显衰减（早期 {ic_first:.4f} → 近期 {ic_last:.4f}），信号稳定性良好。"))

        conclusions_html = "\n".join(conclusions)
        img_b64 = _img_to_base64(vis_dir / "ic_analysis.png")
        sections.append(("1. 预测信号质量（IC / Rank IC）", img_b64, metrics, conclusions_html,
            "IC（信息系数）衡量模型预测的股票排名和真实收益排名的相关性。"
            "IC=0.05 看似很低，但在金融市场中这已经是强信号——因为你每天对数百只股票做预测，"
            "通过分散投资和大数定律，微弱的 IC 也能转化为稳定的超额收益。"
            "IC 时序图观察信号是否持续为正；IC 分布图看是否集中在正值一侧；"
            "IC 累计和曲线观察是否持续上升（中途大幅回调说明某段时期模型失效）。"))

    # ── 2. 回测收益表现 ──
    if "report" in files:
        report_df = load_pkl(files["report"])
        cum_ret = (report_df["return"] - report_df["cost"]).cumsum()
        cum_bench = report_df["bench"].cumsum()
        excess = (report_df["return"] - report_df["bench"] - report_df["cost"]).cumsum()
        dd = excess - excess.cummax()
        total_days = len(report_df)
        years = total_days / 252
        strat_total = cum_ret.iloc[-1] * 100
        bench_total = cum_bench.iloc[-1] * 100
        excess_total = excess.iloc[-1] * 100
        max_dd = dd.min() * 100
        max_dd_date = dd.idxmin().strftime("%Y-%m-%d")
        ann_excess = excess_total / years
        ann_strat = strat_total / years
        ann_bench = bench_total / years
        daily_ret = report_df["return"] - report_df["bench"] - report_df["cost"]
        sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252)
        start_date = report_df.index[0].strftime("%Y-%m-%d")
        end_date = report_df.index[-1].strftime("%Y-%m-%d")

        metrics = f"""
        <table class="metrics-table">
          <tr><td>测试区间</td><td><b>{start_date} ~ {end_date}</b></td><td>共 {total_days} 个交易日 ({years:.1f} 年)</td></tr>
          <tr><td>策略累计收益 (含手续费)</td><td><b>{strat_total:.1f}%</b></td><td>年化 {ann_strat:.1f}%</td></tr>
          <tr><td>基准累计收益 (CSI300)</td><td>{bench_total:.1f}%</td><td>年化 {ann_bench:.1f}%</td></tr>
          <tr><td>超额收益 (含手续费)</td><td><b>{excess_total:.1f}%</b></td><td>年化 {ann_excess:.1f}%</td></tr>
          <tr><td>最大超额回撤</td><td><b>{max_dd:.1f}%</b></td><td>发生在 {max_dd_date}</td></tr>
          <tr><td>夏普比率</td><td><b>{sharpe:.2f}</b></td><td>收益/风险比</td></tr>
        </table>"""

        conclusions = []
        if excess_total > 0:
            conclusions.append(_conclusion_html("盈利",
                f"策略在 {years:.1f} 年内累计超额 {excess_total:.1f}%（年化 {ann_excess:.1f}%），跑赢沪深300基准。"
                "这意味着如果同期买入沪深300 ETF 赚 12%/年，你的策略能多赚约 8.5%/年。"
                "在量化选股中，年化超额 8-15% 是一个合理且可实盘化的水平。"))
        else:
            conclusions.append(_conclusion_html("亏损",
                f"策略在 {years:.1f} 年内累计超额 {excess_total:.1f}%，跑输基准。模型选出的股票还不如直接买指数。"))

        if max_dd > -5:
            conclusions.append(_conclusion_html("低风险",
                f"最大超额回撤仅 {max_dd:.1f}%，回撤控制优秀。实盘中即使遇到最差时期，你的策略相对基准的亏损也很小，心理压力低。"))
        elif max_dd > -15:
            conclusions.append(_conclusion_html("中风险",
                f"最大超额回撤 {max_dd:.1f}%，在可接受范围。实盘中这意味着某些时段你的策略会阶段性跑输指数约 {abs(max_dd):.0f}%，"
                "需要你有足够的耐心持有，不要在最差时期放弃策略。"))
        else:
            conclusions.append(_conclusion_html("高风险",
                f"最大超额回撤 {max_dd:.1f}% 超过 15%。实盘中这么大的回撤会让你严重怀疑策略是否有效，心理压力极大，建议优化。"))

        if sharpe >= 1.5:
            conclusions.append(_conclusion_html("优秀",
                f"夏普比率 {sharpe:.2f} ≥ 1.5，每承担 1 单位风险获得的超额收益非常高。这在量化策略中属于顶尖水平。"))
        elif sharpe >= 0.8:
            conclusions.append(_conclusion_html("良好",
                f"夏普比率 {sharpe:.2f}，处于 [0.8, 1.5) 区间。风险调整后收益合理——这是实盘可用的水平。"
                "作为参考，巴菲特长期夏普约 0.7-0.8，公募基金的优秀量化策略通常在 0.8-1.5。"))
        else:
            conclusions.append(_conclusion_html("较差",
                f"夏普比率 {sharpe:.2f} < 0.8，收益不足以补偿风险。策略虽然可能赚钱，但波动太大，实盘难以坚持。"))

        conclusions_html = "\n".join(conclusions)
        img_b64 = _img_to_base64(vis_dir / "return_analysis.png")
        sections.append(("2. 回测收益表现", img_b64, metrics, conclusions_html,
            "回测模拟了「每天用模型选出 top50 股票等权持有」的策略表现。"
            "上方曲线对比策略 vs 基准的累计收益；中间曲线看超额收益是否持续上升；"
            "下方回撤图看策略最差时期亏多少。"
            "关注三个核心指标：年化超额收益（赚多少）、最大回撤（最惨亏多少）、夏普比率（性价比）。"))

    # ── 3. 换手率与交易成本 ──
    if "report" in files:
        report_df = load_pkl(files["report"])
        turnover = report_df["turnover"]
        avg_to = turnover.mean()
        total_cost = report_df["cost"].sum() * 100
        years_tr = len(report_df) / 252
        ann_cost = total_cost / years_tr

        metrics = f"""
        <table class="metrics-table">
          <tr><td>日均换手率</td><td><b>{avg_to:.3f}</b></td><td>每日更换 {avg_to*100:.1f}% 的持仓</td></tr>
          <tr><td>累计交易成本</td><td>{total_cost:.2f}%</td><td>占初始本金</td></tr>
          <tr><td>年均交易成本</td><td>{ann_cost:.1f}%</td><td>每年对收益的侵蚀</td></tr>
        </table>"""

        conclusions = []
        if avg_to < 0.1:
            conclusions.append(_conclusion_html("低换手",
                f"日均换手 {avg_to:.3f}，换手较少。模型选出的股票组合比较稳定，不需要频繁买卖，交易成本低。"))
        elif avg_to < 0.3:
            conclusions.append(_conclusion_html("适中",
                f"日均换手 {avg_to:.3f}（双边口径，买入额+卖出额/账户总值），换手率适中。"
                f"持仓 50 只股票，每天约替换 {avg_to/2*50:.0f} 只（单边），"
                "属于正常的日频调仓水平。"))
        else:
            conclusions.append(_conclusion_html("高换手",
                f"日均换手 {avg_to:.3f}，换手频繁。每天大幅更换持仓会导致高额交易成本，侵蚀收益。"
                "可考虑降低调仓频率或增大 dropout 阈值来减少换手。"))

        if ann_cost > 5:
            conclusions.append(_conclusion_html("注意",
                f"年均交易成本 {ann_cost:.1f}%，对年化收益侵蚀较大。如果你的年化超额是 8%，交易成本就吃掉了大半。"))
        else:
            conclusions.append(_conclusion_html("正常",
                f"年均交易成本 {ann_cost:.1f}%，交易成本影响较小，对超额收益的侵蚀在合理范围内。"))

        conclusions_html = "\n".join(conclusions)
        img_b64 = _img_to_base64(vis_dir / "turnover_analysis.png")
        sections.append(("3. 换手率与交易成本", img_b64, metrics, conclusions_html,
            "换手率反映策略的交易频率。高换手 = 高交易成本 = 吃掉更多利润。"
            "A 股单边手续费约千分之三（佣金+印花税），每次换仓都要付出这个成本。"))

    # ── 4. 月度表现拆解 ──
    if "report" in files:
        report_df = load_pkl(files["report"])
        monthly_excess = report_df.groupby(
            [report_df.index.year, report_df.index.month]
        ).apply(lambda x: (x["return"] - x["bench"] - x["cost"]).sum())
        pos_months = (monthly_excess > 0).sum()
        total_months = len(monthly_excess)
        best = monthly_excess.max() * 100
        worst = monthly_excess.min() * 100
        best_idx = monthly_excess.idxmax()
        worst_idx = monthly_excess.idxmin()

        yearly = report_df.groupby(report_df.index.year).apply(
            lambda x: (x["return"] - x["bench"] - x["cost"]).sum()
        )
        yearly_rows = "".join(
            f'<tr><td>{y}</td><td>{"+" if r>0 else ""}{r*100:.1f}%</td></tr>'
            for y, r in yearly.items()
        )

        metrics = f"""
        <table class="metrics-table">
          <tr><td>正超额月份</td><td><b>{pos_months}/{total_months} ({pos_months/total_months*100:.0f}%)</b></td><td>策略多数月份跑赢基准？</td></tr>
          <tr><td>最佳月份</td><td>+{best:.1f}%</td><td>{best_idx[0]}-{best_idx[1]:02d}</td></tr>
          <tr><td>最差月份</td><td>{worst:.1f}%</td><td>{worst_idx[0]}-{worst_idx[1]:02d}</td></tr>
        </table>
        <h4>各年度超额收益</h4>
        <table class="metrics-table">{yearly_rows}</table>"""

        conclusions = []
        if pos_months / total_months >= 0.6:
            conclusions.append(_conclusion_html("稳定",
                f"正超额月份占比 {pos_months/total_months*100:.0f}%，策略在大多数月份能跑赢基准。"
                "这意味着你不需要忍受长期的策略失效期，心理压力较小。"))
        elif pos_months / total_months >= 0.5:
            conclusions.append(_conclusion_html("一般",
                f"正超额月份占比 {pos_months/total_months*100:.0f}%，胜率仅勉强过半。策略在某些市场环境下会阶段性失效。"))
        else:
            conclusions.append(_conclusion_html("差",
                f"正超额月份占比仅 {pos_months/total_months*100:.0f}%，策略经常跑输基准，需要重新审视。"))

        all_pos = all(r > 0 for r in yearly.values)
        if all_pos:
            conclusions.append(_conclusion_html("稳健",
                f"每个年度均实现正超额，最差年份 {yearly.idxmin()} 仍有 +{yearly.min()*100:.1f}%。"
                "策略在不同市场环境下（牛市/熊市/震荡）都能创造超额价值，这是非常理想的状况。"))
        else:
            neg_years = [f"{y}({r*100:.1f}%)" for y, r in yearly.items() if r <= 0]
            conclusions.append(_conclusion_html("波动",
                f"存在负超额年份：{', '.join(neg_years)}。策略在某些年份整体会跑输基准，"
                "需要分析这些年份的市场特征（如风格切换），判断是否可以通过滚动训练改善。"))

        conclusions_html = "\n".join(conclusions)
        img_b64 = _img_to_base64(vis_dir / "monthly_return.png")
        sections.append(("4. 月度表现拆解", img_b64, metrics, conclusions_html,
            "月度热力图共三层：上图 = 策略净收益（已扣手续费），中图 = 基准 CSI300 收益，下图 = 超额收益（策略净收益 − 基准）。"
            "三图口径自洽：上图 − 中图 = 下图，可直接对照看出绝对收益里有多少是大盘 beta、多少是真实 alpha。"
            "绿色 = 正收益（超额图中即跑赢基准），红色 = 负收益。"
            "关注两点：(1) 超额图绿色是否明显多于红色？(2) 红色集中在哪些年份/月份？"
            "如果红色集中在某个特定时期（如 2018 年熊市），说明策略对特定市场环境敏感。"))

    # ── 5. 特征重要性分析 ──
    if "model" in files:
        model = load_pkl(files["model"])
        booster = model.model
        importance = booster.feature_importance(importance_type='gain')
        total_imp = importance.sum()
        fi_data = []
        for i in range(len(importance)):
            name = _ALPHA158_NAMES[i] if i < len(_ALPHA158_NAMES) else f'Col_{i}'
            fi_data.append((name, importance[i], importance[i]/total_imp*100))
        fi_data.sort(key=lambda x: -x[1])

        top5_share = sum(x[2] for x in fi_data[:5])
        top10_share = sum(x[2] for x in fi_data[:10])
        top20_share = sum(x[2] for x in fi_data[:20])

        top10_rows = "".join(
            f'<tr><td>{rank}</td><td><b>{name}</b></td><td>{pct:.1f}%</td></tr>'
            for rank, (name, _, pct) in enumerate(fi_data[:10], 1)
        )

        metrics = f"""
        <table class="metrics-table">
          <tr><td>总特征数</td><td>{len(importance)}</td><td>Alpha158 因子集</td></tr>
          <tr><td>Top 5 占比</td><td><b>{top5_share:.1f}%</b></td><td>前 5 个因子的贡献</td></tr>
          <tr><td>Top 10 占比</td><td>{top10_share:.1f}%</td><td>前 10 个因子的贡献</td></tr>
          <tr><td>Top 20 占比</td><td>{top20_share:.1f}%</td><td>前 20 个因子的贡献</td></tr>
        </table>
        <h4>Top 10 因子</h4>
        <table class="metrics-table">
          <tr><th>排名</th><th>因子名</th><th>重要性</th></tr>
          {top10_rows}
        </table>"""

        conclusions = []
        if top5_share >= 40:
            conclusions.append(_conclusion_html("集中",
                f"Top 5 因子贡献了 {top5_share:.1f}% 的模型能力，模型过度依赖少数因子。"
                "这存在过拟合风险——如果这几个因子在未来失效，整个策略会崩溃。"
                "建议：尝试剔除低重要性因子（贡献 < 1% 的），减少噪声。"))
        elif top5_share >= 25:
            conclusions.append(_conclusion_html("均衡",
                f"Top 5 因子贡献 {top5_share:.1f}%，模型综合使用了多种信号来源。"
                "这种分散性是好的——即使某个因子失效，其他因子还能支撑模型表现。"))
        else:
            conclusions.append(_conclusion_html("分散",
                f"Top 5 因子仅贡献 {top5_share:.1f}%，模型能力高度分散在 158 个因子上。"
                "这意味着没有单一「明星因子」，模型靠集体智慧取胜，稳健性好。"))

        top1_name = fi_data[0][0]
        conclusions.append(_conclusion_html("提示",
            f"最重要的因子是 <b>{top1_name}</b>（占 {fi_data[0][2]:.1f}%）。"
            "你可以在【阶段5-迭代优化】中利用这个信息：(1) 确认这个因子的经济学含义是否合理；"
            "(2) 尝试剔除贡献 < 1% 的尾部因子，看 IC 是否提升（减少噪声）；"
            "(3) 如果多个模型都依赖相同因子，说明这些因子包含真实的 alpha 信息。"))

        conclusions_html = "\n".join(conclusions)
        img_b64 = _img_to_base64(vis_dir / "feature_importance.png")
        sections.append(("5. 特征重要性分析", img_b64, metrics, conclusions_html,
            "特征重要性展示模型「做决策时最依赖哪些因子」。"
            "gain 类型的重要性衡量每个因子对模型预测精度的贡献。"
            "这张图的核心价值是指导因子筛选——剔除不重要的因子可以减少噪声、加快训练、降低过拟合风险。"))

    # ── 6. 5分位分组收益 ──
    if "pred" in files and "label" in files:
        pred_df = load_pkl(files["pred"])
        label_df = load_pkl(files["label"])
        merged = pred_df.join(label_df, how='inner')
        merged.columns = ['score', 'label']
        daily_groups = {}
        for dt, day_df in merged.groupby(level='datetime'):
            if len(day_df) < 10:
                continue
            day_df = day_df.sort_values('score')
            groups = pd.qcut(day_df['score'], 5, labels=False, duplicates='drop')
            group_ret = day_df.groupby(groups)['label'].mean()
            daily_groups[dt] = group_ret

        if daily_groups:
            result = pd.DataFrame.from_dict(daily_groups, orient='index')
            result.index = pd.to_datetime(result.index)
            result = result.sort_index()
            avg_ret = result.mean()
            labels = ['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)']
            q_rows = "".join(
                f'<tr><td>{labels[i]}</td><td>{avg_ret.iloc[i]*100:+.4f}%</td>'
                f'<td>{avg_ret.iloc[i]*252*100:+.1f}%</td></tr>'
                for i in range(len(avg_ret))
            )
            spread = (avg_ret.iloc[-1] - avg_ret.iloc[0]) * 100
            spread_ann = spread * 252

            metrics = f"""
            <table class="metrics-table">
              <tr><th>分位</th><th>日均收益</th><th>年化收益</th></tr>
              {q_rows}
              <tr><td><b>Q5-Q1 价差</b></td><td><b>{spread:.3f}%/天</b></td><td><b>年化 {spread_ann:.1f}%</b></td></tr>
            </table>"""

            is_monotonic = all(avg_ret.iloc[i] <= avg_ret.iloc[i+1] for i in range(len(avg_ret)-1))
            conclusions = []
            if is_monotonic:
                conclusions.append(_conclusion_html("完美",
                    "收益从 Q1 到 Q5 严格单调递增——模型给出的预测分数越高，股票的实际收益越高。"
                    "这证明模型具有优秀的排序能力：买入 Q5（预测最好的 20% 股票）、卖空 Q1（预测最差的 20%），"
                    "理论上能获得巨大的多空价差收益。在实盘中你只做多 Q5，就已经能获得很好的超额。"))
            else:
                violations = []
                for i in range(len(avg_ret)-1):
                    if avg_ret.iloc[i] > avg_ret.iloc[i+1]:
                        violations.append(f"{labels[i]}({avg_ret.iloc[i]*100:.3f}%) > {labels[i+1]}({avg_ret.iloc[i+1]*100:.3f}%)")
                conclusions.append(_conclusion_html("不完美",
                    f"存在 {len(violations)} 处单调性违反：{'; '.join(violations)}。"
                    "模型的排序能力有瑕疵——某些中间分组收益没有按预期递增。"
                    "但 Q1 和 Q5 的分化仍然明显的话，实盘只做多 Q5 仍然可行。"))

            if spread_ann >= 30:
                conclusions.append(_conclusion_html("强",
                    f"年化价差 {spread_ann:.1f}% ≥ 30%，多空价差非常可观。即使扣除交易成本和冲击成本，"
                    "仍有足够的获利空间。这是策略可实盘化的核心保障。"))
            elif spread_ann >= 15:
                conclusions.append(_conclusion_html("可用",
                    f"年化价差 {spread_ann:.1f}%，可用于组合构建，但需要控制交易成本。"))
            else:
                conclusions.append(_conclusion_html("弱",
                    f"年化价差 {spread_ann:.1f}% < 15%，多空分化不够大，可能无法覆盖实盘的交易成本和滑点。"))

            conclusions_html = "\n".join(conclusions)
            img_b64 = _img_to_base64(vis_dir / "group_return.png")
            sections.append(("6. 5分位分组收益", img_b64, metrics, conclusions_html,
                "分组收益是评估模型选股能力最直观的方式。每天把所有股票按模型打分分成 5 组："
                "Q1 = 打分最低的 20%，Q5 = 打分最高的 20%。"
                "如果模型有效，Q5 应该赚得最多、Q1 应该亏得最多。"
                "左图看各组的平均日收益（柱状图应递增）；右图看各组的累计收益曲线（Q5 应在最上方）。"))

    # ── 7. 综合评估与下一步建议 ──
    overall_conclusions = []
    # 根据已有数据综合判断
    if "ic" in files and "ric" in files:
        ic_s = load_pkl(files["ic"])
        ic = ic_s.iloc[:, 0] if isinstance(ic_s, pd.DataFrame) else ic_s
        ic_mean = ic.mean()
        icir = ic_mean / ic.std()
        n = len(ic)
        ic_first = ic.iloc[:n//3].mean()
        ic_last = ic.iloc[-n//3:].mean()

        if ic_mean >= 0.02 and icir >= 0.3:
            overall_conclusions.append(_conclusion_html("通过",
                "静态训练结果达标：信号有效且基本稳定，可以进入下一阶段。"))
        else:
            overall_conclusions.append(_conclusion_html("未达标",
                "静态训练结果不够理想，建议先回到因子构建或模型调优阶段。"))

        if ic_last < ic_first * 0.5:
            overall_conclusions.append(_conclusion_html("下一步",
                "IC 衰减明显，<b>下一步应进入【阶段4-滚动训练】</b>。"
                "滚动训练的核心逻辑：市场规律会随时间变化（你看到的 IC 衰减就是证据），"
                "滚动训练通过定期用最新数据重新训练模型来对抗这种变化。"
                "类比深度学习：这就像你的模型在旧数据上精度高但在新数据上精度下降，"
                "解决方案是定期用新数据 fine-tune 或重训——滚动训练做的就是这件事。"))
        else:
            overall_conclusions.append(_conclusion_html("下一步",
                "IC 无明显衰减，但仍建议做滚动训练以获取更真实的实盘预期。"
                "或者先进入【阶段5-迭代优化】尝试提升模型性能。"))

    if "report" in files:
        report_df = load_pkl(files["report"])
        excess = (report_df["return"] - report_df["bench"] - report_df["cost"]).cumsum()
        daily_ret = report_df["return"] - report_df["bench"] - report_df["cost"]
        sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252)
        dd = excess - excess.cummax()
        ann_excess = excess.iloc[-1] / (len(report_df)/252) * 100

        if ann_excess >= 8 and abs(dd.min()*100) < 15 and sharpe >= 0.8:
            overall_conclusions.append(_conclusion_html("达标",
                f"核心指标全部达到实盘门槛：年化超额 {ann_excess:.1f}% ≥ 8%、"
                f"最大回撤 {dd.min()*100:.1f}% > -15%、夏普 {sharpe:.2f} ≥ 0.8。"
                "经过滚动训练确认后，该策略具备实盘部署条件。"))
        else:
            gaps = []
            if ann_excess < 8:
                gaps.append(f"年化超额 {ann_excess:.1f}% < 8%")
            if abs(dd.min()*100) >= 15:
                gaps.append(f"最大回撤 {dd.min()*100:.1f}% 超过 -15%")
            if sharpe < 0.8:
                gaps.append(f"夏普 {sharpe:.2f} < 0.8")
            overall_conclusions.append(_conclusion_html("待优化",
                f"以下指标未达到实盘门槛：{'; '.join(gaps)}。"
                "建议在【阶段5-迭代优化】中针对性优化后再做滚动训练确认。"))

    overall_html = "\n".join(overall_conclusions)
    sections.append(("7. 综合评估与下一步建议", "", "", overall_html,
        "综合以上所有分析，判断当前策略是否具备实盘条件，以及下一步应该做什么。"))

    # ── 组装 HTML ──
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>LightGBM 训练结果分析报告</title>",
        "<style>",
        "  body { font-family: -apple-system, 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; "
        "         max-width: 1100px; margin: 0 auto; padding: 20px 30px; "
        "         background: #fafafa; color: #333; line-height: 1.7; }",
        "  h1 { text-align: center; color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 12px; }",
        "  h2 { color: #1565c0; border-left: 5px solid #1565c0; padding-left: 12px; margin-top: 50px; }",
        "  h4 { color: #555; margin: 12px 0 6px; }",
        "  .section { background: white; border-radius: 8px; padding: 24px; margin: 20px 0; "
        "             box-shadow: 0 2px 8px rgba(0,0,0,0.08); }",
        "  .chart-container { text-align: center; margin: 16px 0; }",
        "  .chart-container img { max-width: 100%; border: 1px solid #e0e0e0; border-radius: 4px; }",
        "  .explain { background: #e8eaf6; border-radius: 6px; padding: 12px 16px; "
        "             font-size: 0.92em; color: #37474f; margin: 12px 0; }",
        "  .metrics-table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 0.95em; }",
        "  .metrics-table td, .metrics-table th { padding: 6px 12px; border-bottom: 1px solid #e0e0e0; text-align: left; }",
        "  .metrics-table th { background: #f5f5f5; font-weight: 600; }",
        "  .metrics-table td:first-child { color: #555; min-width: 140px; }",
        "  .metrics-table td:last-child { color: #888; font-size: 0.9em; }",
        "  .conclusions { margin-top: 16px; }",
        "  .conclusions h3 { color: #2e7d32; font-size: 1.05em; margin-bottom: 8px; }",
        "  .conclusion-item { display: flex; align-items: flex-start; gap: 10px; "
        "                     padding: 8px 0; border-bottom: 1px solid #f0f0f0; }",
        "  .tag { display: inline-block; padding: 2px 10px; border-radius: 4px; color: white; "
        "         font-size: 0.85em; font-weight: 600; white-space: nowrap; min-width: 50px; text-align: center; }",
        "  .summary-box { background: #e8f5e9; border-left: 4px solid #2e7d32; padding: 16px; "
        "                  border-radius: 4px; margin: 16px 0; font-size: 0.95em; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>LightGBM + Alpha158 训练结果分析报告</h1>",
        '<p style="text-align:center;color:#666;">本报告将图表与详细解读整合在一起，帮助你理解每个指标的含义和下一步决策。</p>',
    ]

    for title, img_b64, metrics_html, conclusions_html, explain_text in sections:
        html_parts.append(f'<div class="section">')
        html_parts.append(f"<h2>{title}</h2>")
        if explain_text:
            html_parts.append(f'<div class="explain">{explain_text}</div>')
        if img_b64:
            html_parts.append(f'<div class="chart-container"><img src="{img_b64}" alt="{title}"></div>')
        if metrics_html:
            html_parts.append(f'<h4>核心指标</h4>{metrics_html}')
        if conclusions_html:
            html_parts.append(f'<div class="conclusions"><h3>结论与解读</h3>{conclusions_html}</div>')
        html_parts.append("</div>")

    html_parts.extend(["</body>", "</html>"])

    html_text = "\n".join(html_parts)
    html_path = vis_dir / "analysis_report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"\nHTML report saved: {html_path.relative_to(OUTPUT_DIR)}")
    return html_path


# ─────────────────────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────────────────────
def main(mlruns_name: str = "mlruns_static", skip_charts: bool = False):
    is_rolling = "rolling" in mlruns_name
    mlruns_dir = OUTPUT_DIR / mlruns_name

    print(f"Loading {'rolling' if is_rolling else 'static'} training results...")
    files, vis_dir = find_latest_run(mlruns_name)
    print(f"Found files: {list(files.keys())}")
    if skip_charts:
        print("(skip-charts mode: will skip PNG regeneration, only generate HTML report)")
    print()

    # ── 滚动训练专属：解析子模型窗口 + 绘制窗口图 ──
    windows = []
    if is_rolling and mlruns_dir.exists():
        print("Parsing rolling sub-model windows...")
        windows = parse_rolling_windows(mlruns_dir)
        if windows:
            print(f"  Found {len(windows)} sub-models")
            print(f"  Test range: {windows[0]['test_start'].strftime('%Y-%m')} ~ {windows[-1]['test_end'].strftime('%Y-%m')}")
            # 滚动窗口图只在不存在时生成
            if not (vis_dir / "rolling_windows.png").exists():
                plot_rolling_windows(windows, vis_dir)
            else:
                print("  rolling_windows.png already exists, skipping.")
        else:
            print("  Warning: no sub-model windows found")

    # ── 图表生成（可通过 --skip-charts 跳过） ──
    if not skip_charts:
        # 指标汇总（打印到终端）
        if "port_analysis" in files:
            print_summary(files["port_analysis"])

        # IC 分析
        if "ic" in files and "ric" in files:
            print("\nPlotting IC analysis...")
            ic_df = load_pkl(files["ic"])
            ric_df = load_pkl(files["ric"])
            plot_ic_analysis(ic_df, ric_df, vis_dir)

        # 收益与回撤分析
        if "report" in files:
            print("Plotting return analysis...")
            report_df = load_pkl(files["report"])
            plot_return_analysis(report_df, vis_dir)

            # 换手率分析
            print("Plotting turnover analysis...")
            plot_turnover(report_df, vis_dir)

            # 月度热力图
            print("Plotting monthly return heatmap...")
            plot_monthly_return(report_df, vis_dir)

        # 特征重要性
        if "model" in files:
            print("Plotting feature importance...")
            plot_feature_importance(files["model"], vis_dir)

        # 分组收益
        if "pred" in files and "label" in files:
            print("Plotting quintile group return...")
            pred_df = load_pkl(files["pred"])
            label_df = load_pkl(files["label"])
            plot_group_return(pred_df, label_df, vis_dir)

        rel = vis_dir.relative_to(OUTPUT_DIR)
        print(f"\nAll charts saved to {rel}/:")
        print(f"  - ic_analysis.png")
        print(f"  - return_analysis.png")
        print(f"  - turnover_analysis.png")
        print(f"  - monthly_return.png")
        print(f"  - feature_importance.png")
        print(f"  - group_return.png")
        if is_rolling and windows:
            print(f"  - rolling_windows.png")

        # 生成量化分析报告
        print("\nGenerating quantitative report...")
        generate_report(files, vis_dir)

    # ── HTML 报告生成（始终执行） ──
    if is_rolling and windows:
        print("\nGenerating rolling HTML report...")
        generate_rolling_html_report(files, vis_dir, windows)
    elif not skip_charts:
        print("\nGenerating HTML report...")
        generate_html_report(files, vis_dir)
    else:
        # skip-charts + static: 仍然生成 HTML（复用已有图表）
        print("\nGenerating HTML report (reusing existing charts)...")
        generate_html_report(files, vis_dir)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mlruns-dir", default="mlruns_static",
                        help="mlruns 目录名，默认 mlruns_static")
    parser.add_argument("--skip-charts", action="store_true",
                        help="跳过 PNG 图表生成，仅生成 HTML 报告（复用已有图表）")
    args = parser.parse_args()
    main(mlruns_name=args.mlruns_dir, skip_charts=args.skip_charts)
