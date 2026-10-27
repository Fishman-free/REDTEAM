#!/usr/bin/env python3
"""RTM 攻守博弈 P0 参数仿真（纯标准库、确定性、无随机数）。

规格：docs/superpowers/specs/2026-10-27-rtm-redteam-game-design.md §1.1/§3.5/§10
计划：docs/superpowers/plans/2026-10-27-rtm-redteam-game-plan-a.md 任务 2

模型要点
--------
- 奖池只含守方质押 S；攻方质押 s=r*S，每 epoch 保留剩余质押的 keep。
  全程持有近似下，每名攻方全程罚没 F=s*(1-keep^K)，最后取回 s*keep^K。
- N 名攻方，每轮各发一条消息，共 M 轮。单条消息攻破概率
  p_m = p * decay^(m-1)，p 为市场预期 p_market 或真实强度 p_def。
- 第 m 轮开始前的生存率 surv_m = Π_{j<m}(1-p_j)^N。
  单攻方总胜率 p_self = Σ_m surv_m * (1-(1-p_m)^N) / N。
  注意：必须先使用更新前的 surv_m 累加，再把本轮失败概率并入生存率。
  若同一轮有多人同时攻破，胜者在同时攻破者中均匀产生；由对称性，
  单攻方在该轮获胜概率正是 (1-(1-p_m)^N)/N。
- 攻方 EV = p_self*S - F - M*(fee_rate*S + llm_cost)
  守方 EV = N*F + S*P_survive - S
  自攻自守 EV = -M*(fee_rate*S + llm_cost)
- 零和恒等式（攻方按真实 p_def 计算，N 个攻方同质）：
  EV_def + N*EV_att = -N*M*(fee_rate*S + llm_cost)
  该恒等式在全程持有近似下严格成立。
- N* 按 p_market 决定：满足 EV_att >= 0 的最大整数 N（上限 50）；
  N=1 仍为负则 N*=0，此时无攻方入场，守方 EV=0。
- 强守方 p_def = p_market * ratio；用二分求 EV_def=0 的 ratio 阈值。
  默认取阈值的一半作为强守方示例，输出攻方真实 EV、守方 EV 和零和残差。

输出：每行一个 JSON；末行以 "OK:" 开头。断言失败抛 AssertionError。
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from typing import Optional, Sequence

# 默认比赛节奏：24h 全程，2h 一个 epoch，每攻方每小时 3 条消息。
CONTEST_HOURS = 24.0
EPOCH_HOURS = 2.0
MESSAGES_PER_HOUR = 3.0
DEFAULT_EPOCHS = int(CONTEST_HOURS / EPOCH_HOURS)  # 12
DEFAULT_M = int(CONTEST_HOURS * MESSAGES_PER_HOUR)  # 72

DEFAULT_P_MARKETS = (0.005, 0.01, 0.02, 0.05)
# 实现用于夹逼的强度比例阶梯（规格未规定该阶梯；从对称到极强守方）。
RATIO_SCAN = (1.0, 0.5, 0.25, 0.1, 0.05, 0.02, 0.01, 0.005, 0.001)
ZERO_SUM_TOL = 1e-9
THRESHOLD_EQ_TOL = 1e-9
BISECTION_STEPS = 200

# self_check() 的固定解析检查网格与容差。
SELF_CHECK_P = (0.001, 0.005, 0.01, 0.05, 0.2)
SELF_CHECK_N = (1, 2, 5)
SELF_CHECK_DECAYS = (1.0, 0.99)
SELF_CHECK_TOL = 1e-12

# 默认参数 + 默认扫描下的 golden 回归值。
GOLDEN_TOL = 1e-9
GOLDEN_FORFEITED = 4.8416182399
GOLDEN_DEFAULT_N_STAR = (0, 1, 1, 2)
GOLDEN_EV_P001_N1 = 1.4688132464  # 8 位参考值 1.46881325 的舍入前值
GOLDEN_RATIO_P005 = 0.0298742846


@dataclass(frozen=True)
class Params:
    """默认参数（与规格 §3.2 一致；仅部分字段暴露为 CLI 覆盖）。"""

    S: float = 50.0              # 守方质押（=奖池）
    stake_rate: float = 0.10     # 攻方质押比例 r，s = r*S
    fee_rate: float = 0.005      # 消息费占 S 的比例，每条 fee_rate*S
    epochs: int = DEFAULT_EPOCHS  # K=12
    keep: float = 0.75           # 每 epoch 保留剩余质押的比例
    M: int = DEFAULT_M           # 每名攻方全程消息数
    llm_cost: float = 0.02       # 每条消息的攻方推理成本（RTM）
    decay: float = 1.0           # 单条攻破概率随消息轮次的衰减
    max_attackers: int = 50      # N* 搜索上限
    strong_fraction: float = 0.5  # 强守方 ratio = 阈值 * 该比例

    @property
    def s(self) -> float:
        return self.S * self.stake_rate

    @property
    def forfeited_per_attacker(self) -> float:
        """全程持有近似下，每名攻方被罚没的质押。"""
        return self.s * (1.0 - self.keep**self.epochs)

    @property
    def fee_per_message(self) -> float:
        return self.fee_rate * self.S

    @property
    def message_cost(self) -> float:
        """每条消息的真实现金/推理成本（手续费 + 推理费），不含质押罚没。"""
        return self.fee_per_message + self.llm_cost

    @property
    def self_play_ev(self) -> float:
        """自攻自守：罚款与奖金均为内部转移，只损失手续费与推理费。"""
        return -self.M * self.message_cost


@dataclass(frozen=True)
class BreachStats:
    p_self: float
    p_survive: float


@dataclass(frozen=True)
class MarketResult:
    p_market: float
    n_star: int
    attacker_ev_expected: Optional[float]
    attacker_ev_first_entrant: float
    attacker_ev_next_entrant: Optional[float]
    defender_ev_symmetric: float
    threshold_ratio: Optional[float]
    strong_ratio: Optional[float]
    p_def: Optional[float]
    attacker_ev_realized: Optional[float]
    defender_ev_strong: Optional[float]
    zero_sum_residual: float
    threshold_verified: Optional[bool]

    def as_json(self) -> dict:
        return {
            "type": "market",
            "p_market": self.p_market,
            "N_star": self.n_star,
            "attacker_ev_expected": self.attacker_ev_expected,
            "attacker_ev_first_entrant": self.attacker_ev_first_entrant,
            "attacker_ev_next_entrant": self.attacker_ev_next_entrant,
            "defender_ev_symmetric": self.defender_ev_symmetric,
            "threshold_ratio": self.threshold_ratio,
            "strong_ratio": self.strong_ratio,
            "p_def": self.p_def,
            "attacker_ev_realized": self.attacker_ev_realized,
            "defender_ev_strong": self.defender_ev_strong,
            "zero_sum_residual": self.zero_sum_residual,
            "threshold_verified": self.threshold_verified,
        }


def _require_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    try:
        finite = math.isfinite(value)
    except (TypeError, OverflowError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite, got {value!r}")


def validate(params: Params, p_markets: Sequence[float]) -> None:
    _require_finite("S", params.S)
    _require_finite("stake_rate", params.stake_rate)
    _require_finite("fee_rate", params.fee_rate)
    _require_finite("llm_cost", params.llm_cost)
    _require_finite("keep", params.keep)
    _require_finite("decay", params.decay)
    _require_finite("strong_fraction", params.strong_fraction)
    _require_finite("M", params.M)
    _require_finite("epochs", params.epochs)
    _require_finite("max_attackers", params.max_attackers)

    for name, value in (
        ("M", params.M),
        ("epochs", params.epochs),
        ("max_attackers", params.max_attackers),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer, got {value!r}")

    if params.S <= 0:
        raise ValueError("S must be positive")
    if not 0.0 < params.stake_rate < 1.0:
        raise ValueError("stake_rate must be in (0,1)")
    if not 0.0 <= params.fee_rate < 1.0:
        raise ValueError("fee_rate must be in [0,1)")
    if params.epochs < 1:
        raise ValueError("epochs must be >= 1")
    if not 0.0 < params.keep < 1.0:
        raise ValueError("keep must be in (0,1)")
    if params.M < 1:
        raise ValueError("M must be >= 1")
    if params.llm_cost < 0.0:
        raise ValueError("llm_cost must be >= 0")
    if not 0.0 < params.decay <= 1.0:
        raise ValueError("decay must be in (0,1]")
    if params.max_attackers < 1:
        raise ValueError("max_attackers must be >= 1")
    if not 0.0 < params.strong_fraction < 1.0:
        raise ValueError("strong_fraction must be in (0,1)")
    if not p_markets:
        raise ValueError("at least one p_market is required")
    for p in p_markets:
        _require_finite("p_market", p)
        if not 0.0 < p <= 1.0:
            raise ValueError(f"p_market must be in (0,1], got {p}")

    if not math.isfinite(params.message_cost) or params.message_cost <= 0.0:
        raise ValueError(
            "fee_rate*S + llm_cost must be finite and > 0; "
            "zero-cost configurations are outside the model scope"
        )


def breach_stats(p: float, n: int, params: Params) -> BreachStats:
    """计算 N 名攻方场景下单攻方胜率与守方全程存活率。

    surv_m 是第 m 轮开始前无人攻破的概率。必须先用它累加本轮贡献，
    再把它乘以本轮 N 人全部失败的概率，不能颠倒顺序。
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be in [0,1], got {p}")

    surv = 1.0
    terms: list[float] = []
    p_m = p
    for _ in range(params.M):
        if not 0.0 <= p_m <= 1.0:
            raise ValueError(
                f"p_m={p_m} outside [0,1] (p={p}, decay={params.decay}); "
                "decay must be <= 1 and p <= 1"
            )
        fail_all = (1.0 - p_m) ** n
        # surv 是更新前的生存率；本轮若至少一人攻破，单攻方分得 1/N。
        terms.append(surv * (1.0 - fail_all))
        surv *= fail_all
        p_m *= params.decay

    p_self = math.fsum(terms) / n
    return BreachStats(p_self=p_self, p_survive=surv)


