# 新机器迁移状态与恢复计划

> 生成时间：2026-09-13（最后更新：环境与数据已重建完成，见 §8）
> 这条记录取代 `research/docs/RESEARCH_PLAN.md` / `RESUME.md` / `ENVIRONMENT.md` 里的环境部分。
> 那三份文档写在"看不到仓库既有资产"的阶段，其中的自建系统已归档到
> `research/archive/parallel_track_2026-09/`（附说明），**不在主线上**。

---

## 8. 已完成：环境与数据重建（2026-09-13）

用户安装 WSL2（Ubuntu 26.04）并提供 TUSHARE_TOKEN 后，以下工作已全部完成并验证：

| 项 | 结果 |
|---|---|
| Python 环境 | `~/qlib-env`（uv 管理的 CPython **3.12.14**，无需 sudo、无需编译器） |
| 关键包 | pandas **2.3.3**、numpy 2.5.3、scipy、statsmodels、pyarrow、scikit-learn、lightgbm 4.7.0、tushare 1.4.29、**pyqlib 0.9.7** |
| lightgbm 修复 | 缺 `libgomp.so.1` → 从 `.deb` 解包到 `~/.local/lib`，已写入 venv activate |
| token | `~/.config/tushare/token`（chmod 600） |
| qlib 导入 | `python scripts/x.py` 时 `sys.path[0]=scripts/`，因此导入**已安装的 pyqlib**，而非缺编译扩展的本地 `qlib/` 源码 —— 已验证 |
| 日线行情 | `data/external/tushare/market_daily_v1/raw/`：**2,822 个交易日（2015-01-05 ~ 2026-08-13），0 失败** |
| qlib bin | `~/.qlib/qlib_data/cn_data_2026`：**2,843 天（2015-01-05 ~ 2026-09-11）**、58,020 个 feature 文件、483.8 MB、5,802 只 instrument |
| 基准 | `SH000852` 可用（2,843 行，close 4149 ~ 15006） |
| 路径移植 | 31 处硬编码路径改为 `$HOME` / 仓库相对路径（30 个文件）；**156 个 .py 全部编译通过** |
| 版本控制 | 仓库原本**没有 `.git`**（旧机器的 .git 未一并拷贝）。已建立安全快照：894 个受版本控制文件（151 份 research 文档 + 160 个 scripts 文件），大数据通过 `.git/info/exclude` 本地排除 |

验证脚本：`scripts/migration/verify_qlib_store_v1.py`（全部 PASS）。

**已知口径差异（重要）**：新 bin 的复权常数取 `K = 1.0`（旧库按自身 bin 校准每股常数）。
**收益率与旧库一致，绝对价位不一致**。仅影响 qlib 回测里 `min_cost=5` 的绝对量级，
在 1 亿账户假设下无影响。

**数据范围差异**：旧库 2000-2026，新库 **2015**-2026。已关闭的 CSI1000/Alpha158 线
（训练段 2008-2020）若重跑，需要把 `--start` 往前推并重新拉取。

---

## 1. 一句话状态

**代码、文档、4.19 GB 外部数据都完好；缺的只有"可运行的 Python 环境"和"日线行情数据"。**
（→ 这两项已于 2026-09-13 重建完成，见上方 §8。）
两者都有明确的恢复路径，且用户已选定方案（WSL2 + 提供 TUSHARE_TOKEN）。

---

## 2. 已核实：完好无损的资产

用 `scripts/migration/audit_surviving_data_v1.py` 实测（只读）：

| 资产 | 状态 |
|---|---|
| `PROJECT_SYNC.md` + `research/{charters,protocols,decisions,specifications}` | 150+ 文档齐全 |
| `scripts/` 自定义研究/回测/管道脚本 | 85 个 `.py` 齐全 |
| `data/external/tushare/` | **4.19 GB** |
| — `daily_basic`（close/市值/换手/估值） | 10,948,728 行；5,796 只；**2016-01-04 ~ 2026-08-13**；close 与 total_mv **缺失率 0%** |
| — `financial fina_indicator` | 54 个 batch + 合并版 94.99 MB（116 列） |
| — `financial cashflow / income` | 54 个 batch（105 / 93 列） |
| — `financial balancesheet` | 54 个 batch（160 列） |
| — `ST status intervals` | 14,170 行 |
| — `style`（free float size / 行业 L1 区间 / 月度调仓网格） | 齐全 |
| — `margin_detail` / `moneyflow` / `sw_industry_index` | 齐全 |
| `data/derived/`（股票分类 v1/v2、事件面板） | 104 MB |

**已完成的一项修复**：三个被拆成 `.partNN` 的大文件已用仓库自带脚本重组完成——
`daily_basic.csv.gz`（636 MB）、`moneyflow.csv.gz`（330 MB）、`margin_detail.csv.gz`（199 MB）。
命令：`python scripts/data_collector/reassemble_large_data_v1.py`

