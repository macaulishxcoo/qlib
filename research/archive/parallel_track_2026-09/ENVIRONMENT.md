# 环境搭建 与 DSH shell 故障排查

## 0. 当前状态（重要）

本机（Windows，用户 `congx`）上，DeepSeek Harness 的 **`pwsh` 工具 100% 失败**，
`glob` / `grep` 也失败（它们同样依赖子进程）。因此**目前无法执行任何 Python 代码**。

### 已确认的事实

| 探测 | 结果 |
| --- | --- |
| `pwsh` 工具：`python --version` | `subprocess-local: Windows Job runner exited with exit code 3221225794 before proving its managed range empty` |
| `pwsh` 工具：`cmd /c ver` | 同样的错误 |
| `pwsh` 工具（后台 job） | `subprocess failed before reporting an outcome: Error: write EPIPE` |
| `glob` 工具 | `glob subprocess failed before reporting an outcome (ripgrep provider failure)` |
| `grep` 工具 | 同上 |
| `read` / `write` / `edit` / `web_fetch` / `web_search` | **正常** |

`3221225794` = `0xC0000142` = `STATUS_DLL_INIT_FAILED`。
它是**进程在加载 DLL 阶段就死掉**的状态码，不是命令失败、不是权限拒绝、不是脚本报错。

### 根因分析

DSH 在 Windows 上启动任何子进程时，会先拉起一个私有的 **"Windows Job runner"**
（就是 `process.execPath` 自己 + `@deepseek-ai/dsh-subprocess-local/runner`
这个入口，见 `packages/subprocess/subprocess-local/src/windows-job.ts`）。

该 runner 进程**已经被成功创建**（Node 的 `spawn` 事件已触发），
但它在 DLL 初始化阶段就崩了，于是父进程收到：

```
subprocess-local: Windows Job runner exited with exit code 3221225794
                  before proving its managed range empty
```

关键点：DSH 的设计是**原生路径失败时不会静默回退**到弱化的进程组方案
（`docs/subsystems/subprocess.md`：「A selected native failure is reported instead of
replaying argv through fallback」）。所以**只要 runner 起不来，所有工具都废掉**。

上游已知的 Windows 同类问题（都是 `0xC0000142`）：