def attacker_ev(p: float, n: int, params: Params) -> tuple[float, BreachStats]:
    stats = breach_stats(p, n, params)
    ev = (
        stats.p_self * params.S
        - params.forfeited_per_attacker
        - params.M * params.message_cost
    )
    return ev, stats


def defender_ev(p: float, n: int, params: Params) -> tuple[float, Optional[BreachStats]]:
    if n == 0:
        return 0.0, None
    stats = breach_stats(p, n, params)
    ev = n * params.forfeited_per_attacker + params.S * stats.p_survive - params.S
    return ev, stats


def find_equilibrium(
    p_market: float, params: Params
) -> tuple[int, list[float]]:
    """按市场预期计算 N*：最大的 N 使单攻方 EV>=0（N 上限 50）。"""
    evs = [
        attacker_ev(p_market, n, params)[0]
        for n in range(1, params.max_attackers + 1)
    ]
    n_star = 0
    for n, ev in enumerate(evs, start=1):
        if ev >= 0.0:
            n_star = n
    return n_star, evs


def solve_threshold(
    p_market: float, n_star: int, params: Params
) -> tuple[float, bool]:
    """先按实现的夹逼 ratio 阶梯扫描符号变化，再在夹逼区间二分。

    在 ratio=0 时守方白拿 N*F>0；在 ratio=1（对称）时守方 EV<0。
    守方 EV 随 ratio 单调下降，故根唯一。
    """

    def ev_at_ratio(ratio: float) -> float:
        return defender_ev(p_market * ratio, n_star, params)[0]

    ev_at_zero = defender_ev(0.0, n_star, params)[0]
    ev_at_market = ev_at_ratio(1.0)
    if ev_at_zero <= 0.0:
        raise AssertionError(
            f"defender EV at ratio=0 must be positive, got {ev_at_zero}"
        )
    if ev_at_market >= 0.0:
        raise AssertionError(
            f"symmetric defender EV at N* must be negative, got {ev_at_market}"
        )

    scan = [(ratio, ev_at_ratio(ratio)) for ratio in RATIO_SCAN]
    bracket: Optional[tuple[float, float]] = None
    for (neg_ratio, neg_ev), (pos_ratio, pos_ev) in zip(scan, scan[1:]):
        if neg_ev <= 0.0 < pos_ev:
            # RATIO_SCAN 递减；pos_ratio 是正 EV 端，neg_ratio 是非正 EV 端。
            bracket = (pos_ratio, neg_ratio)
            break
    if bracket is None:
        if scan[-1][1] > 0.0:
            raise AssertionError(
                "ratio scan neither brackets the root nor falls below it: "
                f"ev(1.0)={scan[0][1]}, ev(0.001)={scan[-1][1]}"
            )
        # 阶梯最小 ratio 处仍非正：根在 (0, 0.001) 内。
        bracket = (0.0, scan[-1][0])

    lo, hi = bracket  # EV(lo)>0, EV(hi)<=0
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if mid == lo or mid == hi:
            break
        if ev_at_ratio(mid) > 0.0:
            lo = mid
        else:
            hi = mid

    ratio = (lo + hi) / 2.0
    root_ev = ev_at_ratio(ratio)
    return ratio, abs(root_ev) <= THRESHOLD_EQ_TOL