---

## 3. 已核实：真正缺失的部分

| 缺失项 | 影响 | 恢复路径 |
|---|---|---|
| `~/.qlib/qlib_data/cn_data_2026`（qlib bin） | `D.features("$open"/"$close")` 全部失效；回测无法运行 | 用 tushare 重建 |
| `data/external/tushare/market_daily_v1`（日线 OHLCV 原始层） | 同上；open 是 T+1 开盘成交与 open-to-open 标签的必需输入 | 用 tushare 重建 |
| Python 环境（原为 Linux conda env `qlib`，pandas 2.3.3） | 无法执行任何脚本 | WSL2 + conda |
| `output/`（历史回测产物） | 无法直接比对历史数字，需重跑 | 重跑生成 |

---

## 4. 根因：为什么 Windows 原生走不通

本机 **Smart App Control 处于开启状态**（`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy`
的 `VerifiedAndReputablePolicyState = 1`，强制级别 2）。它按"信誉"拦截可执行文件：

- 新建 conda 环境的 `python.exe`、`select.pyd` 等 → **被拦**（"Application Control policy has blocked this file"）；
- pip 安装的 `pyarrow` 扩展 → **被拦**；
- 只有预先存在的 `D:\software\miniconda`（Python 3.13）可用。

而 `pyqlib` 在 PyPI 上只提供 **cp38–cp312 的 Windows wheel**（无 cp313），
所以现有 3.13 解释器装不了 qlib；本地 `qlib/` 源码又没有编译好的扩展
（`qlib/data/_libs/*.pyd` 不存在），从仓库根目录 `import qlib` 会失败。

> 结论：Windows 原生需要关闭 Smart App Control（单向开关）或大量绕行，都不如直接上 WSL2。

---

## 5. 用户需要做的两件事

### 5.1 安装 WSL2（需要管理员 + 重启）

在**管理员** PowerShell 里执行：

```powershell
wsl --install -d Ubuntu
```

然后**重启电脑**。重启后 Ubuntu 会自动启动并要求设置用户名和密码。

> 本机已确认：Windows 11 25H2（build 26200）、虚拟化已启用（HypervisorPresent=True），
> 满足 WSL2 条件。

### 5.2 提供 TUSHARE_TOKEN（不要贴在聊天里）

推荐写入一个文件，我负责搬进 WSL 并落到脚本期望的位置：

```powershell
# 在 Windows PowerShell 里执行（把 <你的token> 换成真实值）
Set-Content -Path "$env:USERPROFILE\.tushare_token" -Value "<你的token>" -NoNewline -Encoding ascii
```

脚本期望的位置（Linux 侧）：`/root/.config/tushare/token`，或环境变量 `TUSHARE_TOKEN`。
我会在 WSL 就绪后自动从上面的文件读取并配置好。

---

## 6. WSL 就绪后我会做的（无需你介入）

1. 在 WSL 里建 conda/venv 环境（Python 3.11/3.12 + pandas 2.3.3 + lightgbm + statsmodels；
   qlib 用 Linux manylinux wheel 或源码安装）。
2. 把仓库就地使用（`/mnt/d/workspaces/qlib`），只修 7 处硬编码 Linux 路径
   （`/root/...`、`/home/xiaocong/...`、`/tmp/...`）。
3. 配置 token，运行 `scripts/data_collector/update_daily_market_data_v1.py` 重建
   `market_daily_v1` 与 `~/.qlib/qlib_data/cn_data_2026`。
4. 跑通 `backtest_a_share_daily_strategy_v1.py`（main：net +0.164 / IR 1.68）
   与五因子 top30_cap3，先**复现**历史数字，再推进目标。

---

## 7. 关于目标方向的提醒（重要）

`research/decisions/a_share_daily_alpha_exhaustion_manifest_v1.md` 的结论是：
**独立于动量/反转的日频截面 alpha 已测尽**（13 条线全闭环，无存活者）。
但同一份清单 §4 记录了一个**已达标的日频策略形态**：

> `main` = 基本面域 + 日频调仓 —— net 超额 **+0.164**、IR **1.68**、四年全正、换手仅 4.8%、
> stress 费率下 IR 1.58。

其样本止于 2025-06（受财务 PIT 上限）。而 `PROJECT_SYNC.md` §5 记录的最终实盘形态是
**五因子 + top-30 + 行业 cap3**（全期 IR 0.94、holdout IR 1.09），并已知
**2026 年价值风格逆风**（v6 的 new_coverage 段 -25.6%/yr、2026 年 -50.5%/yr）。

所以"找有效日频策略"这件事，本项目的真实状态不是"从零开始"，而是：
1. 先复现并确认历史达标形态；
2. 把样本推进到 2026（数据已到 2026-08）；
3. 处理已知的 2026 风格逆风（这是目前最大的未解问题）。

我按这个顺序推进，除非你另有指示。
