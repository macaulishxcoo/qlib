#!/usr/bin/env python
"""Alpha101 公式解析 / 求值器（无 ``eval``，自建 tokenizer + 递归下降）。

为什么自己写
------------
qdata 的 ``factor_desc`` 里是 ``Rank(...) ? ... : ...`` 风格的三元表达式，
且含 ``^`` 幂、``||``/``&&`` 逻辑、``<``/``<=`` 比较（返回**序列**而非标量）。
直接用 Python ``eval`` 需要大量脆弱的字符串替换；递归下降只需 ~150 行，
且能对每个节点做**记忆化**（同一子表达式在多因子间复用，显著省时）。

语法（优先级低 → 高）
---------------------
``?:``  →  ``||``  →  ``&&``  →  比较  →  ``+ -``  →  ``* /``  →  一元 ``- + !``
→  ``^``（右结合）  →  原子（数字 / 变量 / 函数调用 / 括号）

求值
----
``Env`` 提供变量（DataFrame）与函数；:func:`evaluate` 按 AST 记忆化，
避免 ``Correlation(Rank(Volume), Rank(VWAP), 5)`` 这类子式被重复计算。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from xs_ops import (CFG, EPS, abs_, correlation, covariance, decay_linear, delay,
                    delta, elem_max, elem_min, if_else, ind_neutralize, log, product,
                    rank, scale, sign, signed_power, stddev, ts_argmax, ts_max,
                    ts_mean, ts_min, ts_rank, ts_sum)

# ======================================================== 词法 ==================
_TOKEN_RE = re.compile(r"""
    (?P<num>\d+\.\d*|\.\d+|\d+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\|\||&&|<=|>=|==|!=|[-+*/^()?,:<>=!])