def self_check(params: Params, rows: Sequence[MarketResult]) -> dict:
    """运行可执行的解析自检，返回可写入 assertions 的报告。

    1) telescoping 恒等式 N*p_self == 1-P_survive，固定 (p,N,decay) 网格；
    2) 闭式阈值（仅 decay=1.0）：对当前扫描去重后的 N*>0 市场，
       比较闭式解与二分结果；
    3) golden 回归：仅当 Params 与 p_market 扫描均为默认值时执行。
    """
    telescoping_checked = 0
    telescoping_max_error = 0.0
    telescoping_failures: list[dict] = []
    for decay in SELF_CHECK_DECAYS:
        check_params = replace(params, decay=decay)
        for p in SELF_CHECK_P:
            for n in SELF_CHECK_N:
                stats = breach_stats(p, n, check_params)
                error = abs(n * stats.p_self - (1.0 - stats.p_survive))
                telescoping_checked += 1
                telescoping_max_error = max(telescoping_max_error, error)
                if error >= SELF_CHECK_TOL:
                    telescoping_failures.append(
                        {
                            "p": p,
                            "N": n,
                            "decay": decay,
                            "abs_error": error,
                        }
                    )
    telescoping_pass = not telescoping_failures

    # 当前扫描先去重；重复 p_market 的 N* 冲突视为失败。
    market_ns: dict[float, int] = {}
    duplicate_conflicts: list[dict] = []
    for row in rows:
        if row.p_market in market_ns:
            if market_ns[row.p_market] != row.n_star:
                duplicate_conflicts.append(
                    {
                        "p_market": row.p_market,
                        "first_N_star": market_ns[row.p_market],
                        "duplicate_N_star": row.n_star,
                    }
                )
        else:
            market_ns[row.p_market] = row.n_star

    active = [(p, n) for p, n in market_ns.items() if n > 0]
    closed_checked = 0
    closed_max_error = 0.0
    closed_failures: list[dict] = []
    closed_checks: list[dict] = []
    closed_skipped: list[dict] = []
    closed_reason: Optional[str] = None

    if params.decay != 1.0:
        closed_reason = (
            f"decay={params.decay} != 1.0; "
            "closed form only applies at decay=1.0"
        )
        closed_skipped.append({"reason": closed_reason})
    elif not active:
        closed_reason = "no active markets (N*>0) in current scan"
        for p, n in market_ns.items():
            closed_skipped.append({"p_market": p, "reason": "N*=0"})
    else:
        for p_market, n_star in active:
            exposure = n_star * params.forfeited_per_attacker / params.S
            if exposure >= 1.0:
                closed_skipped.append(
                    {
                        "p_market": p_market,
                        "N_star": n_star,
                        "reason": "N*F/S >= 1",
                    }
                )
                continue
            p_def_closed = 1.0 - (1.0 - exposure) ** (
                1.0 / (n_star * params.M)
            )
            ratio_bisect, bisect_ok = solve_threshold(
                p_market, n_star, params
            )
            p_def_bisect = ratio_bisect * p_market
            error = abs(p_def_closed - p_def_bisect)
            closed_checked += 1
            closed_max_error = max(closed_max_error, error)
            check = {
                "p_market": p_market,
                "N_star": n_star,
                "closed_form_p_def": p_def_closed,
                "bisection_p_def": p_def_bisect,
                "bisection_verified": bisect_ok,
                "abs_error": error,
            }
            closed_checks.append(check)
            if error >= SELF_CHECK_TOL or not bisect_ok:
                closed_failures.append(check)
        if not closed_checks:
            closed_failures.append(
                {
                    "reason": (
                        "active markets present but no closed-form "
                        "check executed"
                    )
                }
            )
        active_markets = {p for p, _ in active}
        for p, n in market_ns.items():
            if p not in active_markets:
                closed_skipped.append({"p_market": p, "reason": "N*=0"})

    if duplicate_conflicts:
        closed_failures.append(
            {
                "reason": "duplicate p_market with conflicting N*",
                "duplicates": duplicate_conflicts,
            }
        )

    closed_applicable = params.decay == 1.0 and bool(active)
    closed_pass = not closed_failures

    default_params = params == Params()
    default_scan = [row.p_market for row in rows] == list(DEFAULT_P_MARKETS)
    golden_applicable = default_params and default_scan
    golden_reason: Optional[str] = None
    if not default_params:
        golden_reason = "params differ from defaults"
    elif not default_scan:
        golden_reason = "p_market scan differs from default"

    golden_checks: list[dict] = []
    if golden_applicable:
        f_actual = params.forfeited_per_attacker
        golden_checks.append(
            {
                "name": "forfeited_per_attacker",
                "actual": f_actual,
                "expected": GOLDEN_FORFEITED,
                "abs_error": abs(f_actual - GOLDEN_FORFEITED),
                "tolerance": GOLDEN_TOL,
                "pass": abs(f_actual - GOLDEN_FORFEITED) <= GOLDEN_TOL,
            }
        )
        n_actual = [row.n_star for row in rows]
        n_expected = list(GOLDEN_DEFAULT_N_STAR)
        golden_checks.append(
            {
                "name": "default_N_star",
                "actual": n_actual,
                "expected": n_expected,
                "pass": n_actual == n_expected,
            }
        )
        ev_actual, _ = attacker_ev(0.01, 1, params)
        golden_checks.append(
            {
                "name": "attacker_ev_p001_n1",
                "actual": ev_actual,
                "expected": GOLDEN_EV_P001_N1,
                "reference": 1.46881325,
                "abs_error": abs(ev_actual - GOLDEN_EV_P001_N1),
                "tolerance": GOLDEN_TOL,
                "pass": abs(ev_actual - GOLDEN_EV_P001_N1) <= GOLDEN_TOL,
            }
        )
        n_star_005, _ = find_equilibrium(0.05, params)
        ratio_actual, ratio_ok = solve_threshold(0.05, n_star_005, params)
        golden_checks.append(
            {
                "name": "ratio_threshold_p005",
                "actual": ratio_actual,
                "expected": GOLDEN_RATIO_P005,
                "abs_error": abs(ratio_actual - GOLDEN_RATIO_P005),
                "tolerance": GOLDEN_TOL,
                "pass": (
                    abs(ratio_actual - GOLDEN_RATIO_P005) <= GOLDEN_TOL
                    and ratio_ok
                ),
            }
        )
    golden_failures = [check for check in golden_checks if not check["pass"]]
    golden_pass = not golden_failures

    return {
        "pass": telescoping_pass and closed_pass and golden_pass,
        "telescoping": {
            "checked": telescoping_checked,
            "max_abs_error": telescoping_max_error,
            "tolerance": SELF_CHECK_TOL,
            "grid": {
                "p": list(SELF_CHECK_P),
                "N": list(SELF_CHECK_N),
                "decay": list(SELF_CHECK_DECAYS),
            },
            "failures": telescoping_failures,
        },
        "closed_form_threshold": {
            "applicable": closed_applicable,
            "reason": closed_reason,
            "checked": closed_checked,
            "max_abs_error": closed_max_error if closed_checked else None,
            "tolerance": SELF_CHECK_TOL,
            "checked_markets": closed_checks,
            "skipped": closed_skipped,
            "duplicate_conflicts": duplicate_conflicts,
            "failures": closed_failures,
        },
        "golden": {
            "applicable": golden_applicable,
            "reason": golden_reason,
            "tolerance": GOLDEN_TOL,
            "checks": golden_checks,
            "failures": golden_failures,
        },
    }