- [#810 — Windows: sandboxed pwsh always dies with 0xC0000142 under console-less host (desktop launch path)](https://github.com/deepseek-ai/deepseek-harness/discussions/810)
- [#1102 — Windows 无控制台宿主（pm2 后台托管）下执行 shell 工具命令会弹出 PowerShell 窗口](https://github.com/deepseek-ai/deepseek-harness/discussions/1102)
- [#1344 — Sandboxed subprocess spawn flashes a visible console window from GUI hosts; STARTF_USESHOWWINDOW + SW_HIDE fixes it without the 0xC0000142 crash](https://github.com/deepseek-ai/deepseek-harness/discussions/1344)

**最可能的诱因：DSH 宿主进程没有控制台（console-less host）** —
例如从桌面快捷方式 / Electron 桌面外壳 / GUI 启动器 / 计划任务 / pm2 之类的方式拉起。
此时新创建的控制台子进程会以 `0xC0000142` 死掉。

---

## 1. 修复步骤（按顺序做，第一步大概率就好了）

### 步骤 1：从真正的控制台窗口重启 DSH

1. 完全退出当前 DSH（关掉桌面外壳 / 结束 `node.exe` 与 `dsh` 相关进程）。
2. 打开 **Windows Terminal** 或 **PowerShell 7** 或 **cmd**（必须是能看到黑底命令行的那种窗口）。
3. 在**同一个窗口里**启动 DSH，例如：

```powershell
cd D:\workspaces\deepseek-harness
pnpm dsh web
```

   或者（如果你用的是 npm 安装版）：

```powershell
npx @deepseek-ai/dsh web
```

   > 关键：**不要**双击图标、不要用桌面 App、不要用后台托管/计划任务启动。
   > 宿主必须有一个真实的控制台。

4. 新会话里让我再跑一次 `pwsh` 验证。

### 步骤 2：跑一次诊断脚本，把猜测变成结论

在**独立打开的** PowerShell / Windows Terminal 窗口里执行：

```powershell
cd D:\workspaces\qlib
pwsh -NoProfile -ExecutionPolicy Bypass -File .\research\scripts\diagnose_windows_shell.ps1
```

它会跑一组子进程探针，直接区分三种可能：

| 探针 | 含义 |
| --- | --- |
| A `cmd /c ver`（继承完整环境、正常分配控制台） | 本机到底能不能创建控制台子进程 |
| B 同样的命令，但**清空环境块** | 验证 `SystemRoot` 缺失假设（缺它时 loader 找不到 `conhost.exe`，正是 `0xC0000142`） |
| C 仅 `SystemRoot`+`PATH`+`TEMP` 的最小环境 | 判断是不是某个环境变量缺失 |
| D 空环境 + `CREATE_NO_WINDOW`（**不分配控制台**） | 判断"强制走降级 spawn 路径"这个规避方案是否可行 |
| E/F `node --version`（完整环境 / 空环境） | 单独验证 Node 子进程 |

脚本最后会打印结论。

- **A、E 都 OK** → 说明这台机器没问题，是 DSH 进程拿到的环境/启动方式有问题。
  回到步骤 1，从**同样这个终端窗口**重启 DSH。
- **A 或 E 也失败** → 是整机问题，走下面的"整机修复"。

### 步骤 3：整机修复（仅当 A/E 也失败）

```powershell
# 需要管理员权限的控制台
sfc /scannow
DISM /Online /Cleanup-Image /RestoreHealth
```

然后重启电脑。常见诱因：中断的 Windows 更新、被杀软/EDR 注入的坏 DLL、
`conhost.exe` 损坏（缺失或损坏都会让每个新控制台进程以 0xC0000142 死掉）、
桌面堆（desktop heap）耗尽。

另外临时关闭第三方杀软做一次对照实验，并把 `node.exe` 与
`D:\workspaces\deepseek-harness` 加入白名单。

### 步骤 4：备用方案（我可以从会话内部动手）

如果诊断显示 A 正常、但 DSH 仍然起不了子进程，且**探针 D 成功**，
说明"强制 DSH 走降级 spawn 路径"是可行的。这条路需要改动 DSH 的安装文件，
我会在动手前先跟你确认。

---

## 2. Python 环境搭建（shell 恢复后执行）

### 2.1 一键脚本

```powershell
cd D:\workspaces\qlib
pwsh -NoProfile -ExecutionPolicy Bypass -File .\research\scripts\bootstrap_env.ps1
```

### 2.2 脚本做了什么

1. 定位 Python（优先 `py -3.11`，其次 `python`），要求 ≥ 3.10。
2. 在 `D:\workspaces\qlib\research\.venv` 建虚拟环境。
3. 升级 pip，安装：`pandas numpy pyarrow scipy statsmodels lightgbm matplotlib
   plotly tqdm akshare baostock tushare pyyaml`。
4. 打印版本清单。

### 2.3 验证

```powershell
D:\workspaces\qlib\research\.venv\Scripts\python.exe .\research\scripts\verify_env.py
```

验证脚本会：

- 检查解释器版本与必需包；
- 调 **baostock** 登录并拉一小段日线，确认数据源可用；
- 尝试 **akshare** 拉一个日线接口做对照；
- 检查磁盘空间与工作目录可写性；
- 输出一份简洁的 PASS/FAIL 报告。

---

## 3. 数据源说明

| 源 | 用途 | 是否需要 token | 备注 |
| --- | --- | --- | --- |
| **baostock** | 主数据（日线 + 复权因子 + isST + 停牌 + 行业） | 否 | 免费稳定，`query_history_k_data_plus` 支持 `adjustflag` |
| **akshare** | 另类数据 + 退市股清单 + 交叉校验 | 否 | 接口多但偶有变动，需容错 |
| **tushare** | 交叉校验、财务、每日指标 | 是（免费额度足够起步） | 若你有 token，写进 `research/.env`（不入库） |
| qlib 社区数据 | 第三方对照（量化差异与幸存者偏差） | 否 | `~/.qlib/qlib_data/cn_data` |

**红线**：任何数据集都必须包含**已退市股票**，否则回测天然高估收益。