""", re.VERBOSE)


def tokenize(s: str) -> list[tuple[str, str]]:
    toks, i, n = [], 0, len(s)
    while i < n:
        if s[i].isspace():
            i += 1
            continue
        m = _TOKEN_RE.match(s, i)
        if not m:
            raise SyntaxError(f"无法词法分析: {s[i:i+30]!r}")
        kind = m.lastgroup
        toks.append((kind, m.group()))
        i = m.end()
    return toks


# ======================================================== 语法 ==================
class Parser:
    def __init__(self, toks: list[tuple[str, str]]):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self, val=None):
        k, v = self.peek()
        if val is not None and v != val:
            raise SyntaxError(f"期望 {val!r}，实得 {v!r}")
        self.i += 1
        return v

    # expr := ternary
    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.or_expr()
        if self.peek()[1] == "?":
            self.eat("?")
            a = self.expr()
            self.eat(":")
            b = self.ternary()
            return ("cond", c, a, b)
        return c

    def or_expr(self):
        n = self.and_expr()
        while self.peek()[1] == "||":
            self.eat()
            n = ("bool", "||", n, self.and_expr())
        return n

    def and_expr(self):
        n = self.cmp_expr()
        while self.peek()[1] == "&&":
            self.eat()
            n = ("bool", "&&", n, self.cmp_expr())
        return n

    def cmp_expr(self):
        n = self.add_expr()
        while self.peek()[1] in ("<", ">", "<=", ">=", "==", "!="):
            op = self.eat()
            n = ("cmp", op, n, self.add_expr())
        return n

    def add_expr(self):
        n = self.mul_expr()
        while self.peek()[1] in ("+", "-"):
            op = self.eat()
            n = ("bin", op, n, self.mul_expr())
        return n

    def mul_expr(self):
        n = self.unary()
        while self.peek()[1] in ("*", "/"):
            op = self.eat()
            n = ("bin", op, n, self.unary())
        return n

    def unary(self):
        v = self.peek()[1]
        if v in ("-", "+", "!"):
            self.eat()
            return ("un", v, self.unary())
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek()[1] == "^":
            self.eat("^")
            return ("bin", "^", base, self.unary())
        return base

    def atom(self):
        k, v = self.peek()
        if k == "num":
            self.eat()
            return ("num", float(v))
        if k == "ident":
            self.eat()
            if self.peek()[1] == "(":
                self.eat("(")
                args = []
                if self.peek()[1] != ")":
                    args.append(self.expr())
                    while self.peek()[1] == ",":
                        self.eat(",")
                        args.append(self.expr())
                self.eat(")")
                return ("call", v, tuple(args))
            return ("var", v)
        if v == "(":
            self.eat("(")
            e = self.expr()
            self.eat(")")
            return e
        raise SyntaxError(f"意外的 token: {v!r}")


def parse(expr: str):
    p = Parser(tokenize(expr))
    ast = p.expr()
    if p.i != len(p.t):
        raise SyntaxError(f"解析未消费完全部 token: {p.t[p.i:]}")
    return ast


# ======================================================== 公式预处理 ============
_ALPHA_PREFIX = re.compile(r"^\s*Alpha\s*=", re.I)


def clean_formula(text: str) -> str:
    """从 ``factor_desc`` 的 ``formula`` 文本提取纯表达式。

    - 去掉 ``Alpha = `` 前缀
    - 截断 ``说明:`` 之后的自然语言
    - 合并多行续行
    """
    s = text.split("说明:")[0]
    s = "\n".join(ln for ln in s.splitlines() if ln.strip())
    s = _ALPHA_PREFIX.sub("", s.strip())
    return " ".join(s.split())


# ======================================================== 求值 ==================
@dataclass
class Env:
    """求值上下文：变量表 + 函数表 + 记忆化缓存。"""

    vars: dict[str, pd.DataFrame] = field(default_factory=dict)
    ind_mat: np.ndarray | None = None
    cache: dict = field(default_factory=dict)
    missing: set = field(default_factory=set)

    def func(self, name: str):
        f = FUNCS.get(name)
        if f is None:
            raise KeyError(name)
        return f


def _cmp(op, a, b):
    if isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame):
        ref = a if isinstance(a, pd.DataFrame) else b
        if op == "<":
            r = a < b
        elif op == ">":
            r = a > b
        elif op == "<=":
            r = a <= b
        elif op == ">=":
            r = a >= b
        elif op == "==":
            r = a == b
        else:
            r = a != b
        if isinstance(r, bool):
            r = pd.DataFrame(r, index=ref.index, columns=ref.columns)
        elif not isinstance(r, pd.DataFrame):
            r = pd.DataFrame(r, index=ref.index, columns=ref.columns)
        return r
    return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b,
            "==": a == b, "!=": a != b}[op]


def _bin(op, a, b):
    df_like = isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if isinstance(b, pd.DataFrame):
            b2 = b.where(b.abs() > EPS)
        else:
            b2 = b if abs(b) > EPS else np.nan
        return a / b2
    if op == "^":
        try:
            return a ** b
        except Exception:                       # noqa: BLE001
            return signed_power(a, b) if df_like else a ** b
    raise KeyError(op)


def evaluate(node, env: Env, depth: int = 0):
    key = node if isinstance(node, (int, float, str)) else _key(node)
    if key in env.cache:
        return env.cache[key]
    t = node[0]
    if t == "num":
        out = node[1]
    elif t == "var":
        name = node[1]
        if name not in env.vars:
            env.missing.add(name)
            raise KeyError(f"未定义变量 {name}")
        out = env.vars[name]
    elif t == "call":
        name, args = node[1], node[2]
        vals = [evaluate(a, env, depth + 1) for a in args]
        out = env.func(name)(*vals)
    elif t == "un":
        v = evaluate(node[2], env, depth + 1)
        out = -v if node[1] == "-" else (v if node[1] == "+" else ~v)
    elif t == "bin":
        out = _bin(node[1], evaluate(node[2], env, depth + 1),
                   evaluate(node[3], env, depth + 1))
    elif t == "cmp":
        out = _cmp(node[1], evaluate(node[2], env, depth + 1),
                   evaluate(node[3], env, depth + 1))
    elif t == "bool":
        a = evaluate(node[2], env, depth + 1)
        b = evaluate(node[3], env, depth + 1)
        out = (a & b) if node[1] == "&&" else (a | b)
    elif t == "cond":
        out = if_else(evaluate(node[1], env, depth + 1),
                      evaluate(node[2], env, depth + 1),
                      evaluate(node[3], env, depth + 1))
    else:
        raise SyntaxError(f"未知节点 {t}")
    env.cache[key] = out
    return out


def _key(node):
    return repr(node)


# ======================================================== 函数表 ================
def _ind(env: Env):
    def f(x):
        if env.ind_mat is None:
            raise RuntimeError("IndNeutralize 需要行业分类（env.ind_mat 为空）")
        if env.ind_mat.shape[0] != x.shape[1]:
            raise RuntimeError("行业指示矩阵与列数不匹配")
        return ind_neutralize(x, env.ind_mat)
    return f


def make_funcs(env: Env) -> dict:
    f = {
        "Rank": rank,
        "Scale": lambda x, a=1.0: scale(x, a),
        "IndNeutralize": _ind(env),
        "Abs": abs_,
        "Sign": sign,
        "Log": log,
        "SignedPower": signed_power,
        "Power": lambda x, a: x ** a,
        "Delta": delta,
        "Delay": delay,
        "Sum": ts_sum,
        "Product": product,
        "Mean": ts_mean,
        "StdDev": stddev,
        "Ts_Min": ts_min,
        "Ts_Max": ts_max,
        "Ts_Rank": ts_rank,
        "Ts_ArgMax": ts_argmax,
        "Decay_Linear": decay_linear,
        "Correlation": correlation,
        "Covariance": covariance,
        "Min": elem_min,
        "Max": elem_max,
        "IF": if_else,
        "If": if_else,
    }
    return f


FUNCS: dict = {}


def build_env(vars_: dict[str, pd.DataFrame], ind_mat=None) -> Env:
    env = Env(vars=dict(vars_), ind_mat=ind_mat)
    FUNCS.clear()
    FUNCS.update(make_funcs(env))
    return env


def eval_formula(text: str, env: Env) -> pd.DataFrame:
    ast = parse(clean_formula(text))
    return evaluate(ast, env)


def expr_of(text: str) -> str:
    return clean_formula(text)