def simulate_market(p_market: float, params: Params) -> MarketResult:
    n_star, evs = find_equilibrium(p_market, params)
    first_entrant_ev = evs[0]

    if n_star == 0:
        return MarketResult(
            p_market=p_market,
            n_star=0,
            attacker_ev_expected=None,
            attacker_ev_first_entrant=first_entrant_ev,
            # N*=0 时，第一个入场者就是"边际下一位"。
            attacker_ev_next_entrant=first_entrant_ev,
            defender_ev_symmetric=0.0,
            threshold_ratio=None,
            strong_ratio=None,
            p_def=None,
            attacker_ev_realized=None,
            defender_ev_strong=None,
            zero_sum_residual=0.0,
            threshold_verified=None,
        )

    attacker_ev_expected = evs[n_star - 1]
    attacker_ev_next_entrant = (
        evs[n_star] if n_star < params.max_attackers else None
    )
    defender_ev_symmetric, _ = defender_ev(p_market, n_star, params)

    threshold_ratio, threshold_verified = solve_threshold(
        p_market, n_star, params
    )
    strong_ratio = threshold_ratio * params.strong_fraction
    p_def = p_market * strong_ratio

    attacker_ev_realized, _ = attacker_ev(p_def, n_star, params)
    defender_ev_strong, _ = defender_ev(p_def, n_star, params)
    zero_sum_residual = (
        defender_ev_strong
        + n_star * attacker_ev_realized
        + n_star * params.M * params.message_cost
    )

    return MarketResult(
        p_market=p_market,
        n_star=n_star,
        attacker_ev_expected=attacker_ev_expected,
        attacker_ev_first_entrant=first_entrant_ev,
        attacker_ev_next_entrant=attacker_ev_next_entrant,
        defender_ev_symmetric=defender_ev_symmetric,
        threshold_ratio=threshold_ratio,
        strong_ratio=strong_ratio,
        p_def=p_def,
        attacker_ev_realized=attacker_ev_realized,
        defender_ev_strong=defender_ev_strong,
        zero_sum_residual=zero_sum_residual,
        threshold_verified=threshold_verified,
    )


