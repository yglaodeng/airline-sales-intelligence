from __future__ import annotations

import math


def safe_number(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def calc_trend_direction(speed_3d, speed_7d):
    """Compare near-term sales speed with the weekly baseline."""
    s3 = safe_number(speed_3d)
    s7 = safe_number(speed_7d)
    if s7 <= 0:
        return "平稳"
    if s3 > s7 * 1.1:
        return "加速"
    if s3 < s7 * 0.9:
        return "减速"
    return "平稳"


def calc_pressure_level(pressure_index, trend_direction, speed_3d, history_avg_speed):
    """Return an upgraded pressure/action decision without changing existing UI names."""
    p = safe_number(pressure_index)
    s3 = safe_number(speed_3d)
    history = safe_number(history_avg_speed)
    trend_note = f"近3天动销{trend_direction}" if trend_direction else "近3天动销平稳"

    if p >= 1.5:
        if history > 0 and s3 < history * 0.8:
            return {
                "pressure_level": "严重积压",
                "suggested_action": "立即降价",
                "suggested_change_percent": -10,
                "suggested_change_range": "-8% ~ -12%",
                "priority": "高",
                "note": f"{trend_note}，库存压力严重且动销低于历史，建议大幅降价测试。",
            }
        return {
            "pressure_level": "偏慢",
            "suggested_action": "降价测试",
            "suggested_change_percent": -5,
            "suggested_change_range": "-3% ~ -5%",
            "priority": "高",
            "note": f"{trend_note}，库存压力偏高，先做降价测试。",
        }
    if p >= 1.2:
        if history > 0 and s3 < history * 0.9:
            return {
                "pressure_level": "偏慢",
                "suggested_action": "降价测试",
                "suggested_change_percent": -5,
                "suggested_change_range": "-3% ~ -5%",
                "priority": "高",
                "note": f"{trend_note}，库存偏高且动销偏慢。",
            }
        return {
            "pressure_level": "正常",
            "suggested_action": "维持现价",
            "suggested_change_percent": 0,
            "suggested_change_range": "0%",
            "priority": "中",
            "note": f"{trend_note}，库存可控，先维持观察。",
        }
    if p > 0.8:
        if history > 0 and s3 < history * 0.8:
            return {
                "pressure_level": "正常",
                "suggested_action": "小幅降价观察",
                "suggested_change_percent": -3,
                "suggested_change_range": "-2% ~ -3%",
                "priority": "中",
                "note": f"{trend_note}，库存压力正常但动销突然变慢。",
            }
        if history > 0 and s3 > history * 1.2:
            return {
                "pressure_level": "偏快",
                "suggested_action": "小幅提价",
                "suggested_change_percent": 3,
                "suggested_change_range": "+3% ~ +5%",
                "priority": "中",
                "note": f"{trend_note}，动销快于历史，可小幅提价测试。",
            }
        return {
            "pressure_level": "正常",
            "suggested_action": "维持现价",
            "suggested_change_percent": 0,
            "suggested_change_range": "0%",
            "priority": "中",
            "note": f"{trend_note}，节奏正常。",
        }
    if history > 0 and s3 > history * 1.3:
        return {
            "pressure_level": "很快",
            "suggested_action": "提价或控量",
            "suggested_change_percent": 5,
            "suggested_change_range": "+5% ~ +8%",
            "priority": "低（慎用）",
            "note": f"{trend_note}，库存紧张且卖得快，建议控量慎降价。",
        }
    return {
        "pressure_level": "偏快",
        "suggested_action": "小幅提价",
        "suggested_change_percent": 3,
        "suggested_change_range": "+3% ~ +5%",
        "priority": "中",
        "note": f"{trend_note}，库存压力偏低，可小幅提价。",
    }


def apply_advice_to_backtest(rows, cost_floor=0):
    """Build control/experiment comparison from existing price-adjustment rows."""
    floor = safe_number(cost_floor)
    control_revenue = 0.0
    experiment_revenue = 0.0
    control_profit = 0.0
    experiment_profit = 0.0
    sold_qty = 0.0
    potential_qty = 0.0
    below_cost_count = 0
    tail_loss = 0.0
    daily_data = []

    for row in rows:
        qty = safe_number(row.get("模拟销量"), safe_number(row.get("建议销售张数")))
        control_price = safe_number(row.get("对照组售价"), safe_number(row.get("原建议售价")))
        experiment_price = safe_number(row.get("建议调后价"), control_price)
        remaining = safe_number(row.get("剩余库存R"))
        lead_days = safe_number(row.get("距离起飞D"))
        below_cost = bool(row.get("below_cost_floor")) or (floor > 0 and experiment_price < floor)

        control_revenue += qty * control_price
        experiment_revenue += qty * experiment_price
        if floor:
            control_profit += qty * (control_price - floor)
            experiment_profit += qty * (experiment_price - floor)
        sold_qty += max(0, qty)
        potential_qty += max(0, qty) + max(0, remaining)
        if below_cost:
            below_cost_count += 1
        if floor and lead_days <= 7:
            tail_loss += max(0, remaining) * floor
        daily_data.append({
            "销售日期": row.get("销售日期", ""),
            "起飞日期": row.get("起飞日期", ""),
            "对照组售价": round(control_price),
            "实验组售价": round(experiment_price),
            "模拟销量": round(qty),
            "below_cost_floor": below_cost,
        })

    revenue_change = (experiment_revenue - control_revenue) / abs(control_revenue) * 100 if control_revenue else 0
    profit_change = (experiment_profit - control_profit) / abs(control_profit) * 100 if floor and control_profit else None
    sell_out_rate = sold_qty / potential_qty * 100 if potential_qty else 0
    avg_discount_rate = 0
    if control_revenue:
        avg_discount_rate = (control_revenue - experiment_revenue) / abs(control_revenue) * 100

    return {
        "control_group": {
            "total_revenue": round(control_revenue),
            "total_profit": round(control_profit) if floor else None,
            "sell_out_rate": round(sell_out_rate, 2),
        },
        "experiment_group": {
            "total_revenue": round(experiment_revenue),
            "total_profit": round(experiment_profit) if floor else None,
            "sell_out_rate": round(sell_out_rate, 2),
            "tail_loss": round(tail_loss),
            "avg_discount_rate": round(avg_discount_rate, 2),
            "below_cost_count": below_cost_count,
            "daily_data": daily_data[:300],
        },
        "comparison": {
            "revenue_change_percent": round(revenue_change, 2),
            "profit_change_percent": round(profit_change, 2) if profit_change is not None else None,
            "sell_out_rate_change": 0,
            "tail_loss_change": None,
            "data_days": len(rows),
            "cost_floor": round(floor) if floor else None,
        },
    }