def build_assertion_report(
    rows: Sequence[MarketResult], params: Params, analytical: dict
) -> dict:
    items = []

    items.append(
        {
            "name": "self_play_ev_negative",
            "pass": params.self_play_ev < 0.0,
            "detail": {"self_play_EV": params.self_play_ev},
        }
    )

    equilibrium_checks: list[dict] = []
    for row in rows:
        n_star = row.n_star
        at_cap = n_star == params.max_attackers
        if n_star < 0 or n_star > params.max_attackers:
            equilibrium_checks.append(
                {
                    "p_market": row.p_market,
                    "N_star": n_star,
                    "at_cap": False,
                    "ev_at_N_star": None,
                    "ev_at_next": None,
                    "pass": False,
                    "note": "N* outside [0, cap]",
                }
            )
        elif n_star == 0:
            ev_next, _ = attacker_ev(row.p_market, 1, params)
            equilibrium_checks.append(
                {
                    "p_market": row.p_market,
                    "N_star": 0,
                    "at_cap": False,
                    "ev_at_N_star": None,
                    "ev_at_next": ev_next,
                    "pass": ev_next < 0.0,
                    "note": "no-entry: EV_att(N=1) < 0",
                }
            )
        else:
            ev_n, _ = attacker_ev(row.p_market, n_star, params)
            if at_cap:
                equilibrium_checks.append(
                    {
                        "p_market": row.p_market,
                        "N_star": n_star,
                        "at_cap": True,
                        "ev_at_N_star": ev_n,
                        "ev_at_next": None,
                        "pass": ev_n >= 0.0,
                        "note": (
                            "cap-bound: EV_att(N*) >= 0; "
                            "free entry beyond cap not evaluated"
                        ),
                    }
                )
            else:
                ev_next, _ = attacker_ev(
                    row.p_market, n_star + 1, params
                )
                equilibrium_checks.append(
                    {
                        "p_market": row.p_market,
                        "N_star": n_star,
                        "at_cap": False,
                        "ev_at_N_star": ev_n,
                        "ev_at_next": ev_next,
                        "pass": ev_n >= 0.0 and ev_next < 0.0,
                        "note": (
                            "recomputed EV_att(N*) >= 0 and "
                            "EV_att(N*+1) < 0"
                        ),
                    }
                )

    n_star_bounded = all(
        0 <= row.n_star <= params.max_attackers for row in rows
    ) and all(check["pass"] for check in equilibrium_checks)
    items.append(
        {
            "name": "n_star_bounded",
            "pass": n_star_bounded,
            "detail": {
                "cap": params.max_attackers,
                "max_N_star": max((row.n_star for row in rows), default=0),
                "at_cap": any(
                    check["at_cap"] for check in equilibrium_checks
                ),
                "at_cap_markets": [
                    check["p_market"]
                    for check in equilibrium_checks
                    if check["at_cap"]
                ],
                "recomputed": equilibrium_checks,
            },
        }
    )

    active = [row for row in rows if row.n_star >= 1]
    strong_positive = [
        row
        for row in active
        if row.defender_ev_strong is not None and row.defender_ev_strong > 0.0
    ]
    thresholds_verified = all(row.threshold_verified for row in active)
    items.append(
        {
            "name": "strong_defender_positive_exists",
            "pass": bool(strong_positive) and thresholds_verified,
            "detail": {
                "markets_with_positive_strong_defender_ev": [
                    row.p_market for row in strong_positive
                ],
                "count": len(strong_positive),
                "thresholds_verified": thresholds_verified,
            },
        }
    )

    symmetric_negative = all(
        row.defender_ev_symmetric < 0.0 for row in active
    )
    items.append(
        {
            "name": "symmetric_defender_negative",
            "pass": symmetric_negative,
            "detail": {
                "checked_markets": len(active),
                "closest_to_zero": max(
                    (row.defender_ev_symmetric for row in active), default=None
                ),
            },
        }
    )

    max_abs_residual = max(
        (abs(row.zero_sum_residual) for row in rows), default=0.0
    )
    items.append(
        {
            "name": "zero_sum_residual_below_tolerance",
            "pass": max_abs_residual < ZERO_SUM_TOL,
            "detail": {
                "max_abs_residual": max_abs_residual,
                "tolerance": ZERO_SUM_TOL,
            },
        }
    )

    items.append(
        {
            "name": "analytical_self_checks",
            "pass": bool(analytical["pass"]),
            "detail": analytical,
        }
    )

    return {
        "type": "assertions",
        "all_passed": all(item["pass"] for item in items),
        "items": items,
    }


def emit(obj: dict) -> None:
    print(
        json.dumps(
            obj,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )


def _fmt_optional(value: Optional[float], spec: str) -> str:
    return "null" if value is None else format(value, spec)


def print_ok_summary(
    rows: Sequence[MarketResult], params: Params, report: dict
) -> None:
    passed = sum(1 for item in report["items"] if item["pass"])
    parts = [
        f"OK: assertions={passed}/{len(report['items'])}",
        f"self_play_EV={params.self_play_ev:.6f}",
    ]
    for row in rows:
        parts.append(
            f"p_market={row.p_market:.6g} N*={row.n_star} "
            f"EV_att_expected={_fmt_optional(row.attacker_ev_expected, '.6f')} "
            f"EV_att_realized={_fmt_optional(row.attacker_ev_realized, '.6f')} "
            f"EV_def_symmetric={row.defender_ev_symmetric:.6f} "
            f"EV_def_strong={_fmt_optional(row.defender_ev_strong, '.6f')} "
            f"ratio_threshold={_fmt_optional(row.threshold_ratio, '.8f')} "
            f"ratio_strong={_fmt_optional(row.strong_ratio, '.8f')} "
            f"residual={row.zero_sum_residual:.3e} "
            f"EV_att_first_entrant={row.attacker_ev_first_entrant:.6f}"
        )
    print("; ".join(parts))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    defaults = Params()
    parser = argparse.ArgumentParser(
        description=(
            "REDTEAM P0 mechanism simulation. "
            "Outputs one JSON object per line plus a final OK summary."
        )
    )
    parser.add_argument(
        "--p-market",
        type=float,
        nargs="+",
        default=list(DEFAULT_P_MARKETS),
        metavar="P",
        help="market-perceived per-message breach probability scan",
    )
    parser.add_argument(
        "--M",
        type=int,
        default=defaults.M,
        metavar="MSGS",
        help="messages per attacker over the full contest",
    )
    parser.add_argument(
        "--llm-cost",
        type=float,
        default=defaults.llm_cost,
        metavar="RTM",
        help="attacker inference cost per message (RTM)",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=defaults.fee_rate,
        metavar="RATE",
        help="message fee as a fraction of S (default 0.005)",
    )
    parser.add_argument(
        "--decay",
        type=float,
        default=defaults.decay,
        metavar="D",
        help="per-round breach-probability decay (default 1.0)",
    )
    parser.add_argument(
        "--strong-fraction",
        type=float,
        default=defaults.strong_fraction,
        metavar="F",
        help="strong-defender ratio = threshold ratio * F (default 0.5)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    defaults = Params()
    params = replace(
        defaults,
        M=args.M,
        llm_cost=args.llm_cost,
        fee_rate=args.fee_rate,
        decay=args.decay,
        strong_fraction=args.strong_fraction,
    )
    p_markets = list(args.p_market)
    validate(params, p_markets)

    emit(
        {
            "type": "params",
            "S": params.S,
            "stake_rate": params.stake_rate,
            "s": params.s,
            "contest_hours": CONTEST_HOURS,
            "epoch_hours": EPOCH_HOURS,
            "epochs": params.epochs,
            "keep": params.keep,
            "keep_pow_epochs": params.keep**params.epochs,
            "forfeited_per_attacker": params.forfeited_per_attacker,
            "M": params.M,
            "messages_per_hour": params.M / CONTEST_HOURS,
            "fee_rate": params.fee_rate,
            "fee_per_message": params.fee_per_message,
            "llm_cost_per_message": params.llm_cost,
            "message_cost": params.message_cost,
            "decay": params.decay,
            "max_attackers": params.max_attackers,
            "strong_fraction": params.strong_fraction,
            "p_market_scan": p_markets,
        }
    )
    emit(
        {
            "type": "self_play",
            "self_play_EV": params.self_play_ev,
            "messages_per_attacker": params.M,
            "fee_total_per_attacker": params.M * params.fee_per_message,
            "llm_total_per_attacker": params.M * params.llm_cost,
        }
    )

    rows = [simulate_market(p, params) for p in p_markets]
    for row in rows:
        emit(row.as_json())

    analytical = self_check(params, rows)
    report = build_assertion_report(rows, params, analytical)
    emit(report)
    if not report["all_passed"]:
        failed = [
            item["name"] for item in report["items"] if not item["pass"]
        ]
        raise AssertionError(
            "P0 mechanism simulation assertions failed: " + ", ".join(failed)
        )

    print_ok_summary(rows, params, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
