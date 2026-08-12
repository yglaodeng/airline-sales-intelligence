from __future__ import annotations

import json
import csv
import io
import os
import secrets
import string
import tempfile
import traceback
import re
import time
import urllib.request
import hashlib
import math
import html
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import cgi

import pandas as pd

from pricing_advice import apply_advice_to_backtest, calc_pressure_level, calc_trend_direction


ROOT = Path(__file__).resolve().parent
DEFAULT_FILE = Path(os.environ.get("AIRLINE_DEFAULT_FILE", ROOT / "sample-sales.xlsx"))
CACHE_FILE = ROOT / "route_schedule_cache.json"
FULL_STRATEGY_DIR = ROOT / "outputs" / "sales_strategy_all"
FULL_STRATEGY_METADATA_FILE = FULL_STRATEGY_DIR / "metadata.json"
AI_ANALYSIS_DIR = ROOT / "outputs" / "ai_analysis"
AI_PACKAGE_DIR = AI_ANALYSIS_DIR / "packages"
AI_SUGGESTION_DIR = AI_ANALYSIS_DIR / "suggestions"
AI_AUDIT_DIR = AI_ANALYSIS_DIR / "audits"
INVENTORY_FILE = ROOT / "inventory_positions.json"
EXECUTION_TASK_FILE = ROOT / "strategy_execution_tasks.json"
OPERATION_CENTER_FILE = ROOT / "operation_center.json"
AUTOMATION_JOBS_FILE = ROOT / "automation_jobs.json"
ACCESS_CONTROL_FILE = ROOT / "access_control.json"
AUDIT_LOG_FILE = ROOT / "audit_logs.json"
NIGHTLY_REVIEW_FILE = ROOT / "outputs" / "nightly_sales_review.json"
PRICE_ADJUSTMENT_DIR = ROOT / "outputs" / "price_adjustment"
GITHUB_ROUTE_DATA_URL = "https://raw.githubusercontent.com/Jonty/airline-route-data/master/airline_routes.json"
OTA_PLATFORMS = ["携程", "去哪儿", "飞猪", "同程", "PK", "其他平台"]
AIRLINE_LOCAL_HOST = os.environ.get("AIRLINE_LOCAL_HOST", "127.0.0.1")
AIRLINE_LOCAL_PORT = int(os.environ.get("AIRLINE_LOCAL_PORT", "8000"))
MOCK_OTA_BASE_URL = os.environ.get("MOCK_OTA_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
MOCK_OTA_TOKEN = os.environ.get("MOCK_OTA_TOKEN", "mock-ota-local-token")
PERMISSION_DEFINITIONS = {
    "dashboard.view": "查看运营驾驶舱",
    "strategy.view": "查看策略/模型/风险",
    "operation.view": "查看运营中心",
    "operation.write": "新增/修改运营中心记录",
    "operation.bulk": "运营中心批量处理",
    "operation.export": "导出运营中心数据",
    "execution.manage": "管理策略执行任务和OTA执行",
    "ai.manage": "生成/导入AI建议",
    "data.manage": "数据状态与系统生成数据清理",
    "settings.accounts": "管理员工账号和权限",
    "settings.logs": "查看操作日志",
    "system.admin": "系统管理员权限",
}
ROLE_TEMPLATES = {
    "sales": {
        "label": "销售",
        "description": "可看策略和运营中心，可维护订单、售后、支付等业务台账。",
        "permissions": ["dashboard.view", "strategy.view", "operation.view", "operation.write", "operation.export"],
    },
    "operation": {
        "label": "运营",
        "description": "可维护运营中心，处理批量、库存、出票和执行任务。",
        "permissions": ["dashboard.view", "strategy.view", "operation.view", "operation.write", "operation.bulk", "operation.export", "execution.manage"],
    },
    "finance": {
        "label": "财务",
        "description": "可查看策略和运营中心，维护支付回填并导出数据。",
        "permissions": ["dashboard.view", "operation.view", "operation.write", "operation.export"],
    },
    "manager": {
        "label": "主管",
        "description": "可管理大多数业务功能，不包含账号权限和高风险系统清理。",
        "permissions": ["dashboard.view", "strategy.view", "operation.view", "operation.write", "operation.bulk", "operation.export", "execution.manage", "ai.manage", "settings.logs"],
    },
    "viewer": {
        "label": "只读",
        "description": "只能查看核心页面和导出，不可写入或执行。",
        "permissions": ["dashboard.view", "strategy.view", "operation.view", "operation.export"],
    },
    "accountAdmin": {
        "label": "账号管理员",
        "description": "可管理员工账号和日志，适合后台权限维护。",
        "permissions": ["dashboard.view", "settings.accounts", "settings.logs"],
    },
}
LEGACY_ROLE_MAP = {
    "employee": "sales",
    "operator": "operation",
    "viewer": "viewer",
}
DEFAULT_ADMIN_PASSWORD = os.environ.get("AIR_SKILL_ADMIN_PASSWORD", "").strip()
if not DEFAULT_ADMIN_PASSWORD:
    raise RuntimeError("请先设置 AIR_SKILL_ADMIN_PASSWORD 环境变量。")
ADMIN_SESSION_SECONDS = 10 * 365 * 24 * 3600
LONG_TERM_SECONDS = 10 * 365 * 24 * 3600
FULL_STRATEGY_FILES = [
    "route_strategy.csv",
    "bucket_detail.csv",
    "route_airline_summary.csv",
    "file_manifest.csv",
    "report.md",
]
SYSTEM_CLEAR_FILE_ALLOWLIST = {
    *(FULL_STRATEGY_DIR / name for name in FULL_STRATEGY_FILES),
    FULL_STRATEGY_METADATA_FILE,
    CACHE_FILE,
    INVENTORY_FILE,
    EXECUTION_TASK_FILE,
    OPERATION_CENTER_FILE,
    AUDIT_LOG_FILE,
    ACCESS_CONTROL_FILE,
    NIGHTLY_REVIEW_FILE,
}


def json_safe(value):
    """Convert pandas/numpy missing values to strict JSON-safe values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return value
BUCKETS = ["1天", "2-4天", "5-9天", "10-14天", "15-21天", "22-30天", "31-45天", "46天以上"]
CITY_AIRPORTS = {
    "BJS": ["PEK", "PKX"],
    "TYO": ["HND", "NRT"],
    "SHA": ["SHA", "PVG"],
    "SEL": ["ICN", "GMP"],
    "OSA": ["KIX", "ITM", "UKB"],
    "NYC": ["JFK", "EWR", "LGA"],
    "LON": ["LHR", "LGW", "STN", "LTN", "LCY"],
    "PAR": ["CDG", "ORY"],
    "MIL": ["MXP", "LIN", "BGY"],
}
AIRPORT_REGION = {
    "ICN": "韩国", "GMP": "韩国", "CJU": "韩国", "CJJ": "韩国", "CJF": "韩国",
    "NRT": "日本", "KIX": "日本", "FUK": "日本", "NGO": "日本",
    "BKK": "泰国", "KUL": "马来西亚", "KTI": "马来西亚", "SIN": "新加坡",
    "CAN": "中国", "RGN": "缅甸", "LAX": "北美",
    "PKX": "中国", "PEK": "中国", "PVG": "中国", "TNA": "中国", "CGO": "中国", "HKG": "中国", "KWL": "中国",
    "JFK": "北美", "EWR": "北美", "SFO": "北美", "SEA": "北美", "YVR": "北美", "YYZ": "北美",
    "LHR": "欧洲", "CDG": "欧洲", "FRA": "欧洲", "AMS": "欧洲", "MAD": "欧洲", "IST": "欧洲",
    "DXB": "中东", "DOH": "中东", "AUH": "中东", "RUH": "中东", "JED": "中东",
    "SYD": "澳新", "MEL": "澳新", "AKL": "澳新",
    "DEL": "南亚", "BOM": "南亚", "CMB": "南亚",
}

ROUTE_SCHEDULES = {
    "PKX-CJU": {
        "route": "PKX-CJU",
        "sourceNote": "公开航班网站显示该航线由春秋航空和济州航空执飞；不同网站对周班次有差异，页面先按每日班次估算。",
        "marketRoundTripUsd": 260,
        "airlines": [
            {"航司": "Spring Airlines / 春秋航空", "代码": "9C", "机型": "Airbus A320", "座位": 180, "每周班次": 7, "定位": "低成本航司"},
            {"航司": "Jeju Air / 济州航空", "代码": "7C", "机型": "Boeing 737-800", "座位": 186, "每周班次": 7, "定位": "低成本航司"},
        ],
        "sources": [
            {"name": "FlightsFrom PKX-CJU", "url": "https://www.flightsfrom.com/PKX-CJU"},
            {"name": "Directflights PKX-CJU", "url": "https://www.directflights.com/PKX-CJU"},
        ],
    },
    "PKX-ICN": {
        "route": "PKX-ICN",
        "sourceNote": "FlightsFrom 和 Aviability 均显示 PKX-ICN 有南航、东航、国航直飞；FlightsFrom 显示3个航司各每日1班，公开排班会随季节变化。",
        "marketRoundTripUsd": 230,
        "airlines": [
            {"航司": "China Southern Airlines / 中国南方航空", "代码": "CZ", "机型": "Boeing 737", "座位": 170, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "China Eastern Airlines / 中国东方航空", "代码": "MU", "机型": "Boeing 737", "座位": 170, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "Air China / 中国国际航空", "代码": "CA", "机型": "Boeing 737", "座位": 170, "每周班次": 7, "定位": "全服务航司"},
        ],
        "sources": [
            {"name": "FlightsFrom PKX-ICN", "url": "https://www.flightsfrom.com/PKX-ICN"},
            {"name": "Aviability PKX-ICN", "url": "https://aviability.com/en/route/pkx-beijing-daxing/icn-seoul-incheon"},
            {"name": "Air China schedule PDF", "url": "https://www.asianasabre.co.kr/CommonFiles/BoardUpLoadFiles/AirLineNews/85838/%EA%B3%B5%EB%AC%B825-043%20CA%202025%20%ED%95%9C%EC%A4%91%EB%85%B8%EC%84%A0%20%EB%8F%99%EA%B3%84%20%EC%8A%A4%EC%BC%80%EC%A4%84%20%EC%95%88%EB%82%B4%20-%20251022%20%EC%88%98%EC%A0%95.pdf"},
        ],
    }
}

PUBLIC_ROUTE_FACTS = {
    "CAN-RGN": {
        "route": "CAN-RGN",
        "sourceNote": "公开航班网站显示 CAN-RGN 有直飞。Directflights 显示由中国南方航空和 Myanmar Airways International 执飞，约12班/周；FlightConnections 也显示2家航司运营直飞。",
        "marketRoundTripUsd": 230,
        "airlines": [
            {"航司": "China Southern Airlines / 中国南方航空", "代码": "CZ", "机型": "Boeing 737 / Airbus A320", "座位": 170, "每周班次": 6, "定位": "全服务航司"},
            {"航司": "Myanmar Airways International / 缅甸国际航空", "代码": "8M", "机型": "Airbus A319/A320", "座位": 150, "每周班次": 6, "定位": "区域航司"},
        ],
        "sources": [
            {"name": "FlightsFrom CAN-RGN", "url": "https://www.flightsfrom.com/CAN-RGN"},
            {"name": "Directflights CAN-RGN", "url": "https://www.directflights.com/CAN-RGN"},
            {"name": "FlightConnections CAN-RGN", "url": "https://www.flightconnections.com/flights-from-can-to-rgn"},
            {"name": "Wego CAN-RGN schedules", "url": "https://www.wego.com/schedules/can/rgn/flight-schedules-from-guangzhou-to-yangon"},
        ],
    },
    "CJU-SIN": {
        "route": "CJU-SIN",
        "sourceNote": "FlightsFrom 显示 CJU-SIN 由 Scoot 与 T'Way Air 直飞，约12班/周；机型包括 Scoot A320neo 约186座、T'Way 737 MAX 8约189座。FlightRoutes 也列出 Scoot 与 T'Way Air 直飞。",
        "marketRoundTripUsd": 300,
        "airlines": [
            {"航司": "Scoot / 酷航", "代码": "TR", "机型": "Airbus A320neo", "座位": 186, "每周班次": 6, "定位": "低成本航司"},
            {"航司": "T'Way Air / 德威航空", "代码": "TW", "机型": "Boeing 737 MAX 8", "座位": 189, "每周班次": 6, "定位": "低成本航司"},
        ],
        "sources": [
            {"name": "FlightsFrom CJU-SIN", "url": "https://www.flightsfrom.com/CJU-SIN"},
            {"name": "FlightRoutes CJU-SIN", "url": "https://www.flightroutes.com/CJU-SIN"},
            {"name": "Wego CJU-SIN schedules", "url": "https://www.wego.com.sg/schedules/cju/sin/flight-schedules-from-jeju-to-singapura"},
        ],
    },
    "TYO-SHA": {
        "route": "TYO-SHA",
        "sourceNote": "TYO 是东京城市代码；公开航班网站显示东京到上海虹桥直飞主要为 HND-SHA，FlightsFrom 显示上海航空、JAL、东航、ANA各约每日1班；Directflights 显示约28班/周。",
        "marketRoundTripUsd": 260,
        "airlines": [
            {"航司": "Shanghai Airlines / 上海航空", "代码": "FM", "机型": "Boeing 737", "座位": 170, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "JAL / 日本航空", "代码": "JL", "机型": "Boeing 787 / Boeing 737", "座位": 180, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "China Eastern Airlines / 中国东方航空", "代码": "MU", "机型": "Airbus A330 / Airbus A320", "座位": 240, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "ANA / 全日空", "代码": "NH", "机型": "Boeing 787-8", "座位": 240, "每周班次": 7, "定位": "全服务航司"},
        ],
        "sources": [
            {"name": "FlightsFrom HND-SHA", "url": "https://www.flightsfrom.com/HND-SHA"},
            {"name": "Directflights HND-SHA", "url": "https://www.directflights.com/HND-SHA"},
            {"name": "Wego TYO-SHA schedules", "url": "https://www.wego.com/schedules/tyo/sha/flight-schedules-from-tokyo-to-shanghai"},
        ],
    },
    "HND-SHA": {
        "route": "HND-SHA",
        "sourceNote": "公开航班网站显示 HND-SHA 由上海航空、JAL、东航、ANA直飞，每家约每日1班，合计约28班/周。",
        "marketRoundTripUsd": 260,
        "airlines": [
            {"航司": "Shanghai Airlines / 上海航空", "代码": "FM", "机型": "Boeing 737", "座位": 170, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "JAL / 日本航空", "代码": "JL", "机型": "Boeing 787 / Boeing 737", "座位": 180, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "China Eastern Airlines / 中国东方航空", "代码": "MU", "机型": "Airbus A330 / Airbus A320", "座位": 240, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "ANA / 全日空", "代码": "NH", "机型": "Boeing 787-8", "座位": 240, "每周班次": 7, "定位": "全服务航司"},
        ],
        "sources": [
            {"name": "FlightsFrom HND-SHA", "url": "https://www.flightsfrom.com/HND-SHA"},
            {"name": "Directflights HND-SHA", "url": "https://www.directflights.com/HND-SHA"},
        ],
    },
    "BJS-SIN": {
        "route": "BJS-SIN",
        "sourceNote": "BJS 是北京城市代码，公开航班供给按 PEK-SIN 与 PKX-SIN 合并估算。FlightsFrom 显示 PEK-SIN 由国航和新航执飞，各约每日3班；PKX-SIN 由东航和新航执飞，新航约每日1班，东航2026-05-29起每日1班。Directflights 显示 PKX-SIN 约9班/周、PEK-SIN约31班/周，实际以查询日期为准。",
        "marketRoundTripUsd": 300,
        "airlines": [
            {"航司": "Air China / 中国国际航空", "代码": "CA", "机型": "Boeing 787-9", "座位": 293, "每周班次": 21, "定位": "全服务航司"},
            {"航司": "Singapore Airlines / 新加坡航空", "代码": "SQ", "机型": "Airbus A350 / Boeing 777-300ER / Boeing 787", "座位": 300, "每周班次": 28, "定位": "全服务航司"},
            {"航司": "China Eastern Airlines / 中国东方航空", "代码": "MU", "机型": "Boeing 737 MAX 8", "座位": 176, "每周班次": 7, "定位": "全服务航司"},
        ],
        "sources": [
            {"name": "FlightsFrom PEK-SIN", "url": "https://www.flightsfrom.com/PEK-SIN"},
            {"name": "FlightsFrom PKX-SIN", "url": "https://www.flightsfrom.com/PKX-SIN"},
            {"name": "Directflights PKX-SIN", "url": "https://www.directflights.com/PKX-SIN"},
            {"name": "Wego BJS-SIN schedules", "url": "https://www.wego.com/schedules/bjs/sin/flight-schedules-from-beijing-to-singapour"},
        ],
    },
    "PEK-SIN": {
        "route": "PEK-SIN",
        "sourceNote": "FlightsFrom 显示 PEK-SIN 由国航和新航直飞，各约每日3班；Wego 也列出新航A359/B77W/B787与国航B789等执飞机型。",
        "marketRoundTripUsd": 300,
        "airlines": [
            {"航司": "Air China / 中国国际航空", "代码": "CA", "机型": "Boeing 787-9", "座位": 293, "每周班次": 21, "定位": "全服务航司"},
            {"航司": "Singapore Airlines / 新加坡航空", "代码": "SQ", "机型": "Airbus A350 / Boeing 777-300ER / Boeing 787", "座位": 300, "每周班次": 21, "定位": "全服务航司"},
        ],
        "sources": [
            {"name": "FlightsFrom PEK-SIN", "url": "https://www.flightsfrom.com/PEK-SIN"},
            {"name": "Wego BJS-SIN schedules", "url": "https://www.wego.com/schedules/bjs/sin/flight-schedules-from-beijing-to-singapour"},
        ],
    },
    "PKX-SIN": {
        "route": "PKX-SIN",
        "sourceNote": "FlightsFrom 显示 PKX-SIN 由东航和新航直飞，新航约每日1班，东航2026-05-29起每日1班；Directflights 显示当前约9班/周。",
        "marketRoundTripUsd": 300,
        "airlines": [
            {"航司": "Singapore Airlines / 新加坡航空", "代码": "SQ", "机型": "Boeing 787 / Airbus A350", "座位": 280, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "China Eastern Airlines / 中国东方航空", "代码": "MU", "机型": "Boeing 737 MAX 8", "座位": 176, "每周班次": 7, "定位": "全服务航司"},
        ],
        "sources": [
            {"name": "FlightsFrom PKX-SIN", "url": "https://www.flightsfrom.com/PKX-SIN"},
            {"name": "Directflights PKX-SIN", "url": "https://www.directflights.com/PKX-SIN"},
        ],
    },
    "SHA-BKK": {
        "route": "SHA-BKK",
        "sourceNote": "公开航班网站显示 SHA-BKK 暂无直飞；上海到曼谷直飞主要使用 PVG-BKK。建议确认是否应改查 PVG-BKK。",
        "marketRoundTripUsd": 230,
        "airlines": [],
        "sources": [
            {"name": "FlightConnections SHA-BKK", "url": "https://www.flightconnections.com/flights-from-sha-to-bkk"},
            {"name": "FlightRoutes SHA-BKK", "url": "https://www.flightroutes.com/SHA-BKK"},
        ],
    },
    "PVG-BKK": {
        "route": "PVG-BKK",
        "sourceNote": "公开航班网站显示 PVG-BKK 为上海到曼谷主力直飞航线，FlightsFrom 显示7家航司、约84班/周，Directflights 显示约98班/周。",
        "marketRoundTripUsd": 230,
        "airlines": [
            {"航司": "Spring Airlines / 春秋航空", "代码": "9C", "机型": "Airbus A320", "座位": 180, "每周班次": 14, "定位": "低成本航司"},
            {"航司": "Air China / 中国国际航空", "代码": "CA", "机型": "Airbus A320/Boeing 737", "座位": 170, "每周班次": 14, "定位": "全服务航司"},
            {"航司": "Shanghai Airlines / 上海航空", "代码": "FM", "机型": "Boeing 737 MAX 8", "座位": 176, "每周班次": 14, "定位": "全服务航司"},
            {"航司": "Juneyao Airlines / 吉祥航空", "代码": "HO", "机型": "Airbus A320", "座位": 180, "每周班次": 14, "定位": "全服务航司"},
            {"航司": "China Eastern Airlines / 中国东方航空", "代码": "MU", "机型": "Airbus A320/Boeing 737", "座位": 170, "每周班次": 14, "定位": "全服务航司"},
            {"航司": "Thai Airways International / 泰国航空", "代码": "TG", "机型": "Airbus A330/Boeing 787", "座位": 290, "每周班次": 7, "定位": "全服务航司"},
            {"航司": "Thai Vietjet Air / 泰国越捷航空", "代码": "VZ", "机型": "Airbus A320", "座位": 180, "每周班次": 7, "定位": "低成本航司"},
        ],
        "sources": [
            {"name": "FlightsFrom PVG-BKK", "url": "https://www.flightsfrom.com/PVG-BKK"},
            {"name": "Directflights PVG-BKK", "url": "https://www.directflights.com/PVG-BKK"},
            {"name": "FlightRoutes PVG-BKK", "url": "https://www.flightroutes.com/PVG-BKK"},
        ],
    },
}


def load_route_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def save_route_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")


def file_status(path):
    if not path.exists():
        return {"exists": False, "size": 0, "updated": ""}
    stat = path.stat()
    return {"exists": True, "size": stat.st_size, "updated": int(stat.st_mtime)}


def load_json_file(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def load_execution_tasks():
    if not EXECUTION_TASK_FILE.exists():
        return []
    try:
        data = json.loads(EXECUTION_TASK_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_execution_tasks(rows):
    EXECUTION_TASK_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")


def load_automation_jobs():
    data = load_json_file(AUTOMATION_JOBS_FILE, {"jobs": [], "updated": 0})
    if not isinstance(data, dict):
        data = {"jobs": [], "updated": 0}
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        jobs = []
    data["jobs"] = jobs
    data.setdefault("updated", 0)
    return data


def save_automation_jobs(data):
    payload = {
        "jobs": data.get("jobs", []) if isinstance(data, dict) else [],
        "updated": now_ts(),
    }
    AUTOMATION_JOBS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return payload


def automation_jobs_payload():
    data = load_automation_jobs()
    return {
        "ok": True,
        "enabled": False,
        "message": "自动跑数与 OTA 比价调价当前仅预留配置口，尚未启用后台执行。",
        "jobs": data.get("jobs", []),
        "updated": file_status(AUTOMATION_JOBS_FILE),
    }


def save_automation_job_config(payload, session, ip=""):
    actor, role = session_actor(session)
    job = payload.get("job", payload)
    if not isinstance(job, dict):
        raise ValueError("自动化预留配置格式不正确")
    allowed = ["任务名称", "平台", "航司", "航线", "舱位", "自动运行", "运行频率", "执行模式", "备注", "关联记录ID"]
    record = {field: str(job.get(field, "")).strip() for field in allowed}
    record["id"] = str(job.get("id") or job.get("关联记录ID") or operation_record_id("automationJobs")).strip()
    record["状态"] = "预留未启用"
    record["最近结果"] = "自动化执行口尚未启用，未跑数、未比价、未调价。"
    record["更新时间"] = now_ts()
    record["更新人"] = actor

    data = load_automation_jobs()
    rows = data.get("jobs", [])
    for index, existing in enumerate(rows):
        if str(existing.get("id", "")) == record["id"]:
            rows[index] = {**existing, **record}
            break
    else:
        rows.insert(0, record)
    data["jobs"] = rows[:500]
    saved = save_automation_jobs(data)
    append_audit_log(actor, role, "保存自动化预留配置", record["id"], "成功", "仅保存配置，不启动定时任务、不调用OTA、不自动调价", ip)
    return {
        "ok": True,
        "enabled": False,
        "message": "自动化预留配置已保存；执行口尚未启用。",
        "record": record,
        "jobs": saved.get("jobs", []),
    }


def automation_run_now_placeholder(payload, session, ip=""):
    actor, role = session_actor(session)
    target = str(payload.get("id") or payload.get("任务名称") or "automation-placeholder").strip()
    append_audit_log(actor, role, "触发自动化预留执行", target, "未启用", "自动化执行口尚未启用，未跑数、未请求OTA、未调价", ip)
    return {
        "ok": False,
        "enabled": False,
        "message": "自动化执行口尚未启用：本次不会跑数、不会调用 OTA、不会自动调价。",
    }


def password_hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def now_ts():
    return int(time.time())


def load_access_control():
    if ACCESS_CONTROL_FILE.exists():
        try:
            data = json.loads(ACCESS_CONTROL_FILE.read_text("utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    if not data.get("adminPasswordHash"):
        data["adminPasswordHash"] = password_hash(DEFAULT_ADMIN_PASSWORD)
        data["passes"] = []
        data["sessions"] = {}
        data["employees"] = []
        save_access_control(data)
    data.setdefault("passes", [])
    data.setdefault("sessions", {})
    data.setdefault("employees", [])
    data.setdefault("roleTemplates", ROLE_TEMPLATES)
    return data


def save_access_control(data):
    ACCESS_CONTROL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def load_audit_logs():
    if not AUDIT_LOG_FILE.exists():
        return []
    try:
        data = json.loads(AUDIT_LOG_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_audit_log(actor, role, action, target="", result="成功", detail="", ip=""):
    row = {
        "时间": now_ts(),
        "账号": actor or "未识别",
        "身份": role or "",
        "动作": action,
        "对象": target or "",
        "结果": result,
        "说明": detail or "",
        "IP": ip or "",
    }
    rows = load_audit_logs()
    rows.append(row)
    AUDIT_LOG_FILE.write_text(json.dumps(rows[-5000:], ensure_ascii=False, indent=2), "utf-8")
    return row


def parse_local_date_ts(value, end_of_day=False):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = time.strptime(value, "%Y-%m-%d")
        base = int(time.mktime(parsed))
        return base + (86399 if end_of_day else 0)
    except Exception:
        return None


def list_audit_logs(actor="", actor_name="", action="", start_date="", end_date="", limit=200):
    actor = str(actor or "").strip().upper()
    actor_name = str(actor_name or "").strip().upper()
    action = str(action or "").strip()
    start_ts = parse_local_date_ts(start_date)
    end_ts = parse_local_date_ts(end_date, True)
    limit = max(20, min(1000, int(number_value(limit, 200))))
    rows = load_audit_logs()
    matched_employee_ids = set()
    if actor_name:
        for employee in load_access_control().get("employees", []):
            employee_name = str(employee.get("name", "")).upper()
            employee_id = str(employee.get("employeeId", "")).upper()
            if actor_name in employee_name or actor_name in employee_id:
                matched_employee_ids.add(employee_id)
    if actor:
        rows = [
            row for row in rows
            if actor in str(row.get("账号", "")).upper()
            or actor in str(row.get("对象", "")).upper()
        ]
    if actor_name:
        rows = [
            row for row in rows
            if actor_name in str(row.get("说明", "")).upper()
            or actor_name in str(row.get("账号", "")).upper()
            or actor_name in str(row.get("对象", "")).upper()
            or str(row.get("账号", "")).upper() in matched_employee_ids
            or str(row.get("对象", "")).upper() in matched_employee_ids
        ]
    if action:
        rows = [row for row in rows if action in str(row.get("动作", ""))]
    if start_ts is not None:
        rows = [row for row in rows if int(row.get("时间", 0) or 0) >= start_ts]
    if end_ts is not None:
        rows = [row for row in rows if int(row.get("时间", 0) or 0) <= end_ts]
    return {"logs": list(reversed(rows[-limit:])), "count": len(rows)}


OPERATION_COLLECTIONS = {
    "stores": {
        "title": "店铺管理",
        "fields": ["店铺名称", "平台", "渠道", "店铺编号", "Office号", "商户号/域名", "用户名", "商户账号", "OTA刷新缓存账号", "状态", "负责人", "备注"],
    },
    "storePullRules": {
        "title": "拉单规则",
        "fields": ["规则名称", "店铺", "平台", "渠道", "订单状态", "拉单频率", "开始时间", "结束时间", "状态", "备注"],
    },
    "storeLogs": {
        "title": "店铺日志",
        "fields": ["店铺", "平台", "日志类型", "操作人", "结果", "详情"],
    },
    "channels": {
        "title": "渠道管理",
        "fields": ["渠道名称", "渠道类型", "结算方式", "状态", "备注"],
    },
    "airlineData": {
        "title": "航司数据",
        "fields": ["状态", "航司", "航班号", "航线", "城市", "出发时间", "到达时间", "舱位", "舱位数", "成人价格", "儿童价格", "成人税", "儿童税", "运价基础", "货币类型", "数据源", "查询人数", "备注"],
    },
    "policyAccounts": {
        "title": "政策账号",
        "fields": ["状态", "平台", "渠道", "店铺名称", "店铺代码", "Office号", "商户号/域名", "用户名", "商户账号", "OTA刷新缓存账号", "负责人", "备注"],
    },
    "banRules": {
        "title": "禁售设置",
        "fields": ["规则名称", "航司", "航线", "舱位", "开始日期", "结束日期", "禁售原因", "状态", "备注"],
    },
    "crawlRules": {
        "title": "抓取规则",
        "fields": ["规则名称", "平台", "航司", "航线", "抓取频率", "价格阈值", "库存阈值", "状态", "备注"],
    },
    "priceAdjustRules": {
        "title": "调价设置",
        "fields": ["规则名称", "平台", "店铺", "航司", "航线", "加价类型", "加价金额", "最低售价", "最高售价", "状态", "备注"],
    },
    "directConnectRules": {
        "title": "直连设置",
        "fields": ["接口名称", "平台", "渠道", "店铺", "接口地址", "认证方式", "状态", "负责人", "备注"],
    },
    "priceCompareTasks": {
        "title": "比价任务",
        "fields": ["任务名称", "平台", "航司", "航线", "出发日期", "舱位", "目标价", "当前价", "差价", "任务状态", "自动运行", "运行频率", "最近运行时间", "下次运行时间", "最近结果", "执行模式", "备注"],
    },
    "fareQueries": {
        "title": "运价查询",
        "fields": ["查询编号", "平台", "航司", "航班号", "航线", "出发日期", "舱位", "查询人数", "最低价", "最高价", "货币类型", "查询状态", "备注"],
    },
    "ticketAccounts": {
        "title": "出票账号",
        "fields": ["账号名称", "渠道", "Office号", "账号状态", "联系人", "备注"],
    },
    "ticketSettings": {
        "title": "出票设置",
        "fields": ["状态", "店铺名称", "设置名称", "航程类型", "优先级", "支付货币", "旅行日期", "旅行适用天数", "排除日期", "政策代码包含", "政策代码排除", "航司", "舱位", "自动支付", "行李不随订单出票", "适用航线", "排除航线", "同舱剩余座位数", "出票渠道", "付款渠道", "出票舱位", "支付利润区间", "修改人", "备注"],
    },
    "ticketChannels": {
        "title": "出票渠道",
        "fields": ["状态", "渠道名称", "平台", "渠道类型", "Office号", "账号/商户", "出票方式", "付款渠道", "优先级", "负责人", "备注"],
    },
    "contacts": {
        "title": "联系人设置",
        "fields": ["姓名", "类型", "手机", "邮箱", "所属渠道", "备注"],
    },
    "policyRules": {
        "title": "政策/规则",
        "fields": ["规则名称", "航司", "航线", "舱位", "日期范围", "规则类型", "规则内容", "状态", "备注"],
    },
    "cutInventory": {
        "title": "切位库存台账",
        "fields": ["航线", "航司", "航班号", "出发日期", "舱位", "PNR", "锁座数", "已售数", "剩余数", "成本价", "计划售价", "库存状态", "采购渠道", "负责人", "政策提示", "备注"],
    },
    "orders": {
        "title": "订单中心",
        "fields": ["订单号", "店铺", "渠道", "航线", "航司", "航班号", "出发日期", "乘机人", "订单金额", "成本", "PNR", "票号", "关联库存ID", "出票账号", "联系人", "订单状态", "处理人", "政策提示", "备注"],
    },
    "ticketTasks": {
        "title": "出票任务",
        "fields": ["任务号", "订单号", "店铺", "渠道", "航线", "航司", "航班号", "PNR", "乘机人", "出票账号", "票号", "出票方式", "出票状态", "异常原因", "处理人", "备注"],
    },
    "ticketOrdersView": {
        "title": "出票订单",
        "fields": ["订单号", "店铺", "渠道", "航线", "航司", "航班号", "乘机人", "PNR", "票号", "订单状态", "出票状态", "处理人", "异常原因"],
        "virtual": True,
    },
    "pendingTicketsView": {
        "title": "待处理",
        "fields": ["任务号", "订单号", "店铺", "渠道", "航线", "航司", "航班号", "PNR", "乘机人", "出票账号", "出票方式", "出票状态", "处理人", "备注"],
        "virtual": True,
    },
    "exceptionTicketsView": {
        "title": "异常单",
        "fields": ["任务号", "订单号", "店铺", "渠道", "航线", "航司", "航班号", "PNR", "乘机人", "出票账号", "出票状态", "处理人", "异常原因"],
        "virtual": True,
    },
    "completedTicketsView": {
        "title": "出票完成",
        "fields": ["任务号", "订单号", "店铺", "渠道", "航线", "航司", "航班号", "PNR", "乘机人", "出票账号", "票号", "出票方式", "出票状态", "处理人"],
        "virtual": True,
    },
    "unclaimedTicketsView": {
        "title": "待认领",
        "fields": ["任务号", "订单号", "店铺", "渠道", "航线", "航司", "航班号", "PNR", "乘机人", "出票状态", "处理人", "备注"],
        "virtual": True,
    },
    "claimPendingView": {
        "title": "认领待处理",
        "fields": ["任务号", "订单号", "店铺", "渠道", "航线", "航司", "航班号", "PNR", "出票账号", "出票状态", "处理人", "认领建议"],
        "virtual": True,
    },
    "flightChanges": {
        "title": "航变管理",
        "fields": ["航变编号", "订单号", "航司", "航班号", "原出发时间", "新出发时间", "影响航线", "处理状态", "处理人", "备注"],
    },
    "ticketConsole": {
        "title": "出票控制台",
        "fields": ["任务号", "订单号", "当前队列", "SLA优先级", "店铺", "渠道", "出票账号", "订单状态", "出票状态", "异常原因", "处理人"],
    },
    "inventoryStatsView": {
        "title": "库存统计",
        "fields": ["航线", "航司", "锁座数", "已售数", "剩余数", "售卖率", "库存状态", "样本数"],
        "virtual": True,
    },
    "teamInventory": {
        "title": "团队库存",
        "fields": ["团队名称", "航线", "航司", "航班号", "出发日期", "舱位", "总库存", "已分配", "剩余", "负责人", "状态", "备注"],
    },
    "refundChangeOrders": {
        "title": "退改订单",
        "fields": ["退改单号", "订单号", "票号", "乘机人", "退改类型", "申请金额", "成本损失", "处理状态", "处理人", "备注"],
    },
    "ticketChecks": {
        "title": "验票管理",
        "fields": ["验票编号", "订单号", "票号", "PNR", "航司", "航班号", "乘机人", "验票状态", "验票人", "备注"],
    },
    "afterSalesCases": {
        "title": "售后工单",
        "fields": ["工单号", "订单号", "店铺", "问题类型", "优先级", "处理状态", "负责人", "联系人", "备注"],
    },
    "paymentReturns": {
        "title": "支付回填",
        "fields": ["流水号", "订单号", "店铺", "渠道", "订单金额", "到账金额", "手续费", "退款金额", "利润", "回填状态", "备注"],
    },
    "interfaceMonitor": {
        "title": "接口监控",
        "fields": ["接口名称", "平台", "接口类型", "最近同步时间", "成功次数", "失败次数", "最后结果", "状态", "负责人", "备注"],
    },
    "interfaceTests": {
        "title": "接口测试",
        "fields": ["接口名称", "平台", "请求方式", "测试地址", "最近测试时间", "响应状态", "耗时", "最后结果", "负责人", "备注"],
    },
    "interfaceOnboarding": {
        "title": "接口对接流程",
        "fields": ["对接编号", "平台", "阶段", "状态", "输入物", "输出物", "验收标准", "完成时间", "负责人", "备注"],
    },
}


def load_operation_center():
    data = load_json_file(OPERATION_CENTER_FILE, {})
    if not isinstance(data, dict):
        data = {}
    for key in OPERATION_COLLECTIONS:
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def save_operation_center(data):
    OPERATION_CENTER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def operation_config(collection):
    if collection not in OPERATION_COLLECTIONS:
        raise ValueError("未知的运营中心功能")
    return OPERATION_COLLECTIONS[collection]


def operation_virtual_rows(collection, data):
    orders = [row for row in data.get("orders", []) if not row.get("_deleted")]
    tasks = [row for row in data.get("ticketTasks", []) if not row.get("_deleted")]
    order_map = {str(row.get("订单号", "")).strip(): row for row in orders if str(row.get("订单号", "")).strip()}

    def task_order(task):
        return order_map.get(str(task.get("订单号", "")).strip(), {})

    def ticket_row(task, extra=None):
        order = task_order(task)
        status = str(task.get("出票状态", "") or order.get("订单状态", "")).strip()
        row = {
            "id": task.get("id") or operation_record_id(collection),
            "任务号": task.get("任务号", ""),
            "订单号": task.get("订单号", ""),
            "店铺": task.get("店铺", "") or order.get("店铺", ""),
            "渠道": task.get("渠道", "") or order.get("渠道", ""),
            "航线": task.get("航线", "") or order.get("航线", ""),
            "航司": task.get("航司", "") or order.get("航司", ""),
            "航班号": task.get("航班号", "") or order.get("航班号", ""),
            "PNR": task.get("PNR", "") or order.get("PNR", ""),
            "乘机人": task.get("乘机人", "") or order.get("乘机人", ""),
            "出票账号": task.get("出票账号", "") or order.get("出票账号", ""),
            "票号": task.get("票号", "") or order.get("票号", ""),
            "出票方式": task.get("出票方式", ""),
            "订单状态": order.get("订单状态", ""),
            "出票状态": status,
            "处理人": task.get("处理人", "") or order.get("处理人", ""),
            "异常原因": task.get("异常原因", "") or ("待补出票账号" if not (task.get("出票账号") or order.get("出票账号")) else ""),
            "备注": task.get("备注", ""),
            "更新时间": task.get("更新时间", "") or order.get("更新时间", ""),
            "更新人": task.get("更新人", "") or order.get("更新人", ""),
        }
        if extra:
            row.update(extra)
        return row

    if collection == "ticketOrdersView":
        return [ticket_row(task) for task in tasks]
    if collection == "pendingTicketsView":
        return [
            ticket_row(task) for task in tasks
            if str(task.get("出票状态", "")).strip() in {"", "自动出票待尝试", "待认领", "待处理", "待出票", "待人工出票", "出票中"}
        ]
    if collection == "exceptionTicketsView":
        rows = []
        for task in tasks:
            text = " ".join(str(task.get(key, "")) for key in ["出票状态", "备注", "异常原因"])
            if any(word in text for word in ["异常", "失败", "错误", "退回"]):
                rows.append(ticket_row(task, {"异常原因": task.get("异常原因", "") or task.get("备注", "") or task.get("出票状态", "")}))
        return rows
    if collection == "completedTicketsView":
        return [ticket_row(task) for task in tasks if "已出票" in str(task.get("出票状态", ""))]
    if collection == "unclaimedTicketsView":
        return [ticket_row(task) for task in tasks if not str(task.get("处理人", "")).strip()]
    if collection == "claimPendingView":
        rows = []
        for task in tasks:
            if str(task.get("处理人", "")).strip() and str(task.get("出票账号", "")).strip():
                continue
            suggestion = "补处理人" if not str(task.get("处理人", "")).strip() else "补出票账号"
            rows.append(ticket_row(task, {"认领建议": suggestion}))
        return rows
    if collection == "inventoryStatsView":
        buckets = {}
        for row in data.get("cutInventory", []):
            if row.get("_deleted"):
                continue
            key = (row.get("航线", ""), row.get("航司", ""))
            bucket = buckets.setdefault(key, {"航线": key[0], "航司": key[1], "锁座数": 0, "已售数": 0, "剩余数": 0, "样本数": 0})
            bucket["锁座数"] += int(number_value(row.get("锁座数"), 0))
            bucket["已售数"] += int(number_value(row.get("已售数"), 0))
            bucket["剩余数"] += int(number_value(row.get("剩余数"), 0))
            bucket["样本数"] += 1
        rows = []
        for index, bucket in enumerate(buckets.values(), 1):
            locked = bucket["锁座数"]
            sold = bucket["已售数"]
            ratio = f"{(sold / locked * 100):.1f}%" if locked else "0.0%"
            status = inventory_status_after_sync(locked, bucket["剩余数"])
            rows.append({
                "id": f"inventory-stats-{index}",
                "航线": bucket["航线"],
                "航司": bucket["航司"],
                "锁座数": str(locked),
                "已售数": str(sold),
                "剩余数": str(bucket["剩余数"]),
                "售卖率": ratio,
                "库存状态": status,
                "样本数": str(bucket["样本数"]),
            })
        return rows
    return []


def operation_collection_payload(collection):
    data = load_operation_center()
    config = operation_config(collection)
    if config.get("virtual"):
        rows = operation_virtual_rows(collection, data)
    else:
        rows = [row for row in data.get(collection, []) if not row.get("_deleted")]
    return {
        "ok": True,
        "collection": collection,
        "title": config["title"],
        "fields": config["fields"],
        "virtual": bool(config.get("virtual")),
        "rows": rows,
        "count": len(rows),
        "updated": file_status(OPERATION_CENTER_FILE),
    }


def operation_record_id(collection):
    return f"OC-{collection}-{now_ts()}-{secrets.token_hex(2)}"


def normalize_operation_record(collection, payload, session):
    config = operation_config(collection)
    if config.get("virtual"):
        raise ValueError("该功能是由底层台账生成的只读视图，请到对应台账修改原始记录")
    actor, _ = session_actor(session)
    record = {"id": str(payload.get("id") or "").strip() or operation_record_id(collection)}
    for field in config["fields"]:
        record[field] = str(payload.get(field, "")).strip()
    if collection == "cutInventory" and not record.get("剩余数"):
        locked = int(number_value(record.get("锁座数"), 0))
        sold = int(number_value(record.get("已售数"), 0))
        if locked or sold:
            record["剩余数"] = str(max(0, locked - sold))
    if collection == "orders" and not record.get("订单状态"):
        record["订单状态"] = "待处理"
    if collection == "priceCompareTasks":
        record["自动运行"] = record.get("自动运行") or "关闭"
        record["运行频率"] = record.get("运行频率") or "1小时"
        record["最近结果"] = record.get("最近结果") or "预留未启用：未跑数、未调用OTA、未自动调价。"
        record["执行模式"] = record.get("执行模式") or "建议待确认"
    if collection == "storeLogs" and not record.get("操作人"):
        record["操作人"] = actor
    if collection == "storeLogs" and not record.get("结果"):
        record["结果"] = "成功"
    if collection in {"orders", "cutInventory"}:
        record["政策提示"] = operation_policy_hint(record)
    record["更新时间"] = now_ts()
    record["更新人"] = actor
    return record


def operation_status_field(row, config):
    for field in ["状态", "账号状态", "任务状态", "查询状态", "库存状态", "订单状态"]:
        if field in config["fields"] or field in row:
            return field
    return ""


def is_enabled_status(value):
    return str(value or "").strip() in {"", "启用", "有效", "生效", "上架", "正常"}


def active_operation_channels(data):
    rows = [row for row in data.get("channels", []) if not row.get("_deleted")]
    active = [
        str(row.get("渠道名称", "")).strip()
        for row in rows
        if str(row.get("渠道名称", "")).strip() and is_enabled_status(row.get("状态"))
    ]
    if active:
        return active
    if rows:
        return []
    return list(OTA_PLATFORMS)


def first_matching_record(rows, field, value, status_field="状态"):
    value = str(value or "").strip()
    for row in rows:
        if row.get("_deleted"):
            continue
        if value and str(row.get(field, "")).strip() != value:
            continue
        if is_enabled_status(row.get(status_field)):
            return row
    return {}


def cascade_channel_status(data, channel_name, enabled, actor, current):
    channel_name = str(channel_name or "").strip()
    if not channel_name:
        return 0
    status = "启用" if enabled else "停用"
    changed = 0
    related_specs = [
        ("stores", ["渠道", "平台"], "状态"),
        ("storePullRules", ["渠道", "平台"], "状态"),
        ("policyAccounts", ["渠道", "平台"], "状态"),
        ("crawlRules", ["平台"], "状态"),
        ("priceAdjustRules", ["平台"], "状态"),
        ("directConnectRules", ["渠道", "平台"], "状态"),
        ("ticketAccounts", ["渠道"], "账号状态"),
        ("ticketSettings", ["出票渠道", "付款渠道", "店铺名称"], "状态"),
        ("ticketChannels", ["渠道名称", "平台"], "状态"),
        ("interfaceMonitor", ["平台"], "状态"),
    ]
    for collection, fields, status_field in related_specs:
        for row in data.get(collection, []):
            if row.get("_deleted"):
                continue
            if not any(str(row.get(field, "")).strip() == channel_name for field in fields):
                continue
            if row.get(status_field) == status:
                continue
            row[status_field] = status
            row["更新时间"] = current
            row["更新人"] = actor
            changed += 1
            if collection == "stores":
                append_store_log(data, row.get("店铺名称", ""), row.get("平台", ""), f"渠道开关联动{status}", actor, "成功", f"渠道 {channel_name}")
    return changed


def set_operation_record_status(collection, record_id, field, enabled, session, ip=""):
    config = operation_config(collection)
    if config.get("virtual"):
        raise ValueError("该功能是由底层台账生成的只读视图，不能直接切换状态")
    record_id = str(record_id or "").strip()
    field = str(field or "").strip()
    if field not in {"状态", "账号状态"}:
        raise ValueError("该字段不支持开关切换")
    data = load_operation_center()
    rows = data.get(collection, [])
    target = None
    for row in rows:
        if str(row.get("id", "")) == record_id:
            target = row
            break
    if not target:
        raise ValueError("未找到要切换状态的记录")
    if field not in target and field not in config.get("fields", []):
        raise ValueError("当前记录没有可切换状态字段")
    actor, role = session_actor(session)
    current = now_ts()
    status = "启用" if bool(enabled) else "停用"
    target[field] = status
    target["更新时间"] = current
    target["更新人"] = actor
    cascaded = 0
    if collection == "channels":
        cascaded = cascade_channel_status(data, target.get("渠道名称", ""), bool(enabled), actor, current)
    if collection == "stores":
        append_store_log(data, target.get("店铺名称", ""), target.get("平台", ""), f"开关{status}", actor, "成功", config["title"])
    save_operation_center(data)
    append_audit_log(actor, role, "切换运营中心开关", record_id, "成功", f"{config['title']} {field}={status}，联动{cascaded}条", ip)
    return {**operation_collection_payload(collection), "record": target, "status": status, "cascaded": cascaded}


def append_store_log(data, store_name, platform, log_type, actor, result="成功", detail=""):
    if "storeLogs" not in data:
        data["storeLogs"] = []
    data["storeLogs"].insert(0, {
        "id": operation_record_id("storeLogs"),
        "店铺": str(store_name or "").strip(),
        "平台": str(platform or "").strip(),
        "日志类型": str(log_type or "").strip(),
        "操作人": str(actor or "").strip(),
        "结果": str(result or "").strip(),
        "详情": str(detail or "").strip(),
        "更新时间": now_ts(),
        "更新人": str(actor or "").strip(),
    })
    data["storeLogs"] = data["storeLogs"][:2000]


def operation_policy_hint(record):
    data = load_operation_center()
    route = str(record.get("航线", "")).strip()
    airline = str(record.get("航司", "")).strip()
    matched = []
    for rule in data.get("policyRules", []):
        status = str(rule.get("状态", "")).strip()
        rule_route = str(rule.get("航线", "")).strip()
        rule_airline = str(rule.get("航司", "")).strip()
        if status and status not in {"启用", "有效", "生效"}:
            continue
        if rule_route and rule_route != route:
            continue
        if rule_airline and rule_airline != airline:
            continue
        if rule_route or rule_airline:
            matched.append(f"{rule.get('规则类型') or '规则'}:{rule.get('规则名称') or rule.get('规则内容') or '未命名'}")
    for rule in data.get("banRules", []):
        status = str(rule.get("状态", "")).strip()
        rule_route = str(rule.get("航线", "")).strip()
        rule_airline = str(rule.get("航司", "")).strip()
        if status and status not in {"启用", "有效", "生效"}:
            continue
        if rule_route and rule_route != route:
            continue
        if rule_airline and rule_airline != airline:
            continue
        if rule_route or rule_airline:
            matched.append(f"禁售:{rule.get('规则名称') or rule.get('禁售原因') or '未命名'}")
    return "；".join(matched[:3])


def upsert_operation_record(collection, payload, session, ip=""):
    row = normalize_operation_record(collection, payload, session)
    data = load_operation_center()
    rows = data.get(collection, [])
    existed = False
    for index, existing in enumerate(rows):
        if str(existing.get("id", "")) == row["id"]:
            rows[index] = {**existing, **row}
            existed = True
            break
    if not existed:
        rows.insert(0, row)
    data[collection] = rows[:2000]
    actor, role = session_actor(session)
    if collection == "stores":
        append_store_log(data, row.get("店铺名称", ""), row.get("平台", ""), "保存店铺", actor, "成功", row.get("备注", ""))
    ticket_task = None
    if collection == "orders" and active_order_for_inventory(row):
        ticket_task = order_to_ticket_task(data, row, actor)
    save_operation_center(data)
    action = "更新运营中心记录" if existed else "新增运营中心记录"
    detail = f"{operation_config(collection)['title']}"
    if ticket_task:
        detail += f"; 出票任务={ticket_task.get('任务号', '')}"
    append_audit_log(actor, role, action, row["id"], "成功", detail, ip)
    if collection == "priceCompareTasks" and any(row.get(field) for field in ["自动运行", "运行频率", "执行模式"]):
        append_audit_log(actor, role, "保存自动化预留配置", row["id"], "成功", "比价任务自动化字段仅预留，不启动定时任务、不调用OTA、不自动调价", ip)
    return {**operation_collection_payload(collection), "record": row, "ticketTask": ticket_task}


def delete_operation_record(collection, record_id, session, ip=""):
    config = operation_config(collection)
    if config.get("virtual"):
        raise ValueError("该功能是由底层台账生成的只读视图，不能直接删除")
    record_id = str(record_id or "").strip()
    if not record_id:
        raise ValueError("缺少记录ID")
    data = load_operation_center()
    deleted_rows = [row for row in data.get(collection, []) if str(row.get("id", "")) == record_id]
    before = len(data.get(collection, []))
    data[collection] = [row for row in data.get(collection, []) if str(row.get("id", "")) != record_id]
    if len(data[collection]) == before:
        raise ValueError("未找到要删除的记录")
    actor, role = session_actor(session)
    if collection == "stores" and deleted_rows:
        row = deleted_rows[0]
        append_store_log(data, row.get("店铺名称", ""), row.get("平台", ""), "删除店铺", actor, "成功", config["title"])
    save_operation_center(data)
    append_audit_log(actor, role, "删除运营中心记录", record_id, "成功", config["title"], ip)
    return operation_collection_payload(collection)


def operation_bulk_action(collection, action, ids, session, ip=""):
    config = operation_config(collection)
    if config.get("virtual"):
        raise ValueError("该功能是由底层台账生成的只读视图，不能批量处理")
    ids = {str(item).strip() for item in (ids or []) if str(item).strip()}
    if action not in {"enable", "disable", "copy", "delete"}:
        raise ValueError("未知的批量操作")
    if not ids:
        raise ValueError("请先选择要处理的记录")
    data = load_operation_center()
    rows = data.get(collection, [])
    actor, role = session_actor(session)
    current = now_ts()
    changed = 0
    created = []
    kept = []
    for row in rows:
        row_id = str(row.get("id", ""))
        if row_id not in ids:
            kept.append(row)
            continue
        if action == "delete":
            changed += 1
            if collection == "stores":
                append_store_log(data, row.get("店铺名称", ""), row.get("平台", ""), "批量删除店铺", actor, "成功", config["title"])
            continue
        updated = dict(row)
        status_field = operation_status_field(updated, config)
        if action == "enable":
            if status_field:
                updated[status_field] = "启用"
            if collection == "channels":
                changed += cascade_channel_status(data, updated.get("渠道名称", ""), True, actor, current)
            updated["更新时间"] = current
            updated["更新人"] = actor
            changed += 1
            kept.append(updated)
        elif action == "disable":
            if status_field:
                updated[status_field] = "停用"
            if collection == "channels":
                changed += cascade_channel_status(data, updated.get("渠道名称", ""), False, actor, current)
            updated["更新时间"] = current
            updated["更新人"] = actor
            changed += 1
            kept.append(updated)
        elif action == "copy":
            copied = dict(updated)
            copied["id"] = operation_record_id(collection)
            copied["更新时间"] = current
            copied["更新人"] = actor
            copied["备注"] = (copied.get("备注", "") + " 复制生成").strip()
            created.append(copied)
            changed += 1
            kept.append(updated)
    data[collection] = (created + kept)[:2000]
    if collection == "stores" and action in {"enable", "disable", "copy"}:
        for row in created:
            append_store_log(data, row.get("店铺名称", ""), row.get("平台", ""), "复制店铺", actor, "成功", row.get("备注", ""))
    save_operation_center(data)
    action_name = {"enable": "批量启用运营中心记录", "disable": "批量停用运营中心记录", "copy": "批量复制运营中心记录", "delete": "批量删除运营中心记录"}[action]
    append_audit_log(actor, role, action_name, collection, "成功", f"{config['title']} {changed}条", ip)
    return {**operation_collection_payload(collection), "changed": changed, "bulkAction": action}


def clean_import_cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if pd.isna(value):
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat"} else text


def normalize_import_header(value):
    return re.sub(r"[\s　_\-/（）()【】\\[\\]:：]+", "", str(value or "").strip().lower())


def import_value(source, aliases):
    normalized = {normalize_import_header(key): value for key, value in source.items()}
    for alias in aliases:
        key = normalize_import_header(alias)
        if key in normalized:
            return clean_import_cell(normalized[key])
    return ""


def import_cut_inventory_excel(file_path, filename, session, ip=""):
    actor, role = session_actor(session)
    try:
        frame = pd.read_excel(file_path, dtype=object)
    except Exception as exc:
        raise ValueError(f"无法读取库存Excel：{exc}") from exc
    if frame.empty:
        raise ValueError("库存Excel没有可导入数据")

    aliases = {
        "航线": ["航线", "路线", "起飞-到达", "起飞到达", "OD", "route"],
        "航司": ["航司", "航空公司", "承运人", "航司代码", "airline"],
        "航班号": ["航班号", "航班", "班号", "flightNo", "flight_no"],
        "出发日期": ["出发日期", "起飞日期", "航班日期", "日期", "departureDate", "flightDate"],
        "舱位": ["舱位", "舱等", "cabin"],
        "PNR": ["PNR", "pnr", "编码", "订座编码"],
        "锁座数": ["锁座数", "锁定位", "座位数", "切位数", "库存", "总库存", "allotment"],
        "已售数": ["已售数", "已售", "已出票", "sold"],
        "剩余数": ["剩余数", "剩余", "可售", "余位", "available"],
        "成本价": ["成本价", "成本", "底价", "采购价", "结算价", "cost"],
        "计划售价": ["计划售价", "售价", "销售价", "建议售价", "投放价", "price"],
        "库存状态": ["库存状态", "状态", "上架状态", "status"],
        "采购渠道": ["采购渠道", "渠道", "供应商", "供给方", "source"],
        "负责人": ["负责人", "操作人", "维护人", "owner"],
        "政策提示": ["政策提示", "政策", "规则提示"],
        "备注": ["备注", "说明", "note"],
    }

    data = load_operation_center()
    imported = []
    errors = []
    current = now_ts()
    for row_index, (_, source_row) in enumerate(frame.iterrows(), 2):
        source = source_row.to_dict()
        if not any(clean_import_cell(value) for value in source.values()):
            continue
        record = {}
        for field, field_aliases in aliases.items():
            record[field] = import_value(source, field_aliases)
        record["航线"] = normalize_route(record.get("航线", ""))
        locked = int(number_value(record.get("锁座数"), 0))
        sold = int(number_value(record.get("已售数"), 0))
        if not record["航线"] or record["航线"] == "-":
            errors.append({"row": row_index, "reason": "缺少航线"})
            continue
        if locked <= 0:
            errors.append({"row": row_index, "reason": "缺少有效锁座数"})
            continue
        if not record.get("剩余数"):
            record["剩余数"] = str(max(0, locked - sold))
        if not record.get("库存状态"):
            record["库存状态"] = inventory_status_after_sync(locked, int(number_value(record.get("剩余数"), 0)))
        record["id"] = operation_record_id("cutInventory")
        record["更新时间"] = current
        record["更新人"] = actor
        if not record.get("负责人"):
            record["负责人"] = actor
        if record.get("政策提示") == "":
            record["政策提示"] = operation_policy_hint(record)
        imported.append(record)

    if not imported:
        detail = "；".join(f"第{item['row']}行：{item['reason']}" for item in errors[:5]) or "没有有效库存行"
        raise ValueError(f"没有导入有效库存。{detail}")

    data["cutInventory"] = (imported + data.get("cutInventory", []))[:2000]
    save_operation_center(data)
    append_audit_log(actor, role, "批量导入切位库存", "cutInventory", "成功", f"{filename}; 导入{len(imported)}条; 跳过{len(errors)}条", ip)
    return {**operation_collection_payload("cutInventory"), "imported": len(imported), "errors": errors[:50], "errorCount": len(errors), "filename": filename}


def operation_export_csv(collection):
    payload = operation_collection_payload(collection)
    output = io.StringIO()
    fields = ["id"] + payload["fields"] + ["更新时间", "更新人"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in payload["rows"]:
        writer.writerow({field: row.get(field, "") for field in fields})
    return output.getvalue()


def excel_column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xlsx_cell_xml(row_index, col_index, value, style=""):
    ref = f"{excel_column_name(col_index)}{row_index}"
    style_attr = f' s="{style}"' if style else ""
    if value is None:
        value = ""
    text = str(value)
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{html.escape(text)}</t></is></c>'


def build_xlsx_workbook(title, fields, rows):
    clean_title = str(title or "导出表格").strip() or "导出表格"
    sheet_rows = [fields] + rows
    col_widths = []
    for col_index, field in enumerate(fields):
        max_len = len(str(field))
        for row in rows[:200]:
            max_len = max(max_len, len(str(row[col_index] if col_index < len(row) else "")))
        col_widths.append(min(max(max_len + 2, 10), 38))
    cols_xml = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(col_widths, 1)
    )
    rows_xml = []
    for row_index, row in enumerate(sheet_rows, 1):
        style = "1" if row_index == 1 else ""
        cells = "".join(xlsx_cell_xml(row_index, col_index, value, style) for col_index, value in enumerate(row, 1))
        rows_xml.append(f'<row r="{row_index}">{cells}</row>')

    sheet_name = re.sub(r"[\[\]\*\?/\\:]", "", clean_title)[:31] or "导出表格"
    filename = f"{clean_title}-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>""")
        workbook.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""")
        workbook.writestr("xl/workbook.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{html.escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>""")
        workbook.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>""")
        workbook.writestr("xl/styles.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>""")
        workbook.writestr("xl/worksheets/sheet1.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{cols_xml}</cols><sheetData>{''.join(rows_xml)}</sheetData><autoFilter ref="A1:{excel_column_name(len(fields))}{max(1, len(sheet_rows))}"/></worksheet>""")
    return output.getvalue(), filename, len(rows)


def operation_export_xlsx(collection):
    payload = operation_collection_payload(collection)
    fields = ["id"] + payload["fields"] + ["更新时间", "更新人"]
    rows = []
    for row in payload["rows"]:
        export_row = []
        for field in fields:
            value = row.get(field, "")
            if field == "更新时间" and value:
                try:
                    value = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
                except Exception:
                    value = str(value)
            export_row.append(value)
        rows.append(export_row)
    return build_xlsx_workbook(payload["title"], fields, rows)

    sheet_rows = [fields] + rows
    col_widths = []
    for col_index, field in enumerate(fields):
        max_len = len(str(field))
        for row in rows[:200]:
            max_len = max(max_len, len(str(row[col_index] or "")))
        col_widths.append(min(max(max_len + 2, 10), 38))
    cols_xml = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(col_widths, 1)
    )
    rows_xml = []
    for row_index, row in enumerate(sheet_rows, 1):
        style = "1" if row_index == 1 else ""
        cells = "".join(xlsx_cell_xml(row_index, col_index, value, style) for col_index, value in enumerate(row, 1))
        rows_xml.append(f'<row r="{row_index}">{cells}</row>')

    sheet_name = re.sub(r"[\[\]\*\?/\\:]", "", payload["title"])[:31] or "运营中心"
    filename = f"{payload['title']}-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>""")
        workbook.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""")
        workbook.writestr("xl/workbook.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{html.escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>""")
        workbook.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>""")
        workbook.writestr("xl/styles.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>""")
        workbook.writestr("xl/worksheets/sheet1.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols>{cols_xml}</cols><sheetData>{''.join(rows_xml)}</sheetData><autoFilter ref="A1:{excel_column_name(len(fields))}{max(1, len(sheet_rows))}"/><freezePanes/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews></worksheet>""")
    return output.getvalue(), filename, len(rows)


def active_order_for_inventory(order):
    status = str(order.get("订单状态", "")).strip()
    return not any(word in status for word in ["取消", "退款", "作废", "关闭"])


def find_ticket_task(data, order_no):
    target = str(order_no or "").strip()
    if not target:
        return None
    return next((row for row in data.get("ticketTasks", []) if str(row.get("订单号", "")).strip() == target), None)


def order_to_ticket_task(data, order, actor="系统"):
    order_no = str(order.get("订单号", "")).strip()
    if not order_no or not active_order_for_inventory(order):
        return None
    current = now_ts()
    existing = find_ticket_task(data, order_no)
    row = existing or {
        "id": operation_record_id("ticketTasks"),
        "任务号": f"TK-{current}-{secrets.token_hex(2).upper()}",
        "出票状态": "自动出票待尝试",
        "出票方式": "自动优先",
        "异常原因": "",
        "备注": "订单收单后自动进入出票处理链路。",
    }
    row.update({
        "订单号": order_no,
        "店铺": order.get("店铺", ""),
        "渠道": order.get("渠道", ""),
        "航线": order.get("航线", ""),
        "航司": order.get("航司", ""),
        "航班号": order.get("航班号", ""),
        "PNR": order.get("PNR", "") or row.get("PNR", ""),
        "乘机人": order.get("乘机人", ""),
        "出票账号": order.get("出票账号", "") or row.get("出票账号", ""),
        "票号": order.get("票号", "") or row.get("票号", ""),
        "处理人": order.get("处理人", "") or row.get("处理人", "") or actor,
        "更新时间": current,
        "更新人": actor,
    })
    if row.get("票号"):
        row["出票状态"] = "已出票"
        row["出票方式"] = row.get("出票方式") or "人工出票"
    if existing:
        existing.update(row)
        return existing
    data.setdefault("ticketTasks", []).insert(0, row)
    return row


def has_auto_ticketing_channel(data, order):
    channel = str(order.get("渠道", "")).strip()
    rows = [row for row in data.get("ticketChannels", []) if not row.get("_deleted")]
    for row in rows:
        status = str(row.get("状态", "")).strip()
        if status not in {"启用", "有效", "生效"}:
            continue
        row_channel = str(row.get("渠道名称", "")).strip()
        row_platform = str(row.get("平台", "")).strip()
        if channel and row_channel not in {"", channel} and row_platform not in {"", channel}:
            continue
        method = str(row.get("出票方式", "")).upper()
        if any(key in method for key in ["API", "B2B", "官网", "自动", "虚拟"]):
            return row
    return None


def process_ticket_task(task_id, mode, payload, session, ip=""):
    data = load_operation_center()
    actor, role = session_actor(session)
    task = next((row for row in data.get("ticketTasks", []) if str(row.get("id", "")) == str(task_id)), None)
    if not task:
        raise ValueError("未找到出票任务")
    order_no = str(task.get("订单号", "")).strip()
    order = next((row for row in data.get("orders", []) if str(row.get("订单号", "")).strip() == order_no), None)
    if not order:
        raise ValueError("出票任务没有匹配订单")
    current = now_ts()
    mode = str(mode or "").strip()
    if mode == "claim":
        task["处理人"] = actor
        if str(task.get("出票状态", "")).strip() in {"", "待认领"}:
            task["出票状态"] = "待人工出票"
        task["备注"] = f"{task.get('备注', '')}；{actor}认领处理".strip("；")
        task["更新时间"] = current
        task["更新人"] = actor
        order["处理人"] = actor
        if str(order.get("订单状态", "")).strip() in {"", "已下单", "待认领"}:
            order["订单状态"] = "待处理"
        order["更新时间"] = current
        order["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, "认领出票任务", order_no, "成功", task.get("任务号", ""), ip)
        return {"ok": True, "task": task, "order": order, "mode": "claimed"}
    if mode == "release":
        task["处理人"] = ""
        task["出票状态"] = "待认领"
        task["备注"] = f"{task.get('备注', '')}；退回待认领".strip("；")
        task["更新时间"] = current
        task["更新人"] = actor
        order["处理人"] = ""
        if str(order.get("订单状态", "")).strip() not in {"已出票", "已取消"}:
            order["订单状态"] = "待认领"
        order["更新时间"] = current
        order["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, "退回待认领", order_no, "成功", task.get("任务号", ""), ip)
        return {"ok": True, "task": task, "order": order, "mode": "released"}
    if mode == "manual-required":
        ticket_channel = str(payload.get("ticketChannel") or payload.get("出票渠道") or "").strip()
        task["处理人"] = actor
        task["出票方式"] = f"人工出票-{ticket_channel}" if ticket_channel else "人工出票"
        task["出票状态"] = "待人工出票"
        task["异常原因"] = str(payload.get("reason") or task.get("异常原因") or "运营转人工出票").strip()
        task["更新时间"] = current
        task["更新人"] = actor
        order["处理人"] = actor
        if str(order.get("订单状态", "")).strip() not in {"已出票", "已取消"}:
            order["订单状态"] = "待人工出票"
        order["更新时间"] = current
        order["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, "转人工出票", order_no, "成功", task["异常原因"], ip)
        return {"ok": True, "task": task, "order": order, "mode": "manual_required"}
    if mode == "exception":
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise ValueError("标记异常必须填写异常原因")
        task["处理人"] = actor
        task["出票状态"] = "出票失败"
        task["异常原因"] = reason
        task["备注"] = f"{task.get('备注', '')}；异常：{reason}".strip("；")
        task["更新时间"] = current
        task["更新人"] = actor
        order["处理人"] = actor
        if str(order.get("订单状态", "")).strip() not in {"已出票", "已取消"}:
            order["订单状态"] = "出票异常"
        order["备注"] = f"{order.get('备注', '')}；出票异常：{reason}".strip("；")
        order["更新时间"] = current
        order["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, "标记出票异常", order_no, "成功", reason, ip)
        return {"ok": True, "task": task, "order": order, "mode": "exception"}
    if mode == "auto":
        channel_row = has_auto_ticketing_channel(data, order)
        if not channel_row:
            task["出票方式"] = "自动出票失败转人工"
            task["出票状态"] = "待人工出票"
            task["异常原因"] = "当前渠道未配置可用 B2B/API/官网出票接口，已转人工处理。"
            task["处理人"] = actor
            task["更新时间"] = current
            task["更新人"] = actor
            save_operation_center(data)
            append_audit_log(actor, role, "自动出票尝试", order_no, "转人工", task["异常原因"], ip)
            return {"ok": True, "task": task, "order": order, "mode": "manual_required"}
        method = str(channel_row.get("出票方式", ""))
        is_virtual = "虚拟" in method or "模拟" in method
        task["出票方式"] = f"{'虚拟' if is_virtual else '自动'}出票-{channel_row.get('渠道名称') or channel_row.get('平台') or '渠道'}"
        if is_virtual:
            generated_pnr = task.get("PNR") or order.get("PNR") or f"PNR{secrets.token_hex(3).upper()}"
            generated_ticket = task.get("票号") or order.get("票号") or f"VT{int(time.time())}{secrets.token_hex(2).upper()}"
            task["PNR"] = generated_pnr
            task["票号"] = generated_ticket
            task["出票账号"] = task.get("出票账号") or channel_row.get("账号/商户", "") or channel_row.get("Office号", "") or "虚拟B2B"
            task["出票状态"] = "已出票"
            task["异常原因"] = ""
            order["PNR"] = generated_pnr
            order["票号"] = generated_ticket
            order["出票账号"] = task["出票账号"]
            order["订单状态"] = "已出票"
            order["处理人"] = actor
            order["更新时间"] = current
            order["更新人"] = actor
            channel_sync = sync_ticket_status_to_channel(order, task, "ticketed")
            task["备注"] = f"{task.get('备注', '')}；虚拟出票完成，已同步渠道前台".strip("；")
            task["处理人"] = actor
            task["更新时间"] = current
            task["更新人"] = actor
            save_operation_center(data)
            append_audit_log(actor, role, "虚拟自动出票", order_no, "成功", f"ticket={generated_ticket}; channelSync={channel_sync.get('ok')}", ip)
            return {"ok": True, "task": task, "order": order, "mode": "auto_complete", "channelSync": channel_sync}
        task["出票状态"] = "出票中"
        task["异常原因"] = "自动出票接口已选择，等待真实出票回执。"
        task["处理人"] = actor
        task["更新时间"] = current
        task["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, "自动出票尝试", order_no, "出票中", task["出票方式"], ip)
        return {"ok": True, "task": task, "order": order, "mode": "auto_pending"}
    if mode == "manual-complete":
        pnr = str(payload.get("pnr") or payload.get("PNR") or task.get("PNR") or order.get("PNR") or "").strip()
        ticket_no = str(payload.get("ticketNo") or payload.get("票号") or task.get("票号") or order.get("票号") or "").strip()
        account = str(payload.get("ticketAccount") or payload.get("出票账号") or task.get("出票账号") or order.get("出票账号") or "").strip()
        ticket_channel = str(payload.get("ticketChannel") or payload.get("出票渠道") or "").strip()
        if not pnr and not ticket_no:
            raise ValueError("人工出票完成至少需要填写 PNR 或票号")
        task["PNR"] = pnr
        task["票号"] = ticket_no
        task["出票账号"] = account
        task["出票方式"] = f"人工出票-{ticket_channel}" if ticket_channel else "人工出票"
        task["出票状态"] = "已出票"
        task["异常原因"] = ""
        task["处理人"] = actor
        task["更新时间"] = current
        task["更新人"] = actor
        order["PNR"] = pnr
        order["票号"] = ticket_no
        order["出票账号"] = account
        order["订单状态"] = "已出票"
        order["处理人"] = actor
        order["备注"] = f"{order.get('备注', '')}；人工出票完成".strip("；")
        order["更新时间"] = current
        order["更新人"] = actor
        channel_sync = sync_ticket_status_to_channel(order, task, "ticketed")
        save_operation_center(data)
        append_audit_log(actor, role, "人工出票完成", order_no, "成功", f"PNR={pnr}; ticket={ticket_no}; channelSync={channel_sync.get('ok')}", ip)
        return {"ok": True, "task": task, "order": order, "mode": "manual_complete", "channelSync": channel_sync}
    raise ValueError("未知的出票处理动作")


def sync_ticket_status_to_channel(order, task, status):
    channel = str(order.get("渠道", "")).strip()
    if channel != "Mock OTA":
        return {"ok": False, "skipped": True, "reason": "当前渠道暂未配置出票状态同步接口"}
    order_id = str(order.get("订单号", "")).strip()
    trace_id = mock_ota_trace_id()
    payload = {
        "order_id": order_id,
        "status": "已出票" if status == "ticketed" else status,
        "pnr": task.get("PNR", ""),
        "ticket_no": task.get("票号", ""),
        "ticket_account": task.get("出票账号", ""),
        "trace_id": trace_id,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{MOCK_OTA_BASE_URL}/api/orders/status",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Mock-OTA-Token": MOCK_OTA_TOKEN,
            "X-Trace-Id": trace_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read().decode("utf-8") or "{}")
        return {"ok": True, "channel": channel, "result": result, "trace_id": trace_id}
    except Exception as exc:
        return {"ok": False, "channel": channel, "error": str(exc), "trace_id": trace_id}


def process_post_ticket_record(collection, record_id, mode, payload, session, ip=""):
    if collection not in {"ticketChecks", "paymentReturns"}:
        raise ValueError("当前功能暂不支持该处理动作")
    data = load_operation_center()
    actor, role = session_actor(session)
    record = next((row for row in data.get(collection, []) if str(row.get("id", "")) == str(record_id)), None)
    if not record:
        raise ValueError("未找到要处理的记录")
    order_no = str(record.get("订单号", "")).strip()
    order = next((row for row in data.get("orders", []) if str(row.get("订单号", "")).strip() == order_no), None)
    current = now_ts()
    mode = str(mode or "").strip()

    if collection == "ticketChecks":
        if mode == "verify-pass":
            record["验票状态"] = "已验票"
            record["验票人"] = actor
            record["备注"] = f"{record.get('备注', '')}；验票通过".strip("；")
            action_name = "验票通过"
            result = "成功"
        elif mode == "verify-fail":
            reason = str(payload.get("reason") or "票号/PNR核验异常").strip()
            record["验票状态"] = "验票失败"
            record["验票人"] = actor
            record["备注"] = f"{record.get('备注', '')}；验票失败：{reason}".strip("；")
            if order and str(order.get("订单状态", "")).strip() == "已出票":
                order["订单状态"] = "验票异常"
                order["备注"] = f"{order.get('备注', '')}；验票异常：{reason}".strip("；")
                order["更新时间"] = current
                order["更新人"] = actor
            action_name = "验票失败"
            result = "异常"
        else:
            raise ValueError("未知的验票处理动作")
        record["更新时间"] = current
        record["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, action_name, order_no or record_id, result, record.get("备注", ""), ip)
        return {"ok": True, "record": record, "order": order, "mode": mode, **operation_collection_payload(collection)}

    if collection == "paymentReturns":
        if mode == "payment-confirm":
            order_amount = number_value(record.get("订单金额") or (order or {}).get("订单金额"), 0)
            cost = number_value((order or {}).get("成本"), 0)
            paid = number_value(payload.get("paidAmount") or record.get("到账金额") or order_amount, 0)
            fee = number_value(payload.get("fee") or record.get("手续费"), 0)
            refund = number_value(record.get("退款金额"), 0)
            record["到账金额"] = str(round(paid, 2))
            record["手续费"] = str(round(fee, 2))
            record["利润"] = str(round(paid - cost - fee - refund, 2))
            record["回填状态"] = "已回填"
            record["备注"] = f"{record.get('备注', '')}；到账确认".strip("；")
            action_name = "支付到账确认"
        elif mode == "refund-confirm":
            refund = number_value(payload.get("refundAmount") or record.get("退款金额"), 0)
            fee = number_value(record.get("手续费"), 0)
            paid = number_value(record.get("到账金额"), 0)
            cost = number_value((order or {}).get("成本"), 0)
            reason = str(payload.get("reason") or "退款回填").strip()
            record["退款金额"] = str(round(refund, 2))
            record["利润"] = str(round(paid - cost - fee - refund, 2))
            record["回填状态"] = "已退款回填"
            record["备注"] = f"{record.get('备注', '')}；{reason}".strip("；")
            if order:
                order["备注"] = f"{order.get('备注', '')}；退款回填：{round(refund, 2)}".strip("；")
                order["更新时间"] = current
                order["更新人"] = actor
            action_name = "退款回填确认"
        else:
            raise ValueError("未知的支付回填动作")
        record["更新时间"] = current
        record["更新人"] = actor
        save_operation_center(data)
        append_audit_log(actor, role, action_name, order_no or record_id, "成功", record.get("备注", ""), ip)
        return {"ok": True, "record": record, "order": order, "mode": mode, **operation_collection_payload(collection)}

    raise ValueError("未知的处理动作")


def inventory_status_after_sync(locked, remaining):
    if locked > 0 and remaining <= 0:
        return "已售罄"
    if locked > 0 and remaining <= max(1, math.ceil(locked * 0.2)):
        return "低库存"
    return "销售中"


def sync_orders_to_inventory(session, ip=""):
    data = load_operation_center()
    order_counts = {}
    for order in data.get("orders", []):
        inventory_id = str(order.get("关联库存ID", "")).strip()
        if inventory_id and active_order_for_inventory(order):
            order_counts[inventory_id] = order_counts.get(inventory_id, 0) + 1

    actor, role = session_actor(session)
    synced_rows = []
    for row in data.get("cutInventory", []):
        inventory_id = str(row.get("id", "")).strip()
        if inventory_id not in order_counts:
            continue
        before_sold = int(number_value(row.get("已售数"), 0))
        locked = int(number_value(row.get("锁座数"), 0))
        sold = order_counts[inventory_id]
        remaining = max(0, locked - sold) if locked else 0
        row["已售数"] = str(sold)
        row["剩余数"] = str(remaining)
        row["库存状态"] = inventory_status_after_sync(locked, remaining)
        row["更新时间"] = now_ts()
        row["更新人"] = actor
        synced_rows.append({
            "库存ID": inventory_id,
            "航线": row.get("航线", ""),
            "锁座数": str(locked),
            "有效订单数": str(sold),
            "同步前已售": str(before_sold),
            "同步后已售": str(sold),
            "同步后剩余": str(remaining),
            "库存状态": row["库存状态"],
        })

    save_operation_center(data)
    append_audit_log(actor, role, "订单库存联动同步", "cutInventory", "成功", f"同步{len(synced_rows)}条库存", ip)
    return {"ok": True, "rows": synced_rows, "count": len(synced_rows), "orderLinks": len(order_counts)}


def mock_ota_trace_id():
    return f"trace-{int(time.time())}-{secrets.token_hex(4)}"


def mock_ota_policy_from_inventory(row):
    locked = int(number_value(row.get("锁座数"), 0))
    sold = int(number_value(row.get("已售数"), 0))
    remaining = int(number_value(row.get("剩余数"), max(0, locked - sold)))
    status = str(row.get("库存状态", "") or "销售中").strip()
    if status in {"已售罄", "停用", "禁用", "下架", "关闭"} or remaining <= 0:
        ota_status = "下架"
    else:
        ota_status = "上架"
    price = row.get("计划售价") or row.get("销售价") or row.get("成本价") or ""
    policy_id = str(row.get("id", "")).strip() or operation_record_id("cutInventory")
    return {
        "policy_id": policy_id,
        "source_inventory_id": policy_id,
        "route": normalize_route(str(row.get("航线", "")).strip()) or str(row.get("航线", "")).strip(),
        "airline": row.get("航司", ""),
        "flight_no": row.get("航班号", ""),
        "departure_date": row.get("出发日期", "") or row.get("航班日期", ""),
        "cabin": row.get("舱位", ""),
        "sale_price": price,
        "settlement_price": row.get("成本价", ""),
        "inventory": max(0, locked),
        "sold": max(0, sold),
        "available": max(0, remaining),
        "valid_from": time.strftime("%Y-%m-%d"),
        "valid_to": row.get("出发日期", "") or row.get("航班日期", ""),
        "refund_rule": row.get("政策提示", ""),
        "change_rule": row.get("备注", ""),
        "status": ota_status,
        "source": "主系统切位库存台账",
        "updated_at": now_ts(),
    }


def build_mock_ota_policies():
    data = load_operation_center()
    policies = []
    for row in data.get("cutInventory", []):
        if row.get("_deleted"):
            continue
        route = str(row.get("航线", "")).strip()
        if not route:
            continue
        policies.append(mock_ota_policy_from_inventory(row))
    return policies


def publish_policies_to_mock_ota(session, ip=""):
    actor, role = session_actor(session)
    policies = build_mock_ota_policies()
    trace_id = mock_ota_trace_id()
    payload = json.dumps({"policies": policies, "trace_id": trace_id}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{MOCK_OTA_BASE_URL}/api/policies/upsert",
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Mock-OTA-Token": MOCK_OTA_TOKEN,
            "X-Trace-Id": trace_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8") or "{}")
        append_audit_log(actor, role, "发布政策到Mock OTA", "mock-ota", "成功", f"policies={len(policies)} trace_id={trace_id}", ip)
        return {"ok": True, "published": len(policies), "mockOta": result, "trace_id": trace_id, "mockOtaBaseUrl": MOCK_OTA_BASE_URL}
    except Exception as exc:
        append_audit_log(actor, role, "发布政策到Mock OTA", "mock-ota", "失败", str(exc), ip)
        raise


def publish_policies_to_channels(session, channels=None, ip=""):
    selected = channels if isinstance(channels, list) else ["mock_ota"]
    selected = [str(item).strip() for item in selected if str(item).strip()]
    if not selected:
        raise ValueError("请至少选择一个发布渠道。")

    channel_names = {
        "mock_ota": "Mock OTA",
        "ctrip": "携程",
        "qunar": "去哪儿",
        "fliggy": "飞猪",
        "ly": "同程",
    }
    results = []
    published = 0
    for channel in selected:
        if channel == "mock_ota":
            result = publish_policies_to_mock_ota(session, ip)
            published += int(result.get("published") or 0)
            results.append({
                "channel": channel,
                "name": channel_names[channel],
                "ok": True,
                "published": result.get("published", 0),
                "baseUrl": result.get("mockOtaBaseUrl", ""),
                "trace_id": result.get("trace_id", ""),
            })
            continue
        results.append({
            "channel": channel,
            "name": channel_names.get(channel, channel),
            "ok": False,
            "error": "该渠道接口尚未接入，不能发布。",
        })

    if not any(item.get("ok") for item in results):
        raise ValueError("所选渠道均未接入，不能发布。")
    return {"ok": True, "published": published, "channels": results}


def verify_mock_ota_token(headers):
    return (headers.get("X-Mock-OTA-Token") or "") == MOCK_OTA_TOKEN


def apply_mock_ota_inventory_delta(data, inventory_id, delta):
    if not inventory_id:
        return None
    row = next((item for item in data.get("cutInventory", []) if str(item.get("id", "")) == str(inventory_id)), None)
    if not row:
        return None
    locked = int(number_value(row.get("锁座数"), 0))
    sold = max(0, int(number_value(row.get("已售数"), 0)) + delta)
    row["已售数"] = str(sold)
    row["剩余数"] = str(max(0, locked - sold))
    row["库存状态"] = inventory_status_after_sync(locked, int(number_value(row.get("剩余数"), 0)))
    row["更新时间"] = now_ts()
    row["更新人"] = "Mock OTA回调"
    return row


def handle_mock_ota_order_callback(payload, ip=""):
    trace_id = str(payload.get("trace_id") or payload.get("traceId") or "")
    action = str(payload.get("action", "create")).strip()
    order = payload.get("order") or {}
    if not isinstance(order, dict):
        raise ValueError("订单回调格式不正确")
    order_id = str(order.get("order_id", "")).strip()
    if not order_id:
        raise ValueError("订单号不能为空")

    data = load_operation_center()
    orders = data.setdefault("orders", [])
    existing = next((row for row in orders if str(row.get("订单号", "")).strip() == order_id), None)
    inventory_id = str(order.get("source_inventory_id") or order.get("policy_id") or "").strip()
    quantity = max(1, int(number_value(order.get("quantity"), 1)))
    previous_status = str(existing.get("订单状态", "")).strip() if existing else ""
    status = "已取消" if action == "cancel" or str(order.get("status")) == "已取消" else "待处理"
    record = {
        "id": existing.get("id") if existing else operation_record_id("orders"),
        "订单号": order_id,
        "店铺": "Mock OTA沙盒店铺",
        "渠道": "Mock OTA",
        "航线": order.get("route", ""),
        "航司": order.get("airline", ""),
        "航班号": order.get("flight_no", ""),
        "出发日期": order.get("departure_date", ""),
        "乘机人": order.get("passenger", ""),
        "订单金额": str(order.get("amount", "")),
        "成本": "",
        "PNR": "",
        "票号": "",
        "关联库存ID": inventory_id,
        "出票账号": "",
        "联系人": "",
        "订单状态": status,
        "处理人": "Mock OTA",
        "政策提示": f"Mock OTA 回调 trace_id={trace_id}",
        "备注": f"来源政策 {order.get('policy_id', '')}；数量 {quantity}；回调动作 {action}",
        "更新时间": now_ts(),
        "更新人": "Mock OTA回调",
    }
    if existing:
        existing.update(record)
    else:
        orders.insert(0, record)

    inventory_delta = 0
    if not existing and status != "已取消":
        inventory_delta = quantity
    elif existing and previous_status != "已取消" and status == "已取消":
        inventory_delta = -quantity
    inventory_row = apply_mock_ota_inventory_delta(data, inventory_id, inventory_delta) if inventory_delta else None
    ticket_task = None
    if status == "已取消":
        ticket_task = find_ticket_task(data, order_id)
        if ticket_task:
            ticket_task["出票状态"] = "取消"
            ticket_task["异常原因"] = "订单已取消，出票任务关闭。"
            ticket_task["更新时间"] = now_ts()
            ticket_task["更新人"] = "Mock OTA回调"
    else:
        ticket_task = order_to_ticket_task(data, record, "Mock OTA回调")
    save_operation_center(data)
    append_audit_log("Mock OTA", "外部渠道", "Mock OTA订单回流", order_id, "成功", f"action={action}; inventory={inventory_id}; delta={inventory_delta}; ticket={ticket_task.get('任务号', '') if ticket_task else ''}; trace_id={trace_id}", ip)
    return {"ok": True, "order": record, "inventory": inventory_row, "ticketTask": ticket_task, "inventoryDelta": inventory_delta, "trace_id": trace_id}


def sync_orders_to_ticket_tasks(session, ip=""):
    data = load_operation_center()
    actor, role = session_actor(session)
    current = now_ts()
    existing_orders = {str(row.get("订单号", "")).strip() for row in data.get("ticketTasks", [])}
    created = []
    for order in data.get("orders", []):
        order_no = str(order.get("订单号", "")).strip()
        if not order_no or order_no in existing_orders:
            continue
        if not active_order_for_inventory(order):
            continue
        row = order_to_ticket_task(data, order, actor)
        if row:
            row["备注"] = row.get("备注") or "由订单中心同步生成。"
            created.append(row)
        existing_orders.add(order_no)
    save_operation_center(data)
    append_audit_log(actor, role, "订单同步出票任务", "ticketTasks", "成功", f"新增{len(created)}条", ip)
    return {"ok": True, "rows": created, "count": len(created)}


def sync_ticket_tasks_to_checks(session, ip=""):
    data = load_operation_center()
    actor, role = session_actor(session)
    current = now_ts()
    existing_keys = {
        (
            str(row.get("订单号", "")).strip(),
            str(row.get("票号", "")).strip(),
            str(row.get("PNR", "")).strip(),
        )
        for row in data.get("ticketChecks", [])
    }
    created = []
    for task in data.get("ticketTasks", []):
        order_no = str(task.get("订单号", "")).strip()
        ticket_no = str(task.get("票号", "")).strip()
        pnr = str(task.get("PNR", "")).strip()
        if not order_no or not (ticket_no or pnr):
            continue
        key = (order_no, ticket_no, pnr)
        if key in existing_keys:
            continue
        row = {
            "id": operation_record_id("ticketChecks"),
            "验票编号": f"VC-{current}-{len(created)+1}",
            "订单号": order_no,
            "票号": ticket_no,
            "PNR": pnr,
            "航司": task.get("航司", ""),
            "航班号": task.get("航班号", ""),
            "乘机人": task.get("乘机人", ""),
            "验票状态": "待验证",
            "验票人": actor,
            "备注": "由出票任务同步生成，待人工或接口验票。",
            "更新时间": current,
            "更新人": actor,
        }
        data["ticketChecks"].insert(0, row)
        created.append(row)
        existing_keys.add(key)
    save_operation_center(data)
    append_audit_log(actor, role, "出票任务同步验票记录", "ticketChecks", "成功", f"新增{len(created)}条", ip)
    return {"ok": True, "rows": created, "count": len(created)}


def sync_refunds_to_after_sales(session, ip=""):
    data = load_operation_center()
    actor, role = session_actor(session)
    current = now_ts()
    existing_keys = {
        str(row.get("关联退改单号", "") or row.get("退改单号", "") or "").strip()
        for row in data.get("afterSalesCases", [])
    }
    order_store = {
        str(row.get("订单号", "")).strip(): row.get("店铺", "")
        for row in data.get("orders", [])
        if str(row.get("订单号", "")).strip()
    }
    created = []
    for refund in data.get("refundChangeOrders", []):
        refund_no = str(refund.get("退改单号", "")).strip()
        order_no = str(refund.get("订单号", "")).strip()
        key = refund_no or f"{order_no}-{refund.get('退改类型', '')}-{refund.get('票号', '')}"
        if not key or key in existing_keys:
            continue
        row = {
            "id": operation_record_id("afterSalesCases"),
            "工单号": f"AS-{current}-{len(created)+1}",
            "订单号": order_no,
            "店铺": order_store.get(order_no, ""),
            "问题类型": refund.get("退改类型", "") or "退改处理",
            "优先级": "中",
            "处理状态": "待处理",
            "负责人": refund.get("处理人", "") or actor,
            "联系人": "",
            "备注": f"由退改订单同步生成；退改单号:{refund_no}；申请金额:{refund.get('申请金额', '')}；成本损失:{refund.get('成本损失', '')}",
            "关联退改单号": refund_no,
            "更新时间": current,
            "更新人": actor,
        }
        data["afterSalesCases"].insert(0, row)
        created.append(row)
        existing_keys.add(key)
    save_operation_center(data)
    append_audit_log(actor, role, "退改订单同步售后工单", "afterSalesCases", "成功", f"新增{len(created)}条", ip)
    return {"ok": True, "rows": created, "count": len(created)}


def sync_orders_to_payment_returns(session, ip=""):
    data = load_operation_center()
    actor, role = session_actor(session)
    current = now_ts()
    existing_orders = {str(row.get("订单号", "")).strip() for row in data.get("paymentReturns", [])}
    created = []
    for order in data.get("orders", []):
        order_no = str(order.get("订单号", "")).strip()
        if not order_no or order_no in existing_orders:
            continue
        if not active_order_for_inventory(order):
            continue
        amount = number_value(order.get("订单金额"), 0)
        cost = number_value(order.get("成本"), 0)
        row = {
            "id": operation_record_id("paymentReturns"),
            "流水号": f"PAY-{current}-{len(created)+1}",
            "订单号": order_no,
            "店铺": order.get("店铺", ""),
            "渠道": order.get("渠道", ""),
            "订单金额": f"{amount:.2f}" if amount else str(order.get("订单金额", "")),
            "到账金额": "",
            "手续费": "",
            "退款金额": "",
            "利润": f"{(amount - cost):.2f}" if amount or cost else "",
            "回填状态": "待回填",
            "备注": "由订单中心同步生成支付回填草稿，到账/手续费/退款需人工或接口补录。",
            "更新时间": current,
            "更新人": actor,
        }
        data["paymentReturns"].insert(0, row)
        created.append(row)
        existing_orders.add(order_no)
    save_operation_center(data)
    append_audit_log(actor, role, "订单同步支付回填", "paymentReturns", "成功", f"新增{len(created)}条", ip)
    return {"ok": True, "rows": created, "count": len(created)}


def seed_demo_orders(session, ip="", count=20):
    data = load_operation_center()
    actor, role = session_actor(session)
    current = now_ts()
    count = max(1, min(50, int(number_value(count, 20))))
    batch = f"DEMO-{time.strftime('%Y%m%d%H%M%S')}"
    routes = ["PKX-CJU", "BJS-SIN", "SHA-BKK", "HKG-CJU", "NRT-ICN"]
    airlines = ["7C", "8M", "LJ", "FD", "HO"]
    channels = active_operation_channels(data)
    if not channels:
        raise ValueError("当前没有启用渠道，无法生成可联动订单。请先在渠道管理中启用至少一个渠道。")
    stores = []
    ticket_accounts = []
    contacts = []
    for channel in channels:
        store = first_matching_record(data.get("stores", []), "渠道", channel) or first_matching_record(data.get("stores", []), "平台", channel)
        account = first_matching_record(data.get("ticketAccounts", []), "渠道", channel, "账号状态")
        contact = first_matching_record(data.get("contacts", []), "所属渠道", channel)
        stores.append(store.get("店铺名称") or f"{channel}默认店铺")
        ticket_accounts.append(account.get("账号名称") or f"{channel}默认出票账号")
        contacts.append(contact.get("姓名") or account.get("联系人") or f"{channel}默认联系人")
    inventories = []
    for index, route in enumerate(routes):
        channel = channels[index % len(channels)]
        inv = {
            "id": operation_record_id("cutInventory"),
            "航线": route,
            "航司": airlines[index % len(airlines)],
            "航班号": f"{airlines[index % len(airlines)]}{230 + index}",
            "出发日期": f"2026-07-{index + 10:02d}",
            "舱位": "G",
            "PNR": f"{batch[-6:]}{index}PN",
            "锁座数": "12",
            "已售数": "0",
            "剩余数": "12",
            "成本价": str(560 + index * 40),
            "计划售价": str(760 + index * 60),
            "库存状态": "销售中",
            "采购渠道": channel,
            "负责人": actor,
            "政策提示": "",
            "备注": f"{batch} 模拟切位库存",
            "更新时间": current,
            "更新人": actor,
        }
        data["cutInventory"].insert(0, inv)
        inventories.append(inv)

    orders = []
    for index in range(count):
        inv = inventories[index % len(inventories)]
        channel = channels[index % len(channels)]
        amount = 880 + (index % 7) * 80
        cost = number_value(inv.get("成本价"), 0)
        order = {
            "id": operation_record_id("orders"),
            "订单号": f"{batch}-ORD-{index + 1:03d}",
            "店铺": stores[index % len(stores)],
            "渠道": channel,
            "航线": inv.get("航线", ""),
            "航司": inv.get("航司", ""),
            "航班号": inv.get("航班号", ""),
            "出发日期": inv.get("出发日期", ""),
            "乘机人": f"模拟旅客{index + 1:02d}",
            "订单金额": f"{amount:.2f}",
            "成本": f"{cost:.2f}",
            "PNR": inv.get("PNR", ""),
            "票号": "" if index % 4 == 0 else f"999-{batch[-6:]}{index + 1:03d}",
            "关联库存ID": inv.get("id", ""),
            "出票账号": ticket_accounts[index % len(ticket_accounts)],
            "联系人": contacts[index % len(contacts)],
            "订单状态": "待处理" if index % 5 else "已出票",
            "处理人": actor,
            "政策提示": operation_policy_hint({"航线": inv.get("航线", ""), "航司": inv.get("航司", "")}),
            "备注": f"{batch} 自动生成模拟订单，用于联动测试",
            "更新时间": current,
            "更新人": actor,
        }
        data["orders"].insert(0, order)
        orders.append(order)

    refunds = []
    for index, order in enumerate(orders[:5]):
        refund = {
            "id": operation_record_id("refundChangeOrders"),
            "退改单号": f"{batch}-RF-{index + 1:03d}",
            "订单号": order.get("订单号", ""),
            "票号": order.get("票号", ""),
            "乘机人": order.get("乘机人", ""),
            "退改类型": "退票" if index % 2 == 0 else "改签",
            "申请金额": order.get("订单金额", ""),
            "成本损失": "120.00",
            "处理状态": "待处理",
            "处理人": actor,
            "备注": f"{batch} 模拟退改样本，用于售后联动测试",
            "更新时间": current,
            "更新人": actor,
        }
        data["refundChangeOrders"].insert(0, refund)
        refunds.append(refund)

    save_operation_center(data)
    append_audit_log(actor, role, "生成模拟订单", "orders", "成功", f"{batch} 订单{len(orders)}条，库存{len(inventories)}条，退改{len(refunds)}条，启用渠道{','.join(channels)}", ip)
    return {
        "ok": True,
        "batch": batch,
        "rows": orders,
        "count": len(orders),
        "inventoryCount": len(inventories),
        "refundCount": len(refunds),
        "channels": channels,
    }


def operation_statistics():
    data = load_operation_center()
    orders = [row for row in data.get("orders", []) if not row.get("_deleted")]
    tickets = [row for row in data.get("ticketTasks", []) if not row.get("_deleted")]
    refunds = [row for row in data.get("refundChangeOrders", []) if not row.get("_deleted")]
    after_sales = [row for row in data.get("afterSalesCases", []) if not row.get("_deleted")]
    payments = [row for row in data.get("paymentReturns", []) if not row.get("_deleted")]
    inventory = [row for row in data.get("cutInventory", []) if not row.get("_deleted")]
    total_amount = sum(number_value(row.get("订单金额"), 0) for row in orders)
    total_cost = sum(number_value(row.get("成本"), 0) for row in orders)
    total_paid = sum(number_value(row.get("到账金额"), 0) for row in payments)
    total_profit = sum(number_value(row.get("利润"), 0) for row in payments)
    open_after_sales = sum(1 for row in after_sales if str(row.get("处理状态", "")).strip() not in {"已完成", "关闭", "已关闭"})
    pending_ticket = sum(1 for row in tickets if str(row.get("出票状态", "")).strip() not in {"已出票", "关闭", "已关闭"})
    low_inventory = sum(1 for row in inventory if str(row.get("库存状态", "")).strip() in {"低库存", "已售罄"})
    rows = [
        {"指标": "订单数", "数值": str(len(orders)), "说明": "订单中心当前有效记录数"},
        {"指标": "订单金额", "数值": f"{total_amount:.2f}", "说明": "订单中心订单金额合计"},
        {"指标": "订单成本", "数值": f"{total_cost:.2f}", "说明": "订单中心成本合计"},
        {"指标": "待出票任务", "数值": str(pending_ticket), "说明": "出票状态未完成的任务数"},
        {"指标": "退改订单", "数值": str(len(refunds)), "说明": "退改订单台账记录数"},
        {"指标": "未结售后", "数值": str(open_after_sales), "说明": "售后工单未完成记录数"},
        {"指标": "到账金额", "数值": f"{total_paid:.2f}", "说明": "支付回填到账金额合计"},
        {"指标": "回填利润", "数值": f"{total_profit:.2f}", "说明": "支付回填利润合计"},
        {"指标": "低库存/售罄", "数值": str(low_inventory), "说明": "切位库存中低库存或售罄记录数"},
    ]
    return {"ok": True, "rows": rows, "count": len(rows)}


def sync_platforms_to_store_channels(session, ip=""):
    data = load_operation_center()
    actor, role = session_actor(session)
    current = now_ts()
    store_keys = {(row.get("平台", ""), row.get("店铺名称", "")) for row in data.get("stores", [])}
    channel_keys = {row.get("渠道名称", "") for row in data.get("channels", [])}
    contact_keys = {row.get("姓名", "") for row in data.get("contacts", [])}
    account_keys = {row.get("账号名称", "") for row in data.get("ticketAccounts", [])}
    created = []

    for platform in OTA_PLATFORMS:
        store_name = f"{platform}默认店铺"
        contact_name = f"{platform}默认联系人"
        account_name = f"{platform}默认出票账号"
        if (platform, store_name) not in store_keys:
            data["stores"].insert(0, {
                "id": operation_record_id("stores"),
                "店铺名称": store_name,
                "平台": platform,
                "渠道": platform,
                "店铺编号": f"{platform}-DEFAULT",
                "Office号": "",
                "商户号/域名": "",
                "用户名": "",
                "商户账号": "",
                "OTA刷新缓存账号": "",
                "状态": "启用",
                "负责人": actor,
                "备注": "由接口预留平台同步生成，可按实际店铺修改。",
                "更新时间": current,
                "更新人": actor,
            })
            created.append({"类型": "店铺", "名称": store_name, "平台": platform})
        if platform not in channel_keys:
            data["channels"].insert(0, {
                "id": operation_record_id("channels"),
                "渠道名称": platform,
                "渠道类型": "OTA平台",
                "结算方式": "待配置",
                "状态": "启用",
                "备注": "由接口预留平台同步生成，可补充结算方式和规则。",
                "更新时间": current,
                "更新人": actor,
            })
            created.append({"类型": "渠道", "名称": platform, "平台": platform})
        if contact_name not in contact_keys:
            data["contacts"].insert(0, {
                "id": operation_record_id("contacts"),
                "姓名": contact_name,
                "类型": "平台联系人",
                "手机": "",
                "邮箱": "",
                "所属渠道": platform,
                "备注": "由接口预留平台同步生成，可替换为真实联系人。",
                "更新时间": current,
                "更新人": actor,
            })
            created.append({"类型": "联系人", "名称": contact_name, "平台": platform})
        if account_name not in account_keys:
            data["ticketAccounts"].insert(0, {
                "id": operation_record_id("ticketAccounts"),
                "账号名称": account_name,
                "渠道": platform,
                "Office号": "",
                "账号状态": "启用",
                "联系人": contact_name,
                "备注": "由接口预留平台同步生成，可替换为真实出票账号。",
                "更新时间": current,
                "更新人": actor,
            })
            created.append({"类型": "出票账号", "名称": account_name, "平台": platform})

    save_operation_center(data)
    append_audit_log(actor, role, "接口平台同步基础资料", "stores/channels/accounts/contacts", "成功", f"新增{len(created)}条", ip)
    return {"ok": True, "rows": created, "count": len(created), "platforms": OTA_PLATFORMS}


def session_actor(session):
    if not session:
        return "未登录", ""
    if session.get("role") == "admin":
        return "admin", "管理员"
    if session.get("role") == "employee":
        return session.get("employeeId", ""), "员工"
    if session.get("role") == "visitor":
        return session.get("phone", ""), "访客"
    return session.get("phone") or session.get("employeeId") or "未知", session.get("role", "")


def cleanup_access_control(data):
    current = now_ts()
    data["passes"] = [row for row in data.get("passes", []) if int(row.get("expiresAt", 0)) > current and not row.get("revoked")]
    employees = {row.get("employeeId"): row for row in data.get("employees", [])}
    data["sessions"] = {
        token: session for token, session in data.get("sessions", {}).items()
        if int(session.get("expiresAt", 0)) > current
        and not (
            session.get("role") == "employee"
            and int(employees.get(session.get("employeeId"), {}).get("accountExpiresAt", current + 1) or current + 1) <= current
        )
    }
    save_access_control(data)
    return data


def parse_cookie(header):
    cookies = {}
    for part in str(header or "").split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            cookies[key] = value
    return cookies


def create_access_pass(phone, hours, note=""):
    phone = re.sub(r"\D+", "", str(phone or ""))
    if len(phone) < 6:
        raise ValueError("请填写正确的手机号")
    hours = max(1, min(168, int(number_value(hours, 1))))
    alphabet = string.ascii_uppercase + string.digits
    access_password = "".join(secrets.choice(alphabet) for _ in range(8))
    sms_code = "".join(secrets.choice(string.digits) for _ in range(6))
    current = now_ts()
    row = {
        "id": secrets.token_hex(8),
        "phone": phone,
        "passwordHash": password_hash(access_password),
        "smsCode": sms_code,
        "note": str(note or "").strip(),
        "createdAt": current,
        "expiresAt": current + hours * 3600,
        "hours": hours,
        "revoked": False,
    }
    data = cleanup_access_control(load_access_control())
    data["passes"].append(row)
    save_access_control(data)
    return {
        "phone": phone,
        "accessPassword": access_password,
        "smsCode": sms_code,
        "expiresAt": row["expiresAt"],
        "hours": hours,
        "note": row["note"],
        "smsMode": "本地模拟验证码，后续可接短信API自动发送。",
    }


def login_with_access(phone, access_password, sms_code):
    phone = re.sub(r"\D+", "", str(phone or ""))
    data = cleanup_access_control(load_access_control())
    current = now_ts()
    matched = None
    for row in data.get("passes", []):
        if row.get("phone") != phone:
            continue
        if row.get("passwordHash") != password_hash(access_password):
            continue
        if str(row.get("smsCode")) != str(sms_code or "").strip():
            continue
        if int(row.get("expiresAt", 0)) <= current:
            continue
        matched = row
        break
    if not matched:
        raise ValueError("手机号、访问密码或验证码不正确，或授权已过期。")
    token = secrets.token_urlsafe(32)
    session = {
        "phone": phone,
        "role": "visitor",
        "expiresAt": int(matched["expiresAt"]),
        "passId": matched["id"],
    }
    data["sessions"][token] = session
    save_access_control(data)
    append_audit_log(phone, "访客", "访客登录", phone, "成功", "手机号验证码登录")
    return token, session


def normalize_employee_id(employee_id):
    value = re.sub(r"\s+", "", str(employee_id or "")).upper()
    if not re.match(r"^[A-Z0-9_-]{2,24}$", value):
        raise ValueError("员工号需为2-24位字母、数字、下划线或横线。")
    return value


def public_employee(row):
    role = normalize_account_role(row.get("role", "sales"))
    return {
        "employeeId": row.get("employeeId", ""),
        "name": row.get("name", ""),
        "role": role,
        "roleLabel": role_label(role),
        "permissions": normalize_permissions(row.get("permissions"), role),
        "status": row.get("status", "active"),
        "accountExpiresAt": row.get("accountExpiresAt", 0),
        "validityMode": row.get("validityMode", "longTerm"),
        "createdAt": row.get("createdAt", 0),
        "updatedAt": row.get("updatedAt", 0),
        "lastLoginAt": row.get("lastLoginAt", 0),
    }


def normalize_account_role(role):
    role = str(role or "sales").strip()
    role = LEGACY_ROLE_MAP.get(role, role)
    return role if role in ROLE_TEMPLATES else "sales"


def role_label(role):
    return ROLE_TEMPLATES.get(normalize_account_role(role), {}).get("label", "销售")


def normalize_permissions(permissions=None, role="sales"):
    role = normalize_account_role(role)
    base = ROLE_TEMPLATES.get(role, ROLE_TEMPLATES["sales"])["permissions"]
    can_customize = role in {"manager", "accountAdmin"}
    if permissions is None or not can_customize:
        values = base
    elif isinstance(permissions, list):
        values = permissions
    else:
        values = str(permissions or "").split(",")
    allowed = set(PERMISSION_DEFINITIONS) - {"system.admin"}
    return sorted({str(item).strip() for item in values if str(item).strip() in allowed})


def permission_catalog():
    return {
        "roles": [
            {
                "key": key,
                "label": config["label"],
                "description": config["description"],
                "permissions": normalize_permissions(config["permissions"], key),
            }
            for key, config in ROLE_TEMPLATES.items()
        ],
        "permissions": [{"key": key, "label": label} for key, label in PERMISSION_DEFINITIONS.items()],
    }


def session_permissions(session):
    if not session:
        return []
    if session.get("role") == "admin":
        return sorted(PERMISSION_DEFINITIONS)
    if session.get("role") == "visitor":
        return ["dashboard.view", "strategy.view"]
    return normalize_permissions(session.get("permissions"), session.get("accountRole", "sales"))


def has_permission(session, permission):
    if not permission:
        return bool(session)
    if session and session.get("role") == "admin":
        return True
    return permission in set(session_permissions(session))


def employee_expiry_from_payload(validity_mode="longTerm", custom_expires_at=""):
    mode = str(validity_mode or "longTerm").strip()
    current = now_ts()
    presets = {
        "1h": 1 * 3600,
        "3h": 3 * 3600,
        "6h": 6 * 3600,
        "12h": 12 * 3600,
        "1d": 24 * 3600,
        "3d": 3 * 24 * 3600,
        "7d": 7 * 24 * 3600,
        "30d": 30 * 24 * 3600,
        "longTerm": LONG_TERM_SECONDS,
    }
    if mode == "custom":
        dt = pd.to_datetime(str(custom_expires_at or ""), errors="coerce")
        if pd.isna(dt):
            raise ValueError("请选择自定义到期时间。")
        expires_at = int(dt.timestamp())
        if expires_at <= current:
            raise ValueError("账号到期时间必须晚于当前时间。")
        return expires_at, "custom"
    seconds = presets.get(mode, LONG_TERM_SECONDS)
    return current + seconds, mode


def list_employee_accounts():
    data = cleanup_access_control(load_access_control())
    rows = sorted(data.get("employees", []), key=lambda item: item.get("employeeId", ""))
    return {"accounts": [public_employee(row) for row in rows]}


def upsert_employee_account(employee_id, name, password="", role="sales", status="active", validity_mode="longTerm", custom_expires_at="", permissions=None):
    employee_id = normalize_employee_id(employee_id)
    name = str(name or "").strip() or employee_id
    password = str(password or "")
    role = normalize_account_role(role)
    permissions = normalize_permissions(permissions, role)
    status = "disabled" if str(status) == "disabled" else "active"
    data = cleanup_access_control(load_access_control())
    accounts = data.setdefault("employees", [])
    current = now_ts()
    account_expires_at, validity_mode = employee_expiry_from_payload(validity_mode, custom_expires_at)
    existing = next((row for row in accounts if row.get("employeeId") == employee_id), None)
    if existing:
        existing["name"] = name
        existing["role"] = role
        existing["permissions"] = permissions
        existing["status"] = status
        existing["accountExpiresAt"] = account_expires_at
        existing["validityMode"] = validity_mode
        existing["updatedAt"] = current
        if password:
            if len(password) < 6:
                raise ValueError("员工登录密码至少需要6位。")
            existing["passwordHash"] = password_hash(password)
        if status == "disabled" or account_expires_at <= current:
            for token, session in list(data.get("sessions", {}).items()):
                if session.get("employeeId") == employee_id:
                    data["sessions"].pop(token, None)
        action = "修改员工账号"
    else:
        if len(password) < 6:
            raise ValueError("新员工账号必须设置至少6位登录密码。")
        existing = {
            "employeeId": employee_id,
            "name": name,
            "role": role,
            "permissions": permissions,
            "status": status,
            "accountExpiresAt": account_expires_at,
            "validityMode": validity_mode,
            "passwordHash": password_hash(password),
            "createdAt": current,
            "updatedAt": current,
            "lastLoginAt": 0,
        }
        accounts.append(existing)
        action = "新增员工账号"
    save_access_control(data)
    return {"ok": True, "action": action, "account": public_employee(existing), "accounts": [public_employee(row) for row in sorted(accounts, key=lambda item: item.get("employeeId", ""))]}


def set_employee_status(employee_id, status):
    employee_id = normalize_employee_id(employee_id)
    status = "disabled" if str(status) == "disabled" else "active"
    data = cleanup_access_control(load_access_control())
    row = next((item for item in data.get("employees", []) if item.get("employeeId") == employee_id), None)
    if not row:
        raise ValueError("员工账号不存在。")
    row["status"] = status
    row["updatedAt"] = now_ts()
    if status == "disabled":
        for token, session in list(data.get("sessions", {}).items()):
            if session.get("employeeId") == employee_id:
                data["sessions"].pop(token, None)
    save_access_control(data)
    return {"ok": True, "account": public_employee(row)}


def delete_employee_account(employee_id):
    employee_id = normalize_employee_id(employee_id)
    data = cleanup_access_control(load_access_control())
    accounts = data.get("employees", [])
    row = next((item for item in accounts if item.get("employeeId") == employee_id), None)
    if not row:
        raise ValueError("员工账号不存在。")
    data["employees"] = [item for item in accounts if item.get("employeeId") != employee_id]
    for token, session in list(data.get("sessions", {}).items()):
        if session.get("employeeId") == employee_id:
            data["sessions"].pop(token, None)
    save_access_control(data)
    rows = sorted(data.get("employees", []), key=lambda item: item.get("employeeId", ""))
    return {"ok": True, "account": public_employee(row), "accounts": [public_employee(item) for item in rows]}


def login_with_employee(employee_id, password):
    employee_id = normalize_employee_id(employee_id)
    data = cleanup_access_control(load_access_control())
    row = next((item for item in data.get("employees", []) if item.get("employeeId") == employee_id), None)
    if not row or row.get("passwordHash") != password_hash(password):
        raise ValueError("员工号或密码不正确。")
    if row.get("status") == "disabled":
        raise ValueError("该员工账号已停用，请联系管理员。")
    account_expires_at = int(row.get("accountExpiresAt", now_ts() + LONG_TERM_SECONDS) or now_ts() + LONG_TERM_SECONDS)
    if account_expires_at <= now_ts():
        raise ValueError("该员工账号授权已过期，请联系管理员重新设置有效期。")
    token = secrets.token_urlsafe(32)
    expires_at = min(now_ts() + ADMIN_SESSION_SECONDS, account_expires_at)
    row["lastLoginAt"] = now_ts()
    session = {
        "employeeId": employee_id,
        "name": row.get("name", employee_id),
        "role": "employee",
        "accountRole": normalize_account_role(row.get("role", "sales")),
        "accountRoleLabel": role_label(row.get("role", "sales")),
        "permissions": normalize_permissions(row.get("permissions"), row.get("role", "sales")),
        "expiresAt": expires_at,
        "accountExpiresAt": account_expires_at,
    }
    data["sessions"][token] = session
    save_access_control(data)
    append_audit_log(employee_id, "员工", "员工登录", employee_id, "成功", row.get("name", ""))
    return token, session


def admin_login(password):
    data = cleanup_access_control(load_access_control())
    if data.get("adminPasswordHash") != password_hash(password):
        raise ValueError("管理员密码不正确。")
    token = secrets.token_urlsafe(32)
    session = {
        "phone": "admin",
        "role": "admin",
        "permissions": sorted(PERMISSION_DEFINITIONS),
        "expiresAt": now_ts() + ADMIN_SESSION_SECONDS,
        "noTimeLimit": True,
    }
    data["sessions"][token] = session
    save_access_control(data)
    append_audit_log("admin", "管理员", "管理员登录", "admin", "成功", "管理员不限时登录")
    return token, session


def change_admin_password(old_password, new_password):
    new_password = str(new_password or "")
    if len(new_password) < 8:
        raise ValueError("新管理员密码至少需要8位。")
    data = cleanup_access_control(load_access_control())
    if data.get("adminPasswordHash") != password_hash(old_password):
        raise ValueError("原管理员密码不正确。")
    data["adminPasswordHash"] = password_hash(new_password)
    save_access_control(data)
    return {"ok": True, "message": "管理员密码已更新。"}


def auth_session_from_cookie(cookie_header):
    token = parse_cookie(cookie_header).get("air_skill_session", "")
    if not token:
        return None
    data = cleanup_access_control(load_access_control())
    session = data.get("sessions", {}).get(token)
    if not session:
        return None
    if int(session.get("expiresAt", 0)) <= now_ts():
        return None
    if session.get("role") == "admin":
        session["permissions"] = sorted(PERMISSION_DEFINITIONS)
    elif session.get("role") == "employee":
        employee = next((row for row in data.get("employees", []) if row.get("employeeId") == session.get("employeeId")), {})
        account_role = normalize_account_role(employee.get("role", session.get("accountRole", "sales")))
        session["accountRole"] = account_role
        session["accountRoleLabel"] = role_label(account_role)
        session["permissions"] = normalize_permissions(employee.get("permissions", session.get("permissions")), account_role)
    return session


def revoke_session(cookie_header):
    token = parse_cookie(cookie_header).get("air_skill_session", "")
    if not token:
        return
    data = load_access_control()
    data.get("sessions", {}).pop(token, None)
    save_access_control(data)


def update_execution_task(task_id, action, operator="人工确认", platform=""):
    rows = load_execution_tasks()
    task = next((row for row in rows if row.get("任务ID") == task_id), None)
    if not task:
        raise ValueError("没有找到这条执行任务，请重新生成任务池。")
    platform = str(platform or "").strip()
    action_map = {
        "approve": ("已确认", "待执行", "已人工确认，可交由执行接口或人工操作。"),
        "execute": ("已确认", "模拟完成", "已完成模拟执行；未调用真实OTA接口。"),
        "reject": ("已驳回", "已关闭", "任务已驳回，不进入执行。"),
        "cancel": ("已取消", "已关闭", "任务已取消。"),
    }
    if action not in action_map:
        raise ValueError("不支持的任务处理动作。")
    approval, execution, note = action_map[action]
    if action == "execute" and platform:
        note = f"已选择{platform}模拟执行；未调用真实OTA接口。"
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    history = task.get("处理记录")
    if not isinstance(history, list):
        history = []
    history_item = {"时间": now, "操作人": operator or "人工确认", "动作": action, "说明": note}
    if platform:
        history_item["平台"] = platform
        task["执行平台"] = platform
    history.append(history_item)
    task["审批状态"] = approval
    task["执行状态"] = execution
    task["最后处理"] = now
    task["处理说明"] = note
    task["处理记录"] = history
    save_execution_tasks(rows)
    return {"ok": True, "task": task, "tasks": rows, "message": note}


def execution_task_store_payload():
    rows = load_execution_tasks()
    return {"tasks": rows, "count": len(rows)}


def is_execution_task_api(path):
    return path == "/api/strategy-execution-tasks"


def is_execution_task_store_api(path):
    return path == "/api/strategy-execution-task-store"


def is_execution_task_action_api(path):
    return path == "/api/strategy-execution-task-action"


def data_status():
    full_files = [FULL_STRATEGY_DIR / name for name in FULL_STRATEGY_FILES]
    full_existing = [path for path in full_files if path.exists()]
    return {
        "page": {
            "label": "当前页面状态",
            "exists": False,
            "size": 0,
            "updated": "",
            "note": "浏览器内已载入的数据和筛选条件，只在页面端清空。",
        },
        "fullStrategy": {
            "label": "全量分析结果",
            "exists": bool(full_existing),
            "size": sum(path.stat().st_size for path in full_existing),
            "updated": int(max((path.stat().st_mtime for path in full_existing), default=0)) if full_existing else "",
            "note": "系统生成的策略CSV和报告，可重新载入全量新数据生成。",
        },
        "metadata": {
            "label": "策略元数据",
            **file_status(FULL_STRATEGY_METADATA_FILE),
            "note": "系统优先读取的结构化版本、日期、口径和来源说明。",
        },
        "routeCache": {
            "label": "航线联网缓存",
            **file_status(CACHE_FILE),
            "note": "已补录的公开航班供给缓存；清空后下次会重新查找或回到内置参考。",
        },
        "inventory": {
            "label": "库存录入",
            **file_status(INVENTORY_FILE),
            "note": "页面录入的锁座、已售、成本和售价记录。",
        },
        "executionTasks": {
            "label": "策略执行任务池",
            **file_status(EXECUTION_TASK_FILE),
            "note": "本地生成的策略执行任务，主文件为 strategy_execution_tasks.json。",
        },
        "operationCenter": {
            "label": "运营中心台账",
            **file_status(OPERATION_CENTER_FILE),
            "note": "运营中心订单、切位、出票、售后、支付、政策和接口台账。",
        },
        "auditLogs": {
            "label": "审计日志",
            **file_status(AUDIT_LOG_FILE),
            "note": "账号、授权和执行任务操作留痕；默认不纳入页面清空。",
        },
        "accessControl": {
            "label": "权限账号与授权",
            **file_status(ACCESS_CONTROL_FILE),
            "note": "管理员密码、员工账号、访客授权和当前登录会话；高风险项，清空后恢复本地默认管理员密码。",
        },
    }


def clear_data_targets(targets):
    allowed = {"fullStrategy", "metadata", "routeCache", "inventory", "executionTasks", "auditLogs", "accessControl"}
    unknown = sorted(set(targets) - allowed)
    if unknown:
        raise ValueError(f"不支持清空这些项目：{', '.join(unknown)}")

    cleared = []

    def unlink_system_file(path, target, label=None):
        allowed_paths = {item.resolve() for item in SYSTEM_CLEAR_FILE_ALLOWLIST}
        if path.resolve() not in allowed_paths:
            raise ValueError("数据清理只允许删除系统生成文件，不允许删除原始数据源。")
        if path.exists():
            path.unlink()
            cleared.append({"target": target, "file": label or path.name})

    if "fullStrategy" in targets:
        for name in FULL_STRATEGY_FILES:
            path = FULL_STRATEGY_DIR / name
            unlink_system_file(path, "fullStrategy", name)
    if "metadata" in targets:
        unlink_system_file(FULL_STRATEGY_METADATA_FILE, "metadata")
    if "routeCache" in targets:
        unlink_system_file(CACHE_FILE, "routeCache")
    if "inventory" in targets:
        unlink_system_file(INVENTORY_FILE, "inventory")
    if "executionTasks" in targets:
        unlink_system_file(EXECUTION_TASK_FILE, "executionTasks")
    if "auditLogs" in targets:
        unlink_system_file(AUDIT_LOG_FILE, "auditLogs")
    if "accessControl" in targets:
        unlink_system_file(ACCESS_CONTROL_FILE, "accessControl")
        load_access_control()
    return {"ok": True, "cleared": cleared, "status": data_status()}


def normalize_route(route):
    route = route.strip().upper().replace(" ", "")
    return route if "-" in route else route[:3] + "-" + route[3:]


def route_variants(route):
    route = normalize_route(route)
    origin, dest = route.split("-", 1)
    origins = CITY_AIRPORTS.get(origin, [origin])
    dests = CITY_AIRPORTS.get(dest, [dest])
    variants = [f"{o}-{d}" for o in origins for d in dests]
    return [item for item in variants if item != route]


def lookup_schedule(route):
    route = normalize_route(route)
    cache = load_route_cache()
    direct = cache.get(route) or ROUTE_SCHEDULES.get(route) or PUBLIC_ROUTE_FACTS.get(route)
    if direct:
        return direct
    origin, dest = route.split("-", 1)
    reverse_route = f"{dest}-{origin}"
    reverse = cache.get(reverse_route) or ROUTE_SCHEDULES.get(reverse_route) or PUBLIC_ROUTE_FACTS.get(reverse_route)
    if not reverse:
        return None
    data = json.loads(json.dumps(reverse, ensure_ascii=False))
    data["route"] = route
    data["sourceMode"] = "反向航线推断"
    data["sourceNote"] = f"未找到 {route} 的结构化公开数据，已使用反向航线 {reverse_route} 的航司/机型/班次作为供给参考。实际拿位前请以航司报价或GDS确认。{reverse.get('sourceNote', '')}"
    data["sources"] = reverse.get("sources", [])
    return data


def combined_city_schedule(route, refresh=False):
    route = normalize_route(route)
    schedules = []
    for variant in route_variants(route):
        schedule = lookup_schedule(variant)
        if refresh and not schedule:
            try:
                schedule = fetch_public_schedule(variant)
            except Exception:
                schedule = None
        if schedule and schedule.get("airlines"):
            schedules.append(schedule)

    if not schedules:
        return None

    airlines = []
    sources = []
    notes = []
    for schedule in schedules:
        for row in schedule["airlines"]:
            item = row.copy()
            item["航司"] = f"{item['航司']} ({schedule['route']})"
            airlines.append(item)
        sources.extend(schedule.get("sources", []))
        notes.append(f"{schedule['route']}：{schedule.get('sourceNote', '')}")

    return {
        "route": route,
        "sourceNote": "城市代码已自动展开并合并实际机场组合。" + " ".join(notes),
        "marketRoundTripUsd": round(sum(s.get("marketRoundTripUsd", 220) for s in schedules) / len(schedules)),
        "airlines": airlines,
        "sources": sources,
        "cached": True,
        "sourceMode": "城市机场组合",
    }


def github_static_route_schedule(route, attempts=None):
    route = normalize_route(route)
    origin, dest = route.split("-", 1)
    cache = load_route_cache()
    req = urllib.request.Request(GITHUB_ROUTE_DATA_URL, headers={"User-Agent": "Mozilla/5.0"})
    payload = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", errors="ignore")
    route_data = json.loads(payload)

    origin_data = route_data.get(origin, {})
    route_row = next((row for row in origin_data.get("routes", []) if row.get("iata") == dest), None)
    matched_route = route
    inferred_reverse = False

    if not route_row:
        reverse_data = route_data.get(dest, {})
        route_row = next((row for row in reverse_data.get("routes", []) if row.get("iata") == origin), None)
        matched_route = f"{dest}-{origin}"
        inferred_reverse = bool(route_row)

    if not route_row:
        raise ValueError(f"GitHub静态公开航线未命中 {route}")

    carriers = route_row.get("carriers") or []
    if not carriers:
        carriers = [{"iata": "", "name": "待补录航司"}]
    per_airline = max(1, round(7 / max(len(carriers), 1)))
    airlines = []
    for carrier in carriers:
        code = (carrier.get("iata") or "").strip()
        name = (carrier.get("name") or "待补录航司").strip()
        display_name = f"{name} / {code}" if code else name
        airlines.append({
            "航司": display_name,
            "代码": code,
            "机型": "待核实",
            "座位": 170,
            "每周班次": per_airline,
            "定位": "GitHub静态公开航线",
        })

    distance = route_row.get("km")
    minutes = route_row.get("min")
    detail = []
    if distance:
        detail.append(f"距离约{distance}公里")
    if minutes:
        detail.append(f"飞行时间约{minutes}分钟")
    detail_text = "，".join(detail)
    reverse_text = "；使用反向航线推断" if inferred_reverse else ""
    attempt_text = ""
    if attempts:
        failed = "；".join([f"第{item['try']}次 {item['status']}" for item in attempts])
        attempt_text = f" 公开网页补录失败后启用GitHub兜底：{failed}"

    data = {
        "route": route,
        "sourceNote": (
            f"GitHub静态公开航线命中 {matched_route}{reverse_text}；"
            f"包含航司和航线距离/时长参考{('，' + detail_text) if detail_text else ''}。"
            "该数据不代表实时班期，周班次按静态兜底估算，控位前仍需用航司报价表/GDS/OAG/Cirium校准。"
            + attempt_text
        ),
        "marketRoundTripUsd": 220,
        "airlines": airlines,
        "sources": [
            {"name": "GitHub Jonty airline-route-data", "url": "https://github.com/Jonty/airline-route-data"},
            {"name": "Raw airline_routes.json", "url": GITHUB_ROUTE_DATA_URL},
        ],
        "cached": True,
        "sourceMode": "GitHub静态公开航线",
        "attempts": attempts or [],
    }
    cache[route] = data
    save_route_cache(cache)
    return data


def fetch_public_schedule(route):
    route = normalize_route(route)
    cache = load_route_cache()
    if route in PUBLIC_ROUTE_FACTS:
        data = PUBLIC_ROUTE_FACTS[route].copy()
        data["cached"] = True
        data["sourceMode"] = "公开源补录"
        cache[route] = data
        save_route_cache(cache)
        return data

    urls = [
        f"https://www.flightsfrom.com/{route}",
        f"https://www.directflights.com/{route}",
        f"https://www.flightconnections.com/flights-from-{route.split('-')[0].lower()}-to-{route.split('-')[1].lower()}",
    ]
    attempts = []
    html = ""
    url = urls[0]
    for idx, candidate in enumerate(urls, start=1):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
            lowered = html.lower()
            if "just a moment" in lowered or "cloudflare" in lowered:
                raise ValueError("公开网站触发 Cloudflare/浏览器验证，无法由本地程序直接解析")
            if "403 forbidden" in lowered:
                raise ValueError("公开网站返回 403，拒绝自动抓取")
            if len(html) < 300:
                raise ValueError("页面内容过短，可能被限制访问")
            url = candidate
            attempts.append({"try": idx, "url": candidate, "status": "成功获取页面"})
            break
        except Exception as exc:
            attempts.append({"try": idx, "url": candidate, "status": f"失败：{exc}"})
    else:
        detail = "；".join([f"第{a['try']}次 {a['status']}" for a in attempts])
        try:
            return github_static_route_schedule(route, attempts=attempts)
        except Exception as github_exc:
            raise ValueError(f"暂时无法联网补录 {route}，已尝试3次。{detail}；GitHub静态兜底失败：{github_exc}")

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    no_direct = "no direct" in text.lower() or "no non-stop" in text.lower()
    flights = re.search(r"Flights per week\s*([0-9]+)", text, re.I)
    weekly_flights = int(flights.group(1)) if flights else 0
    airline_names = [
        "China Southern", "China Eastern", "Air China", "Spring Airlines", "Shanghai Airlines",
        "Juneyao Airlines", "Thai Airways", "Thai Vietjet", "Jeju Air", "Korean Air",
        "Asiana Airlines", "Cathay Pacific", "Hong Kong Airlines", "Air Macau",
    ]
    found = [name for name in airline_names if name.lower() in text.lower()]
    if not found and no_direct:
        airlines = []
    else:
        per_airline = max(1, round((weekly_flights or 7) / max(len(found), 1)))
        airlines = [
            {"航司": name, "代码": "", "机型": "待核实", "座位": 170, "每周班次": per_airline, "定位": "公开源识别"}
            for name in found
        ]

    data = {
        "route": route,
        "sourceNote": "自动联网补录自公开航班源；机型如显示待核实，建议用航司官网/OAG/Cirium或报价表校准。" if airlines else "公开源未识别到直飞航司，可能无直飞或页面限制。",
        "marketRoundTripUsd": 220,
        "airlines": airlines,
        "sources": [{"name": f"FlightsFrom {route}", "url": url}],
        "cached": True,
        "sourceMode": "联网抓取",
        "attempts": attempts,
    }
    if not airlines:
        detail = "；".join([f"第{a['try']}次 {a['status']}" for a in attempts])
        data["sourceNote"] += f" 补录过程：{detail}"
    cache[route] = data
    save_route_cache(cache)
    return data


def route_market(route):
    parts = route.split("-")
    origin, dest = (parts + ["", ""])[:2]
    regions = {AIRPORT_REGION.get(origin, "其他"), AIRPORT_REGION.get(dest, "其他")}

    if regions == {"韩国", "日本"}:
        return {
            "市场类型": "日韩短线高频",
            "外部热度": "高",
            "竞争强度": "高",
            "锁座系数": 0.95,
            "外部判断": "日韩短线通常频次高、替代航班多，适合滚动锁座和临近控价。",
        }
    if "中国" in regions and (regions & {"韩国", "日本"}):
        return {
            "市场类型": "日韩/中国短线",
            "外部热度": "中高",
            "竞争强度": "高",
            "锁座系数": 0.88,
            "外部判断": "中日韩短线受航季、节假日和团队需求影响明显；包机通常提前一个航季确定，切位至少提前3个月启动控位。",
        }
    if "北美" in regions:
        return {
            "市场类型": "长航程远程",
            "外部热度": "中",
            "竞争强度": "中",
            "锁座系数": 0.55,
            "外部判断": "远程航线波动和资金占用更高，锁座宜保守，重点保护高价窗口。",
        }
    if "欧洲" in regions:
        return {
            "市场类型": "欧洲长线/中转",
            "外部热度": "中高",
            "竞争强度": "中",
            "锁座系数": 0.58,
            "外部判断": "欧洲长线受签证、会展和中转供给影响明显，适合分批锁座并强化高价窗口验证。",
        }
    if "中东" in regions:
        return {
            "市场类型": "中东中转枢纽",
            "外部热度": "中高",
            "竞争强度": "高",
            "锁座系数": 0.62,
            "外部判断": "中东枢纽航线中转替代多，价格弹性强，适合航司对照和滚动补位。",
        }
    if "澳新" in regions:
        return {
            "市场类型": "澳新长线休闲",
            "外部热度": "中",
            "竞争强度": "中",
            "锁座系数": 0.52,
            "外部判断": "澳新长线资金占用高且旺淡季明显，应以旺季前置测试和低库存保护为主。",
        }
    if "南亚" in regions:
        return {
            "市场类型": "南亚价格敏感",
            "外部热度": "中",
            "竞争强度": "中高",
            "锁座系数": 0.6,
            "外部判断": "南亚航线价格敏感且中转替代多，适合小批量试单和快速调价。",
        }
    if regions & {"泰国", "马来西亚", "新加坡"}:
        return {
            "市场类型": "东南亚休闲/中转",
            "外部热度": "中高",
            "竞争强度": "中高",
            "锁座系数": 0.75,
            "外部判断": "东南亚航线休闲和中转需求明显，适合旺季前置锁座、淡季快速周转。",
        }
    if regions == {"韩国"}:
        return {
            "市场类型": "韩国国内/区域",
            "外部热度": "中",
            "竞争强度": "高",
            "锁座系数": 0.65,
            "外部判断": "区域短线价格敏感，锁座以小批量高周转为主。",
        }
    return {
        "市场类型": "区域补充航线",
        "外部热度": "中",
        "竞争强度": "中",
        "锁座系数": 0.6,
        "外部判断": "样本量和外部确定性有限，建议先小批量验证再扩大锁座。",
    }


def procurement_control_period(route, market):
    route = normalize_route(route)
    origin, dest = route.split("-", 1)
    regions = {AIRPORT_REGION.get(origin, "其他"), AIRPORT_REGION.get(dest, "其他")}
    market_type = market.get("市场类型", "")
    if "日韩" in market_type or ("中国" in regions and (regions & {"韩国", "日本"})):
        return {
            "周期": "包机：提前一个航季；切位：至少提前3个月",
            "包机": "提前一个航季确定",
            "切位": "至少提前3个月启动",
            "航季": "夏秋航季约3月最后一个周日至10月最后一个周六；冬春航季约10月最后一个周日至次年3月最后一个周六",
            "说明": "日韩/中国短线按航季换班和团队需求前置控位；具体仍以航司报价、航班计划和实际销售节奏校准。",
        }
    if market_type in ["东南亚休闲/中转", "区域补充航线"]:
        return {
            "周期": "旺季：提前2-3个月；平季：提前1-2个月滚动控位",
            "包机": "视旺季和团队量提前一个销售季评估",
            "切位": "建议提前2-3个月启动",
            "航季": "参考夏秋/冬春航季，但以目的地旺淡季和航司报价为准",
            "说明": "区域和休闲航线先按旺淡季前置控位，再用销售转化滚动调整。",
        }
    return {
        "周期": "先提前1-2个月小批量验证，确认供给和转化后滚动控位",
        "包机": "需结合航司报价和团队需求另行评估",
        "切位": "建议提前1-2个月试单",
        "航季": "参考夏秋/冬春航季，实际以航司计划和报价为准",
        "说明": "样本或供给不确定时，不建议一次性重仓控位。",
    }


def load_inventory():
    if not INVENTORY_FILE.exists():
        return []
    try:
        data = json.loads(INVENTORY_FILE.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_inventory(rows):
    INVENTORY_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")


def number_value(value, default=0):
    try:
        if value in [None, ""]:
            return default
        numeric = float(value)
        return numeric if math.isfinite(numeric) else default
    except Exception:
        return default


def normalized_excel_name(value):
    return re.sub(r"[\s_\-/（）()]+", "", str(value or "").strip().lower())


def pick_excel_column(raw, label, candidates, required=True):
    normalized_columns = {normalized_excel_name(col): col for col in raw.columns}
    for candidate in candidates:
        key = normalized_excel_name(candidate)
        if key in normalized_columns:
            return normalized_columns[key]
    for col in raw.columns:
        key = normalized_excel_name(col)
        if any(normalized_excel_name(candidate) in key for candidate in candidates):
            return col
    if required:
        raise ValueError(f"无法自动识别{label}字段，请确认 Excel 中包含相关列。")
    return None


HOLIDAY_PERIODS = [
    ("元旦", "2024-01-01", "2024-01-01"),
    ("春节", "2024-02-10", "2024-02-17"),
    ("清明", "2024-04-04", "2024-04-06"),
    ("五一", "2024-05-01", "2024-05-05"),
    ("端午", "2024-06-08", "2024-06-10"),
    ("中秋", "2024-09-15", "2024-09-17"),
    ("国庆", "2024-10-01", "2024-10-07"),
    ("元旦", "2025-01-01", "2025-01-01"),
    ("春节", "2025-01-28", "2025-02-04"),
    ("清明", "2025-04-04", "2025-04-06"),
    ("五一", "2025-05-01", "2025-05-05"),
    ("端午", "2025-05-31", "2025-06-02"),
    ("国庆/中秋", "2025-10-01", "2025-10-08"),
    ("元旦", "2026-01-01", "2026-01-03"),
    ("春节", "2026-02-16", "2026-02-23"),
    ("清明", "2026-04-04", "2026-04-06"),
    ("五一", "2026-05-01", "2026-05-05"),
    ("端午", "2026-06-19", "2026-06-21"),
    ("中秋", "2026-09-25", "2026-09-27"),
    ("国庆", "2026-10-01", "2026-10-07"),
]


def price_factor_notes(sales_day=None, departure_day=None, lead_days=None):
    notes = []
    sales_day = pd.Timestamp(sales_day).normalize() if pd.notna(sales_day) else None
    departure_day = pd.Timestamp(departure_day).normalize() if pd.notna(departure_day) else None

    for name, start, end in HOLIDAY_PERIODS:
        start_day = pd.Timestamp(start)
        end_day = pd.Timestamp(end)
        for label, day in [("出票日", sales_day), ("起飞日", departure_day)]:
            if day is None:
                continue
            if start_day <= day <= end_day:
                notes.append(f"{label}处于{name}假期")
            elif start_day - pd.Timedelta(days=3) <= day < start_day:
                notes.append(f"{label}为{name}前{int((start_day - day).days)}天")

    if departure_day is not None and departure_day.weekday() in [4, 5, 6]:
        notes.append("起飞日接近/落在周末")
    if sales_day is not None and sales_day.weekday() in [4, 5, 6]:
        notes.append("出票日接近/落在周末")
    if departure_day is not None and departure_day.month in [7, 8]:
        notes.append("暑期旺季出行")
    if lead_days is not None and number_value(lead_days, -1) <= 1:
        notes.append("临近起飞，余位稀缺时具备高价测试条件")

    deduped = []
    for note in notes:
        if note not in deduped:
            deduped.append(note)
    return "；".join(deduped)


def rhythm_price_reason(bucket, action, bucket_avg, bucket_high, test_price, evidence_factor):
    notes = []
    if evidence_factor:
        notes.append(evidence_factor)
    if bucket_avg and bucket_high and bucket_high > test_price * 1.8:
        notes.append("历史最高价明显偏离窗口均价，按单点证据复盘，不直接用于执行价")
    if action == "高价测试/控量保价":
        notes.append("该窗口为单张收益最高窗口，适合小库存控量测试")
    elif action == "主推成交":
        notes.append("该窗口综合销量和价格更稳定，适合作为主推成交段")
    elif action == "余位放量":
        notes.append("该窗口历史销量集中，适合承接放量或清库存")
    else:
        notes.append("未命中主卖/放量/高价核心窗口，先观察转化")
    return "；".join(notes)


def date_factor_multiplier(factor_text):
    if not factor_text:
        return 1.0
    multiplier = 1.0
    if "处于" in factor_text and "假期" in factor_text:
        multiplier *= 1.22
    if "前" in factor_text:
        multiplier *= 1.12
    if "周末" in factor_text:
        multiplier *= 1.06
    if "暑期" in factor_text:
        multiplier *= 1.08
    if "临近起飞" in factor_text:
        multiplier *= 1.08
    return min(multiplier, 1.45)


def date_level_action(base_action, factor_text, bucket, high_window, volume_window, remaining, daily_seats, day):
    if factor_text and ("假期" in factor_text or "国庆" in factor_text or "春节" in factor_text or "五一" in factor_text):
        if bucket == high_window:
            return "节假日高价控量"
        return "节假日提价观察"
    if factor_text and "临近起飞" in factor_text:
        if remaining > daily_seats * 0.45:
            return "临近清仓放量"
        return "临近余位控价"
    if remaining > daily_seats * 0.45 and day <= 4 and bucket == volume_window:
        return "临近放量清库存"
    return base_action


def cycle_pressure_multiplier(lead_days):
    lead_days = max(0, int(number_value(lead_days, 0)))
    if lead_days <= 1:
        return 1.65
    if lead_days <= 4:
        return 1.45
    if lead_days <= 9:
        return 1.25
    if lead_days <= 14:
        return 1.12
    if lead_days <= 21:
        return 1.0
    if lead_days <= 30:
        return 0.9
    if lead_days <= 45:
        return 0.75
    return 0.55


def today_decision_action(lead_days, factor_text, sell_count, daily_seats):
    if lead_days < 0:
        return "已起飞，不可售"
    if factor_text and ("假期" in factor_text or "国庆" in factor_text or "春节" in factor_text or "五一" in factor_text):
        return "节假日高价控量"
    if factor_text and ("暑期" in factor_text or "周末" in factor_text):
        return "旺季小步提价"
    if lead_days > 45:
        return "长周期早鸟试探"
    if lead_days > 21:
        return "中周期观察转化"
    if sell_count >= max(1, round(daily_seats * 0.08)):
        return "加速成交"
    return "小量测试"


def weekday_cn(day):
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return names[pd.Timestamp(day).weekday()]


def build_today_decisions(
    route,
    departure_dates,
    decision_ts,
    daily_seats,
    fallback_price,
    calc_by_bucket,
    high_window,
    main_window,
    volume_window,
    cost=0,
    inventory_by_departure=None,
):
    decisions = []
    for flight_date in departure_dates:
        flight_ts = pd.Timestamp(flight_date).normalize()
        available_seats = int((inventory_by_departure or {}).get(flight_ts.date().isoformat(), daily_seats))
        lead_days = int((flight_ts - decision_ts).days)
        if lead_days < 0:
            decisions.append({
                "航线": route,
                "决策日期": decision_ts.date().isoformat(),
                "起飞日期": flight_ts.date().isoformat(),
                "起飞日": weekday_cn(flight_ts),
                "距起飞天数": f"D{lead_days}",
                "剩余销售周期": "已过起飞日",
                "当日可售座位": available_seats,
                "提前窗口": "不可售",
                "当日建议张数": 0,
                "建议售价": 0,
                "预计销售收入": 0,
                "预计毛利": None,
                "动作": "已起飞，不可售",
                "日期因素": "起飞日早于决策日",
                "策略原因": "该航班已经过起飞日，不再生成销售建议。",
            })
            continue

        bucket = bucket_lead(lead_days)
        bucket_row = calc_by_bucket.get(bucket, {})
        hist_qty = int(sales_quantity_value(bucket_row))
        hist_avg = number_value(bucket_row.get("均价"), fallback_price)
        if not hist_avg:
            hist_avg = fallback_price
        factor_text = price_factor_notes(decision_ts, flight_ts, lead_days)
        factor_multiplier = date_factor_multiplier(factor_text)
        remaining_days = max(1, lead_days)
        base_daily_need = available_seats / remaining_days
        pressure = cycle_pressure_multiplier(lead_days)
        history_strength = 1.0
        if bucket == volume_window:
            history_strength *= 1.18
        if bucket == main_window:
            history_strength *= 1.1
        if bucket == high_window and bucket != volume_window:
            history_strength *= 0.82
        if factor_text:
            history_strength *= min(factor_multiplier, 1.28)
        suggested = round(base_daily_need * pressure * history_strength)
        if lead_days > 45:
            cap = max(1, round(available_seats * 0.03))
        elif lead_days > 30:
            cap = max(2, round(available_seats * 0.05))
        elif lead_days > 21:
            cap = max(3, round(available_seats * 0.08))
        elif lead_days > 9:
            cap = max(5, round(available_seats * 0.12))
        else:
            cap = max(8, round(available_seats * 0.2))
        sell_count = max(1 if lead_days >= 0 else 0, min(cap, suggested))

        if bucket == high_window:
            price_base = max(hist_avg, fallback_price * 1.08)
        elif bucket == main_window:
            price_base = hist_avg * 1.02
        elif bucket == volume_window:
            price_base = hist_avg * 0.96
        else:
            price_base = hist_avg
        price = round(max(price_base, hist_avg * factor_multiplier))
        if lead_days > 45 and "假期" not in (factor_text or ""):
            price = round(max(hist_avg, price * 0.98))
        revenue = int(sell_count * price)
        gross_profit = int(sell_count * (price - cost)) if cost else None
        action = today_decision_action(lead_days, factor_text, sell_count, available_seats)
        factor_note = factor_text or "普通销售日，未命中特殊节假日/周末/暑期因子"
        decisions.append({
            "航线": route,
            "决策日期": decision_ts.date().isoformat(),
            "起飞日期": flight_ts.date().isoformat(),
            "起飞日": weekday_cn(flight_ts),
            "距起飞天数": f"D-{lead_days}",
            "剩余销售周期": f"{lead_days}天",
            "当日可售座位": available_seats,
            "提前窗口": bucket,
            "历史窗口销量": hist_qty,
            "历史窗口均价": round(hist_avg, 2),
            "当日建议张数": sell_count,
            "建议售价": price,
            "预计销售收入": revenue,
            "预计毛利": gross_profit,
            "动作": action,
            "日期因素": factor_note,
            "策略原因": (
                f"{decision_ts.date().isoformat()}销售{flight_ts.date().isoformat()}航班，真实提前{lead_days}天，"
                f"起飞日{weekday_cn(flight_ts)}；按{bucket}历史窗口均价{round(hist_avg, 2)}、"
                f"剩余周期日均压力{round(base_daily_need, 2)}座、日期系数{round(factor_multiplier, 2)}，"
                f"今日建议卖{sell_count}张，售价{price}。"
            ),
        })
    return decisions


def build_decision_calendar(
    route,
    departure_dates,
    first_decision_ts,
    daily_seats,
    fallback_price,
    calc_by_bucket,
    high_window,
    main_window,
    volume_window,
    cost=0,
    inventory_by_departure=None,
):
    """Generate the operator's day-by-day selling playbook.

    Each decision date answers: on this sales day, which future departure
    inventory is still sellable and what should be sold today.
    """
    departure_days = [pd.Timestamp(item).normalize() for item in departure_dates]
    if not departure_days:
        return []
    last_departure = max(departure_days)
    last_decision_ts = max(first_decision_ts, last_departure - pd.Timedelta(days=1))
    calendar = []
    for decision_ts in pd.date_range(first_decision_ts, last_decision_ts, freq="D"):
        sellable_departures = [day for day in departure_days if day > decision_ts]
        decisions = build_today_decisions(
            route,
            sellable_departures,
            pd.Timestamp(decision_ts).normalize(),
            daily_seats,
            fallback_price,
            calc_by_bucket,
            high_window,
            main_window,
            volume_window,
            cost,
            inventory_by_departure,
        )
        calendar.append({
            "决策日期": pd.Timestamp(decision_ts).date().isoformat(),
            "可售起飞开始": sellable_departures[0].date().isoformat() if sellable_departures else "",
            "可售起飞结束": sellable_departures[-1].date().isoformat() if sellable_departures else "",
            "可售起飞天数": len(sellable_departures),
            "decisions": decisions,
        })
    return calendar


def source_excel_paths_from_manifest():
    manifest = read_result_csv("file_manifest.csv")
    if manifest.empty or "file" not in manifest.columns:
        return []
    paths = []
    for value in manifest["file"].dropna().tolist():
        path = Path(str(value)).expanduser()
        if path.exists() and path.suffix.lower() in [".xlsx", ".xls"]:
            paths.append(path)
    return list(dict.fromkeys(paths))


def actual_sales_for_review_date(route, review_date, departure_start="", departure_end=""):
    route = normalize_route(route)
    review_ts = pd.to_datetime(review_date, errors="coerce")
    if pd.isna(review_ts):
        review_ts = pd.Timestamp.today().normalize()
    else:
        review_ts = review_ts.normalize()
    start_ts = pd.to_datetime(departure_start, errors="coerce")
    end_ts = pd.to_datetime(departure_end, errors="coerce")
    rows = []
    for path in source_excel_paths_from_manifest():
        try:
            raw = pd.read_excel(path, sheet_name=0)
            sales_date_col = pick_excel_column(raw, "销售/出票日期", ["操作时间", "出票日期", "销售日期", "下单日期", "订单日期", "创建时间", "支付时间"])
            amount_col = pick_excel_column(raw, "票价/金额", ["款项金额", "航司售价", "销售价", "票价", "成交价", "实收金额", "订单金额", "结算金额"])
            route_col = pick_excel_column(raw, "航线", ["起飞-到达", "航程", "航线", "航段", "OD"])
            departure_col = pick_excel_column(raw, "起飞时间", ["起飞时间/航班号", "起飞时间", "航班日期", "起飞日期", "出发时间", "航班时间"])
            flight_col = pick_excel_column(raw, "航班号", ["起飞时间/航班号", "航班号", "航班"], required=False)
            type_col = pick_excel_column(raw, "款项/产品类型", ["款项类型", "产品类型", "业务类型", "订单类型"], required=False)
        except Exception:
            continue

        df = raw.copy()
        df["_route"] = df[route_col].astype(str).str.strip().str.upper().apply(normalize_route)
        df["_amount"] = pd.to_numeric(df[amount_col], errors="coerce")
        df["_sales_day"] = pd.to_datetime(df[sales_date_col], errors="coerce").dt.normalize()
        df["_departure_day"] = pd.to_datetime(df[departure_col].astype(str).str[:19], errors="coerce").dt.normalize()
        df["_flight"] = df[flight_col].astype(str).str.strip() if flight_col else ""
        if type_col and df[type_col].astype(str).str.strip().eq("出票").any():
            df = df[df[type_col].astype(str).str.strip().eq("出票")]
        df = df[
            df["_route"].eq(route)
            & df["_sales_day"].eq(review_ts)
            & (df["_departure_day"] > review_ts)
            & (df["_amount"] > 0)
            & df["_departure_day"].notna()
        ].copy()
        if pd.notna(start_ts):
            df = df[df["_departure_day"] >= start_ts.normalize()]
        if pd.notna(end_ts):
            df = df[df["_departure_day"] <= end_ts.normalize()]
        if df.empty:
            continue
        grouped = df.groupby("_departure_day").agg(
            qty=("_amount", "size"),
            avg=("_amount", "mean"),
            high=("_amount", "max"),
            revenue=("_amount", "sum"),
            flights=("_flight", lambda values: "、".join([item for item in list(dict.fromkeys(values.astype(str)))[:3] if item])),
        )
        for day, item in grouped.iterrows():
            rows.append({
                "复盘日期": review_ts.date().isoformat(),
                "起飞日期": pd.Timestamp(day).date().isoformat(),
                "起飞日": weekday_cn(day),
                "提前天数": f"D-{int((pd.Timestamp(day) - review_ts).days)}",
                "实际出票": int(item["qty"]),
                "实际均价": round(float(item["avg"]), 2),
                "实际最高价": round(float(item["high"]), 2),
                "实际销售收入": round(float(item["revenue"]), 2),
                "航班样本": item["flights"],
            })
    return sorted(rows, key=lambda item: item["起飞日期"])


def nightly_sales_review(
    route,
    review_date="",
    seats=40,
    departure_date="",
    cost=0,
    departure_end="",
    flights_per_day=1,
    seats_per_flight=0,
    airline="",
    flight_no="",
    horizon_days=0,
    model_source_mode="mixedForecast",
    actual_inventory=0,
):
    review_ts = pd.to_datetime(review_date, errors="coerce")
    if pd.isna(review_ts):
        review_ts = pd.Timestamp.today().normalize()
    else:
        review_ts = review_ts.normalize()
    current_plan = sales_cycle_plan(
        route=route,
        seats=seats,
        departure_date=departure_date,
        cost=cost,
        departure_end=departure_end,
        flights_per_day=flights_per_day,
        seats_per_flight=seats_per_flight,
        airline=airline,
        flight_no=flight_no,
        horizon_days=horizon_days,
        model_source_mode=model_source_mode,
        decision_date=review_ts.date().isoformat(),
        actual_inventory=actual_inventory,
    )
    active_calendar = (current_plan.get("decisionCalendar") or [{}])[0]
    planned_rows = active_calendar.get("decisions") or current_plan.get("todayDecisions") or []
    actual_rows = actual_sales_for_review_date(
        current_plan["route"],
        review_ts.date().isoformat(),
        current_plan["departureDate"],
        current_plan["departureEndDate"],
    )
    actual_by_departure = {row["起飞日期"]: row for row in actual_rows}
    review_rows = []
    for planned in planned_rows:
        actual = actual_by_departure.get(planned["起飞日期"], {})
        planned_count = int(number_value(planned.get("当日建议张数"), 0))
        actual_count = int(number_value(actual.get("实际出票"), 0))
        delta = actual_count - planned_count
        if actual_count <= 0 and planned_count > 0:
            conclusion = "未动销，次日优先观察渠道和价格，必要时小幅降价或加投放"
        elif delta >= 0:
            conclusion = "达到或超过建议，次日可控量并试探提价"
        elif actual_count < planned_count * 0.5:
            conclusion = "明显低于建议，次日降低转化门槛并检查渠道曝光"
        else:
            conclusion = "略低于建议，次日维持主推价并补投放"
        review_rows.append({
            "复盘日期": review_ts.date().isoformat(),
            "起飞日期": planned["起飞日期"],
            "起飞日": planned.get("起飞日", ""),
            "提前天数": planned.get("距起飞天数", ""),
            "建议张数": planned_count,
            "建议售价": planned.get("建议售价", 0),
            "实际出票": actual_count,
            "实际均价": actual.get("实际均价", 0),
            "实际销售收入": actual.get("实际销售收入", 0),
            "差异张数": delta,
            "复盘结论": conclusion,
        })

    next_day = review_ts + pd.Timedelta(days=1)
    refreshed_plan = sales_cycle_plan(
        route=route,
        seats=seats,
        departure_date=current_plan["departureDate"],
        cost=cost,
        departure_end=current_plan["departureEndDate"],
        flights_per_day=flights_per_day,
        seats_per_flight=seats_per_flight,
        airline=airline,
        flight_no=flight_no,
        horizon_days=horizon_days,
        model_source_mode=model_source_mode,
        decision_date=next_day.date().isoformat(),
        actual_inventory=actual_inventory,
    )
    payload = {
        "route": current_plan["route"],
        "reviewDate": review_ts.date().isoformat(),
        "nextDecisionDate": next_day.date().isoformat(),
        "actualRows": actual_rows,
        "reviewRows": review_rows,
        "refreshedPlan": refreshed_plan,
        "basis": [
            f"复盘口径：读取系统已有销售数据来源，只统计 {review_ts.date().isoformat()} 当天出票且起飞日晚于复盘日的未来库存。",
            f"刷新口径：复盘完成后，从 {next_day.date().isoformat()} 开始重新生成剩余可售起飞日的销售决策日历。",
            "如果当日真实出票数据尚未导入，实际出票会显示为0；导入当天销售数据后再次复盘即可更新。",
        ],
    }
    NIGHTLY_REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    NIGHTLY_REVIEW_FILE.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def route_sales_history_frame(route):
    route = normalize_route(route)
    frames = []
    for path in source_excel_paths_from_manifest():
        try:
            raw = pd.read_excel(path, sheet_name=0)
            sales_date_col = pick_excel_column(raw, "销售/出票日期", ["操作时间", "出票日期", "销售日期", "下单日期", "订单日期", "创建时间", "支付时间"])
            amount_col = pick_excel_column(raw, "票价/金额", ["款项金额", "航司售价", "销售价", "票价", "成交价", "实收金额", "订单金额", "结算金额"])
            route_col = pick_excel_column(raw, "航线", ["起飞-到达", "航程", "航线", "航段", "OD"])
            departure_col = pick_excel_column(raw, "起飞时间", ["起飞时间/航班号", "起飞时间", "航班日期", "起飞日期", "出发时间", "航班时间"])
            type_col = pick_excel_column(raw, "款项/产品类型", ["款项类型", "产品类型", "业务类型", "订单类型"], required=False)
        except Exception:
            continue
        df = raw.copy()
        df["_route"] = df[route_col].astype(str).str.strip().str.upper().apply(normalize_route)
        df["_amount"] = pd.to_numeric(df[amount_col], errors="coerce")
        df["_sales_day"] = pd.to_datetime(df[sales_date_col], errors="coerce").dt.normalize()
        df["_departure_day"] = pd.to_datetime(df[departure_col].astype(str).str[:19], errors="coerce").dt.normalize()
        if type_col and df[type_col].astype(str).str.strip().eq("出票").any():
            df = df[df[type_col].astype(str).str.strip().eq("出票")]
        df = df[
            df["_route"].eq(route)
            & (df["_amount"] > 0)
            & df["_sales_day"].notna()
            & df["_departure_day"].notna()
            & (df["_departure_day"] >= df["_sales_day"])
        ].copy()
        if df.empty:
            continue
        df["_lead_days"] = (df["_departure_day"] - df["_sales_day"]).dt.days
        df["_bucket"] = df["_lead_days"].apply(bucket_lead)
        frames.append(df[["_sales_day", "_departure_day", "_lead_days", "_bucket", "_amount"]])
    if not frames:
        return pd.DataFrame(columns=["_sales_day", "_departure_day", "_lead_days", "_bucket", "_amount"])
    return pd.concat(frames, ignore_index=True)


def rolling_history_speed(history_df, bucket, departure_day, fallback_speed=0):
    if history_df.empty or not bucket:
        return round(number_value(fallback_speed, 0), 2)
    departure_ts = pd.to_datetime(departure_day, errors="coerce")
    bucket_df = history_df[history_df["_bucket"].eq(bucket)].copy()
    if pd.notna(departure_ts):
        prior = bucket_df[bucket_df["_departure_day"] < departure_ts.normalize()]
    else:
        prior = bucket_df
    grouped = prior.groupby("_departure_day").size().sort_index()
    if len(grouped):
        per_flight = grouped.tail(3) / max(1, bucket_day_count(bucket))
        return round(float(per_flight.mean()), 2)
    grouped_all = bucket_df.groupby("_departure_day").size().sort_index()
    if len(grouped_all):
        per_flight = grouped_all / max(1, bucket_day_count(bucket))
        return round(float(per_flight.mean()), 2)
    return round(number_value(fallback_speed, 0), 2)


def actual_speed_nd(history_df, sale_date, days=7):
    if history_df.empty:
        return 0
    sale_ts = pd.to_datetime(sale_date, errors="coerce")
    if pd.isna(sale_ts):
        return 0
    days = max(1, int(number_value(days, 7)))
    start_ts = sale_ts.normalize() - pd.Timedelta(days=days)
    end_ts = sale_ts.normalize() - pd.Timedelta(days=1)
    recent = history_df[
        (history_df["_sales_day"] >= start_ts)
        & (history_df["_sales_day"] <= end_ts)
        & (history_df["_departure_day"] >= sale_ts.normalize())
    ]
    return round(len(recent) / days, 2)


def actual_speed_7d(history_df, sale_date):
    return actual_speed_nd(history_df, sale_date, 7)


def adjustment_policy(pressure_index):
    p = number_value(pressure_index, 0)
    if p >= 1.5:
        return "严重积压", "立即降价", -10, "-8% ~ -12%", "高"
    if p >= 1.2:
        return "偏慢", "降价测试", -5, "-3% ~ -5%", "高"
    if p > 0.8:
        return "正常", "维持现价", 0, "0%", "中"
    if p > 0.5:
        return "偏快", "小幅提价", 3, "+3% ~ +5%", "中"
    return "很快", "提价或控量", 6, "+5% ~ +8%", "低（慎用）"


def lead_days_from_label(value):
    match = re.search(r"-?\d+", str(value or ""))
    return abs(int(match.group(0))) if match else 0


def build_price_adjustment_report_html(payload):
    rows = payload.get("rows", [])
    summary = payload.get("summary", {})
    comparison = payload.get("comparison", {})
    control_group = payload.get("control_group", {})
    experiment_group = payload.get("experiment_group", {})
    def esc(value):
        return html.escape(str(value if value is not None else ""))
    table_rows = "\n".join(
        "<tr>"
        + "".join(f"<td>{esc(row.get(col, ''))}</td>" for col in [
            "销售日期", "起飞日期", "提前天数", "剩余库存R", "S_history", "S_actual_3d", "S_actual_7d",
            "动销趋势", "库存压力P", "库存压力等级", "建议动作", "建议调价幅度",
            "原建议售价", "建议调后价", "成本线意见", "执行确认问题", "可写入位置",
        ])
        + "</tr>"
        for row in rows[:300]
    )
    cards = "".join(
        f"<div class='card'><span>{esc(key)}</span><b>{esc(value)}</b></div>"
        for key, value in summary.items()
    )
    comparison_rows = [
        ("总收入", control_group.get("total_revenue"), experiment_group.get("total_revenue"), f"{comparison.get('revenue_change_percent', 0)}%"),
        ("总利润", control_group.get("total_profit"), experiment_group.get("total_profit"), f"{comparison.get('profit_change_percent')}%" if comparison.get("profit_change_percent") is not None else "未填成本底线"),
        ("售罄率", control_group.get("sell_out_rate"), experiment_group.get("sell_out_rate"), f"{comparison.get('sell_out_rate_change', 0)}个百分点"),
        ("尾仓损失估算", "", experiment_group.get("tail_loss"), "起飞前7天未售库存×成本底线"),
        ("低于成本待确认", "", experiment_group.get("below_cost_count"), "需人工确认"),
    ]
    comparison_html = "\n".join(
        f"<tr><td>{esc(label)}</td><td>{esc(control)}</td><td>{esc(experiment)}</td><td>{esc(change)}</td></tr>"
        for label, control, experiment, change in comparison_rows
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{esc(payload.get('route'))} 动态调价建议与回测报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; margin: 28px; color: #172033; background: #f5f7fb; }}
    h1 {{ margin: 0 0 8px; color: #0d3b66; }}
    .note {{ color: #5b667a; margin-bottom: 18px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .card {{ background: white; border: 1px solid #dde5f0; border-radius: 14px; padding: 14px; box-shadow: 0 8px 24px rgba(16, 44, 84, .06); }}
    .card span {{ display: block; color: #69758a; font-size: 12px; }}
    .card b {{ display: block; margin-top: 6px; font-size: 20px; }}
    .comparison {{ margin: 18px 0; background: white; border: 1px solid #f0c8c8; border-radius: 14px; padding: 14px; }}
    .comparison h2 {{ margin: 0 0 10px; color: #c02626; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 14px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #e6edf5; padding: 9px 10px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eaf2fb; color: #0d3b66; position: sticky; top: 0; }}
    .footer {{ margin-top: 18px; color: #68758a; }}
  </style>
</head>
<body>
  <h1>{esc(payload.get('route'))} 动态调价建议与回测报告</h1>
  <div class="note">本报告为新增“调价建议层/回测层”，不自动改写每日建议售价，不自动上架，不自动调价；执行前需要人工确认。</div>
  <div class="cards">{cards}</div>
  <section class="comparison">
    <h2>对照组 vs 实验组对比摘要（新增待确认）</h2>
    <table>
      <thead><tr><th>指标</th><th>对照组</th><th>实验组</th><th>变化/说明</th></tr></thead>
      <tbody>{comparison_html}</tbody>
    </table>
  </section>
  <table>
    <thead>
      <tr>
        <th>销售日期</th><th>起飞日期</th><th>提前天数</th><th>剩余库存R</th><th>S_history</th><th>S_actual_3d</th><th>S_actual_7d</th>
        <th>动销趋势</th><th>库存压力P</th><th>库存压力等级</th><th>建议动作</th><th>建议调价幅度</th><th>原建议售价</th><th>建议调后价</th>
        <th>成本线意见</th><th>执行确认问题</th><th>可写入位置</th>
      </tr>
    </thead>
    <tbody>{table_rows}</tbody>
  </table>
  <div class="footer">{esc('；'.join(payload.get('basis', [])))}</div>
</body>
</html>
"""


def import_price_adjustment_rules(payload, session, ip=""):
    if not session or session.get("role") != "admin":
        raise PermissionError("需要管理员登录后导入回测规则。")
    report_id = str(payload.get("reportId") or payload.get("jsonPath") or "").strip()
    route = normalize_route(payload.get("route", ""))
    rules = payload.get("rules") if isinstance(payload.get("rules"), list) else []
    if not report_id:
        raise ValueError("缺少回测报告ID或JSON路径。")
    if not route:
        raise ValueError("缺少航线。")
    if not rules:
        raise ValueError("缺少可导入规则摘要。")

    AI_SUGGESTION_DIR.mkdir(parents=True, exist_ok=True)
    suggestion_file = AI_SUGGESTION_DIR / "price_adjustment_rules.json"
    existing = load_json_file(suggestion_file, [])
    if not isinstance(existing, list):
        existing = []
    actor, role = session_actor(session)
    record = {
        "id": f"price_rule_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}",
        "type": "price_adjustment_backtest_rule",
        "status": "待人工复核",
        "route": route,
        "reportId": report_id,
        "rules": rules,
        "note": "仅写入建议池，不写售价、不写库存、不自动上架、不自动调价。",
        "createdAt": pd.Timestamp.now().isoformat(),
        "createdBy": actor,
    }
    existing.insert(0, record)
    suggestion_file.write_text(json.dumps(json_safe(existing[:200]), ensure_ascii=False, indent=2), "utf-8")
    append_audit_log(actor, role, "导入回测规则至建议池", route, "成功", f"reportId={report_id}; rules={len(rules)}", ip)
    return {"ok": True, "record": record, "path": str(suggestion_file)}


def price_adjustment_backtest(
    route,
    seats=40,
    departure_date="",
    cost=0,
    departure_end="",
    flights_per_day=1,
    seats_per_flight=0,
    airline="",
    flight_no="",
    horizon_days=0,
    model_source_mode="mixedForecast",
    decision_date="",
    actual_inventory=0,
    cost_floor=0,
):
    route = normalize_route(route)
    cost_floor = number_value(cost_floor, 0) or number_value(cost, 0) or (850 if route == "PKX-CJU" else 0)
    plan = sales_cycle_plan(
        route=route,
        seats=seats,
        departure_date=departure_date,
        cost=cost,
        departure_end=departure_end,
        flights_per_day=flights_per_day,
        seats_per_flight=seats_per_flight,
        airline=airline,
        flight_no=flight_no,
        horizon_days=horizon_days,
        model_source_mode=model_source_mode,
        decision_date=decision_date,
        actual_inventory=actual_inventory,
    )
    history_df = route_sales_history_frame(route)
    calc_df = read_result_csv("bucket_detail.csv")
    route_calc = calc_df[calc_df["航线"] == route].copy() if not calc_df.empty and "航线" in calc_df.columns else pd.DataFrame()
    calc_by_bucket = {row["提前分段"]: row for row in clean_records(route_calc)} if not route_calc.empty else {}
    actual_qty_lookup = {}
    actual_amount_lookup = {}
    if not history_df.empty:
        actual_qty_lookup = {
            (pd.Timestamp(idx[0]).date().isoformat(), pd.Timestamp(idx[1]).date().isoformat()): int(value)
            for idx, value in history_df.groupby(["_sales_day", "_departure_day"]).size().items()
        }
        actual_amount_lookup = {
            (pd.Timestamp(idx[0]).date().isoformat(), pd.Timestamp(idx[1]).date().isoformat()): float(value)
            for idx, value in history_df.groupby(["_sales_day", "_departure_day"])["_amount"].mean().items()
        }

    rows = []
    control_revenue = 0
    experiment_revenue = 0
    control_profit = 0
    experiment_profit = 0
    executable_count = 0
    confirm_count = 0
    for item in plan.get("rows", []):
        bucket = item.get("提前窗口", "")
        sale_date = item.get("销售日期", "")
        departure_day = item.get("起飞日期", "")
        lead_days = lead_days_from_label(item.get("提前天数", ""))
        remaining = number_value(item.get("售后剩余"), 0)
        if remaining <= 0:
            remaining = number_value(item.get("当日可售座位"), 0)
        fallback_speed = sales_quantity_value(calc_by_bucket.get(bucket, {})) / max(1, bucket_day_count(bucket))
        s_history = rolling_history_speed(history_df, bucket, departure_day, fallback_speed)
        s_actual_3d = actual_speed_nd(history_df, sale_date, 3)
        s_actual = actual_speed_7d(history_df, sale_date)
        trend_direction = calc_trend_direction(s_actual_3d, s_actual)
        pressure_index = round((remaining / max(1, lead_days)) / max(0.01, s_history), 2)
        advice = calc_pressure_level(pressure_index, trend_direction, s_actual_3d, s_history)
        level = advice["pressure_level"]
        action = advice["suggested_action"]
        pct = advice["suggested_change_percent"]
        pct_range = advice["suggested_change_range"]
        priority = advice["priority"]
        original_price = number_value(item.get("建议售价"), 0)
        adjusted_price = round(original_price * (1 + pct / 100)) if original_price else 0
        suggested_qty = number_value(item.get("建议销售张数"), 0)
        lookup_key = (sale_date, departure_day)
        simulated_qty = actual_qty_lookup.get(lookup_key, suggested_qty)
        control_price = actual_amount_lookup.get(lookup_key, original_price)
        below_cost_floor = bool(cost_floor and adjusted_price < cost_floor)
        cost_note = "未设置成本底线，仅输出调价建议。"
        executable = "待人工确认"
        if cost_floor:
            if below_cost_floor:
                cost_note = f"建议调后价低于成本底线{round(cost_floor)}，需确认是否按清仓/止损执行；如不执行，可将保护价写为{round(cost_floor)}。"
                executable = "需人工确认"
                confirm_count += 1
            else:
                cost_note = f"建议调后价不低于成本底线{round(cost_floor)}，可进入策略执行任务复核。"
                executable = "建议可执行"
                executable_count += 1
        else:
            confirm_count += 1
        control_revenue += simulated_qty * control_price
        experiment_revenue += simulated_qty * adjusted_price
        if cost_floor:
            control_profit += simulated_qty * (control_price - cost_floor)
            experiment_profit += simulated_qty * (adjusted_price - cost_floor)
        rows.append({
            "航线": route,
            "销售日期": sale_date,
            "起飞日期": departure_day,
            "提前天数": item.get("提前天数", ""),
            "剩余库存R": round(remaining),
            "距离起飞D": lead_days,
            "S_history": s_history,
            "S_actual_3d": s_actual_3d,
            "S_actual_7d": s_actual,
            "动销趋势": trend_direction,
            "库存压力P": pressure_index,
            "库存压力等级": level,
            "建议动作": action,
            "建议调价幅度": pct_range,
            "建议调价百分比": pct,
            "原建议售价": round(original_price),
            "对照组售价": round(control_price),
            "建议调后价": adjusted_price,
            "模拟销量": round(simulated_qty),
            "执行判断": executable,
            "优先级": priority,
            "判定说明": advice.get("note", ""),
            "below_cost_floor": below_cost_floor,
            "成本线意见": cost_note,
            "执行确认问题": f"是否同意 {sale_date} 销售 {departure_day} 航班按“{action} / {pct_range}”处理？",
            "可写入位置": "自动执行中台 > 策略执行任务：targetPrice=建议调后价，protectPrice=成本底线或人工确认价；OTA执行前二次确认。",
        })

    profit_lift = None
    if cost_floor and control_profit:
        profit_lift = round((experiment_profit - control_profit) / abs(control_profit) * 100, 2)
    revenue_lift = round((experiment_revenue - control_revenue) / control_revenue * 100, 2) if control_revenue else 0
    comparison_payload = apply_advice_to_backtest(rows, cost_floor)
    payload = {
        "route": route,
        "generatedAt": pd.Timestamp.now().isoformat(),
        "costFloor": round(cost_floor) if cost_floor else None,
        "reportScope": "阶段A+B：结构化调价建议 + 保守回测；不改每日建议售价公式。",
        "summary": {
            "建议条数": len(rows),
            "建议可执行": executable_count,
            "需人工确认": confirm_count,
            "对照组收入": round(control_revenue),
            "实验组收入": round(experiment_revenue),
            "收入变化": f"{revenue_lift}%",
            "利润变化": f"{profit_lift}%" if profit_lift is not None else "未填成本底线",
            "低于成本待确认": comparison_payload["experiment_group"].get("below_cost_count", 0),
        },
        "basis": [
            "P=(R/D)/S_history；R 取模型行的售后剩余或当日可售座位，D 取提前天数。",
            "S_history 优先按同提前期分段 + 最近3个已起飞航班滚动平均；不足时回退到本航线同窗口历史平均，再回退到 bucket_detail.csv。",
            "S_actual_3d 与 S_actual_7d 用于判断动销趋势；本版不处理退票二次销售。",
            "对照组优先使用历史真实售价+历史真实销量；没有同销售日/起飞日样本时，销量回退到当前模型建议张数，售价回退到系统建议售价。",
            "本功能只新增调价建议层和回测层，不自动改每日建议售价，不自动上架或调价。",
        ],
        "rows": rows,
        **comparison_payload,
    }
    PRICE_ADJUSTMENT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"price_adjustment_{route}_{stamp}"
    json_path = PRICE_ADJUSTMENT_DIR / f"{base_name}.json"
    html_path = PRICE_ADJUSTMENT_DIR / f"{base_name}.html"
    json_path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(build_price_adjustment_report_html(payload), encoding="utf-8")
    payload["jsonPath"] = str(json_path)
    payload["htmlPath"] = str(html_path)
    return payload


def high_price_context_from_manifest(manifest_df):
    """Build route/window historical high-price evidence without mutating source Excel files."""
    if manifest_df.empty or "file" not in manifest_df.columns:
        return {}
    evidence = {}
    source_paths = []
    for value in manifest_df["file"].dropna().tolist():
        path = Path(str(value)).expanduser()
        if path.exists() and path.suffix.lower() in [".xlsx", ".xls"]:
            source_paths.append(path)

    for path in dict.fromkeys(source_paths):
        try:
            raw = pd.read_excel(path, sheet_name=0)
            sales_date_col = pick_excel_column(raw, "销售/出票日期", ["操作时间", "出票日期", "销售日期", "下单日期", "订单日期", "创建时间", "支付时间"])
            amount_col = pick_excel_column(raw, "票价/金额", ["款项金额", "航司售价", "销售价", "票价", "成交价", "实收金额", "订单金额", "结算金额"])
            route_col = pick_excel_column(raw, "航线", ["起飞-到达", "航程", "航线", "航段", "OD"])
            departure_col = pick_excel_column(raw, "起飞时间", ["起飞时间/航班号", "起飞时间", "航班日期", "起飞日期", "出发时间", "航班时间"])
            flight_col = pick_excel_column(raw, "航班号", ["起飞时间/航班号", "航班号", "航班"], required=False)
            type_col = pick_excel_column(raw, "款项/产品类型", ["款项类型", "产品类型", "业务类型", "订单类型"], required=False)
        except Exception:
            continue

        df = raw.copy()
        df["_route"] = df[route_col].astype(str).str.strip().str.upper()
        df["_amount"] = pd.to_numeric(df[amount_col], errors="coerce")
        df["_sales_date"] = pd.to_datetime(df[sales_date_col], errors="coerce").dt.normalize()
        df["_departure_date"] = pd.to_datetime(df[departure_col].astype(str).str[:19], errors="coerce")
        df["_departure_day"] = df["_departure_date"].dt.normalize()
        df["_lead"] = (df["_departure_day"] - df["_sales_date"]).dt.days
        df["_bucket"] = df["_lead"].apply(bucket_lead)
        df["_flight"] = df[flight_col].astype(str).str.strip() if flight_col else ""
        if type_col and df[type_col].astype(str).str.strip().eq("出票").any():
            df = df[df[type_col].astype(str).str.strip().eq("出票")]
        df = df[df["_route"].ne("") & (df["_amount"] > 0) & df["_sales_date"].notna() & df["_bucket"].notna()].copy()
        if df.empty:
            continue

        for (route, bucket), group in df.groupby(["_route", "_bucket"], dropna=False):
            if not route or not bucket:
                continue
            top = group.sort_values(["_amount", "_sales_date"], ascending=[False, True]).iloc[0]
            top_price = round(float(top["_amount"]))
            top_day = top["_sales_date"]
            start_day = top_day - pd.Timedelta(days=3)
            end_day = top_day + pd.Timedelta(days=3)
            context = group[(group["_sales_date"] >= start_day) & (group["_sales_date"] <= end_day)].copy()
            daily = context.groupby("_sales_date").agg(
                qty=("_amount", "size"),
                avg=("_amount", "mean"),
                high=("_amount", "max"),
            ).to_dict("index")
            day_parts = []
            for offset in range(-3, 4):
                day = top_day + pd.Timedelta(days=offset)
                item = daily.get(day)
                if item:
                    day_parts.append(f"{day.strftime('%m-%d')} {int(item['qty'])}张/均{round(float(item['avg']))}/高{round(float(item['high']))}")
                else:
                    day_parts.append(f"{day.strftime('%m-%d')} 0张")
            flight = str(top.get("_flight") or "").strip()
            factor = price_factor_notes(top_day, top.get("_departure_day"), top.get("_lead"))
            evidence[(route, bucket)] = {
                "price": top_price,
                "factor": factor,
                "text": (
                    f"{top_day.strftime('%Y-%m-%d')}出票，{top['_departure_date'].strftime('%Y-%m-%d %H:%M') if pd.notna(top['_departure_date']) else '起飞时间未知'}起飞，"
                    f"航班{flight or '未填'}，提前{int(top['_lead'])}天，历史最高{top_price}；"
                    f"{'因素：' + factor + '；' if factor else ''}"
                    f"前后3天同窗口：{'；'.join(day_parts)}。"
                ),
            }
    return evidence


def sales_quantity_value(row, default=0):
    if not isinstance(row, dict):
        return default
    for key in ["销售数量", "出票量", "真实销售张数", "有效出票", "总销售数量"]:
        if key in row:
            return number_value(row.get(key), default)
    return default


def row_for_route(rows, route):
    return next((row for row in rows if row.get("航线") == route), None)


def risk_level(score):
    if score >= 75:
        return "高风险"
    if score >= 48:
        return "中风险"
    return "低风险"


def window_score(model_window, actual_window):
    if not model_window or not actual_window:
        return None
    if model_window == actual_window:
        return 100
    if model_window in BUCKETS and actual_window in BUCKETS:
        distance = abs(BUCKETS.index(model_window) - BUCKETS.index(actual_window))
        if distance == 1:
            return 80
        if distance == 2:
            return 60
        return max(0, 45 - distance * 10)
    return 0


def value_accuracy(model_value, actual_value):
    model_value = number_value(model_value, 0)
    actual_value = number_value(actual_value, 0)
    if model_value <= 0 or actual_value <= 0:
        return None
    return max(0, round(100 - abs(actual_value - model_value) / model_value * 100))


def pct_deviation(model_value, actual_value):
    model_value = number_value(model_value, 0)
    actual_value = number_value(actual_value, 0)
    if model_value <= 0 or actual_value <= 0:
        return ""
    return f"{round((actual_value - model_value) / model_value * 100)}%"


def build_operating_layers(strategy_df, calc_df, airline_df, high_price_evidence=None):
    strategy_rows = clean_records(strategy_df)
    calc_rows = clean_records(calc_df)
    airline_rows = clean_records(airline_df)
    high_price_evidence = high_price_evidence or {}
    inventory_rows = load_inventory()
    risk_rows = []
    rhythm_rows = []
    airline_priority_rows = []
    calibration_rows = []
    inventory_alerts = []

    by_route_calc = {}
    for row in calc_rows:
        by_route_calc.setdefault(row.get("航线"), []).append(row)
    by_route_airline = {}
    for row in airline_rows:
        route = row.get("航线") or row.get("route")
        by_route_airline.setdefault(route, []).append(row)

    for row in strategy_rows:
        route = row.get("航线")
        valid = number_value(row.get("有效出票"))
        peak_qty = number_value(row.get("最多张数"))
        peak_share = peak_qty / valid if valid else 0
        backtest = row.get("模型回测", "")
        airline_list = by_route_airline.get(route, [])
        top_airline_qty = max([number_value(item.get("出票量")) for item in airline_list], default=0)
        concentration = top_airline_qty / valid if valid else 0
        sample_risk = 28 if valid < 80 else 16 if valid < 300 else 8 if valid < 1000 else 2
        model_risk = 30 if backtest == "偏离" else 18 if backtest == "高价命中" else 10 if backtest == "销量命中" else 4
        concentration_risk = 20 if concentration >= 0.85 else 12 if concentration >= 0.65 else 6
        window_risk = 16 if row.get("单张收益最高窗口") != row.get("张数最多窗口") else 5
        longhaul_risk = 10 if route_market(route)["市场类型"] in ["长航程远程", "欧洲长线/中转", "澳新长线休闲"] else 4
        score = min(100, round(sample_risk + model_risk + concentration_risk + window_risk + longhaul_risk))
        risk_rows.append({
            "航线": route,
            "数据来源": row.get("数据来源") or "自有导入数据",
            "风险等级": risk_level(score),
            "风险分": score,
            "样本风险": sample_risk,
            "模型偏差风险": model_risk,
            "航司集中风险": concentration_risk,
            "窗口分离风险": window_risk,
            "建议动作": "先小批量试单，库存日更，禁止一次性重仓。" if score >= 75 else "滚动锁座，每3天复盘转化和价格。" if score >= 48 else "可按建议节奏推进，保留高价窗口库存。",
        })

        high_window = row.get("单张收益最高窗口")
        main_window = row.get("建议主卖窗口")
        volume_window = row.get("张数最多窗口")
        route_high_avg = number_value(row.get("最高均价"))
        route_protect_price = round(route_high_avg * 0.82) if route_high_avg else ""
        for bucket in BUCKETS:
            route_bucket = next((item for item in by_route_calc.get(route, []) if item.get("提前分段") == bucket), {})
            bucket_avg = number_value(route_bucket.get("均价"))
            bucket_high = number_value(route_bucket.get("最高价"))
            protect_price = round(bucket_avg * 0.82) if bucket_avg else ""
            main_low = round(bucket_avg * 0.94) if bucket_avg else ""
            main_high = round(bucket_avg * 1.08) if bucket_avg else ""
            test_price = round(bucket_avg * 1.18) if bucket_avg else ""
            evidence = high_price_evidence.get((route, bucket), {})
            evidence_factor = evidence.get("factor", "")
            evidence_text = evidence.get("text") or (
                f"本窗口历史最高{round(bucket_high)}，缺少原始明细日期上下文。"
                if bucket_high else
                "无足够历史价格样本。"
            )
            if bucket_avg and bucket_high and bucket_high > test_price * 1.8:
                executable_price_source = f"可执行测试价按本窗口历史均价{round(bucket_avg)}×1.18={test_price}；历史最高{round(bucket_high)}判定为单点高价证据，不直接作为建议售价。"
            elif bucket_avg:
                executable_price_source = f"可执行测试价按本窗口历史均价{round(bucket_avg)}×1.18={test_price}。"
            else:
                executable_price_source = "无足够历史价格样本。"
            if bucket == high_window:
                action = "高价测试/控量保价"
            elif bucket == main_window:
                action = "主推成交"
            elif bucket == volume_window:
                action = "余位放量"
            else:
                action = "观察转化"
            price_reason = rhythm_price_reason(bucket, action, bucket_avg, bucket_high, test_price, evidence_factor)
            rhythm_rows.append({
                "航线": route,
                "提前窗口": bucket,
                "历史销量": route_bucket.get("销售数量", 0),
                "历史均价": route_bucket.get("均价", ""),
                "动作": action,
                "价格原因": price_reason,
                "保护价": protect_price,
                "主推价": f"{main_low}-{main_high}" if main_low else "",
                "可执行测试价": test_price,
                "执行价口径": executable_price_source,
                "历史高价证据": evidence_text,
                "销售说明": f"{bucket}执行{action}；主推价看{main_low}-{main_high}，可执行测试价不超过{test_price}。" if bucket_avg else f"{bucket}先观察，等待更多价格样本。",
            })

        sorted_airlines = sorted(airline_list, key=lambda item: number_value(item.get("出票量")), reverse=True)
        for idx, airline_row in enumerate(sorted_airlines[:4], start=1):
            qty = number_value(airline_row.get("出票量"))
            role = "主库存航司" if idx == 1 else "价格对照航司" if idx == 2 else "临近补位航司"
            airline_priority_rows.append({
                "航线": route,
                "优先级": idx,
                "航司": airline_row.get("航司"),
                "航班号样本": airline_row.get("航班号样本") or airline_row.get("航班样本") or "",
                "航班号数量": int(number_value(airline_row.get("航班号数量"), 0)),
                "历史出票": int(qty),
                "历史均价": round(number_value(airline_row.get("均价"))),
                "历史最高价": round(number_value(airline_row.get("最高价"))),
                "角色": role,
                "采购建议": f"优先谈{role}，报价低于保护价{route_protect_price or '待算'}时可放大；若报价接近窗口测试价，只做少量保护。",
            })

        model_hit = "完全命中" if main_window == volume_window == high_window else "销量命中" if main_window == volume_window else "高价命中" if main_window == high_window else "偏离"
        volume_score = window_score(main_window, volume_window)
        high_score = window_score(main_window, high_window)
        overall_score = round((volume_score or 0) * 0.55 + (high_score or 0) * 0.35 + 10)
        calibration_rows.append({
            "航线": route,
            "模型建议": main_window,
            "实际销量": volume_window,
            "实际高价": high_window,
            "销量窗口一致度": f"{volume_score}%" if volume_score is not None else "",
            "高价窗口一致度": f"{high_score}%" if high_score is not None else "",
            "综合一致度": f"{overall_score}%",
            "回测结论": row.get("模型回测") or model_hit,
            "校准方向": "维持当前权重" if model_hit in ["完全命中", "销量命中"] else "提高高价窗口权重" if model_hit == "高价命中" else "提高销量与稳定性权重",
            "下一版参数": "销量55%/价格35%/稳定性10%" if model_hit == "偏离" else "销量45%/价格45%/稳定性10%",
        })

    for item in inventory_rows:
        route = normalize_route(str(item.get("航线", ""))) if item.get("航线") else ""
        strategy = row_for_route(strategy_rows, route)
        locked = number_value(item.get("锁定位"))
        sold = number_value(item.get("已售"))
        remain = max(0, locked - sold)
        sell_rate = sold / locked if locked else 0
        current_window = item.get("当前窗口") or (strategy.get("建议主卖窗口") if strategy else "")
        if locked <= 0:
            alert = "未录入有效库存"
        elif sell_rate < 0.35 and current_window in ["2-4天", "1天"]:
            alert = "临近库存偏高，需要放量或降价测试"
        elif sell_rate > 0.85:
            alert = "销售快于预期，可补位或提价"
        elif strategy and current_window == strategy.get("单张收益最高窗口") and remain > 0:
            alert = "处于高价窗口，建议控量保价"
        else:
            alert = "库存节奏正常"
        inventory_alerts.append({
            "航线": route,
            "航司": item.get("航司", ""),
            "航班/日期": item.get("航班日期", ""),
            "锁定位": int(locked),
            "已售": int(sold),
            "剩余": int(remain),
            "销售率": f"{round(sell_rate * 100)}%",
            "成本价": item.get("成本价", ""),
            "销售价": item.get("销售价", ""),
            "当前窗口": current_window,
            "预计投放": item.get("预计投放", ""),
            "预警": alert,
        })

    external_api_specs = integration_blueprint()["apis"]

    return {
        "risk": risk_rows,
        "rhythm": rhythm_rows,
        "airlinePriority": airline_priority_rows,
        "calibration": calibration_rows,
        "inventory": inventory_rows,
        "inventoryAlerts": inventory_alerts,
        "externalApis": external_api_specs,
    }


def integration_blueprint():
    return {
        "modules": [
            {"模块": "数据接入", "职责": "统一接入内部销售、航司报价、GDS/航信、OTA价格库存、支付和订单数据。", "当前状态": "已预留", "后续接入": "携程、去哪儿、同程、飞猪、航司/GDS、支付流水"},
            {"模块": "策略引擎", "职责": "按航线/航司/航班号/起飞日期/库存生成价格、节奏、风险和执行建议。", "当前状态": "已具备本地模型", "后续接入": "实时市场价、余位、搜索热度、转化率"},
            {"模块": "执行中台", "职责": "把策略建议转换成上架、改价、关仓、放量、下架等策略执行任务。", "当前状态": "待接接口", "后续接入": "OTA商品/库存/价格API"},
            {"模块": "订单中心", "职责": "接收平台订单，统一订单号、旅客、价格、支付、出票和售后状态。", "当前状态": "已预留", "后续接入": "OTA订单推送、手工导入、Webhook"},
            {"模块": "支付回填", "职责": "匹配支付流水、到账、退款、手续费和订单利润。", "当前状态": "已预留", "后续接入": "微信/支付宝/银企/OTA结算单"},
            {"模块": "闭环校准", "职责": "把真实成交、未成交、库存余量、退改和利润回写模型，校准下一轮策略。", "当前状态": "已预留", "后续接入": "执行结果、成交漏斗、异常原因"},
        ],
        "apis": [
            {"接口": "OTA价格库存-携程", "方向": "双向", "建议字段": "渠道、商品ID、航线、航司、航班号、起飞日期、可售座位、当前售价、上下架状态", "状态": "预留适配器"},
            {"接口": "OTA价格库存-去哪儿", "方向": "双向", "建议字段": "渠道、产品ID、航线、航司、航班号、起飞日期、库存、价格、政策ID、上下架状态", "状态": "预留适配器"},
            {"接口": "OTA订单推送", "方向": "导入", "建议字段": "渠道订单号、内部订单号、旅客、航线、航班、起飞日期、成交价、支付状态、出票状态", "状态": "预留Webhook"},
            {"接口": "OTA执行回执", "方向": "导入", "建议字段": "执行任务ID、渠道、动作、执行状态、失败原因、执行前价格、执行后价格、执行时间", "状态": "预留Webhook"},
            {"接口": "航司报价/切位", "方向": "导入", "建议字段": "航线、航司、航班号、起飞日期、舱位、可切座位、成本价、退改规则、付款期限", "状态": "预留"},
            {"接口": "航信/GDS库存", "方向": "导入", "建议字段": "航线、航班号、起飞日期、舱位、余位、实时票价、税费、规则", "状态": "预留"},
            {"接口": "支付/结算回填", "方向": "导入", "建议字段": "支付流水号、渠道订单号、金额、支付时间、退款金额、手续费、到账状态", "状态": "预留"},
            {"接口": "策略执行输出", "方向": "导出", "建议字段": "任务ID、渠道、航线、航司、航班号、起飞日期、动作、目标库存、目标价格、保护价、执行窗口、审批状态", "状态": "预留"},
        ],
        "flow": [
            {"步骤": 1, "节点": "收数", "输入": "内部销售/航司报价/OTA市场价/GDS余位", "输出": "标准化航班库存与价格底表", "控制": "字段校验、重复订单过滤"},
            {"步骤": 2, "节点": "出策略", "输入": "历史销量、起飞区间、航司航班、成本和余位", "输出": "销售节奏、目标价、保护价、风险等级", "控制": "模型回测、库存风险阈值"},
            {"步骤": 3, "节点": "生成执行任务", "输入": "策略建议", "输出": "上架、改价、放量、关仓、下架任务", "控制": "人工审批/自动审批开关"},
            {"步骤": 4, "节点": "OTA执行", "输入": "执行任务", "输出": "执行回执、失败原因、渠道状态", "控制": "重试、限频、权限校验"},
            {"步骤": 5, "节点": "收单支付", "输入": "订单、支付、出票结果", "输出": "订单利润、库存扣减、异常单", "控制": "支付回填、退改签匹配"},
            {"步骤": 6, "节点": "闭环校准", "输入": "真实销量、价格、利润、失败原因", "输出": "模型命中率、参数调整建议", "控制": "按航线/航司/航班复盘"},
        ],
        "taskSchema": [
            {"字段": "taskId", "含义": "执行任务唯一编号", "示例": "TASK-20260603-0001"},
            {"字段": "channel", "含义": "执行渠道", "示例": "携程/去哪儿/手工"},
            {"字段": "action", "含义": "执行动作", "示例": "上架/改价/放量/关仓/下架"},
            {"字段": "route/airline/flightNo/departureDate", "含义": "单程航班库存定位字段", "示例": "BKK-KUL / 7C / 7C123 / 2026-06-10"},
            {"字段": "targetSeats/targetPrice/protectPrice", "含义": "目标库存、目标售价、保护价", "示例": "20 / 980 / 850"},
            {"字段": "approvalStatus", "含义": "审批状态", "示例": "待确认/已批准/自动执行/已驳回"},
            {"字段": "executeStatus", "含义": "执行状态", "示例": "待执行/执行中/成功/失败/需人工处理"},
        ],
        "sampleTasks": [
            {"任务ID": "TASK-DEMO-001", "渠道": "携程", "动作": "改价", "航线": "BKK-KUL", "航司": "7C", "航班号": "7C123", "起飞日期": "2026-06-10", "目标库存": 20, "目标售价": 980, "状态": "待接真实接口"},
            {"任务ID": "TASK-DEMO-002", "渠道": "去哪儿", "动作": "放量", "航线": "PKX-CJU", "航司": "9C", "航班号": "待填", "起飞日期": "2026-06-12", "目标库存": 15, "目标售价": 1160, "状态": "待接真实接口"},
        ],
    }


def summarize_generated_model(plan):
    rows = plan.get("rows", [])
    by_window = {}
    for row in rows:
        bucket = row.get("提前窗口") or ""
        item = by_window.setdefault(bucket, {"sales": 0, "revenue": 0, "prices": []})
        qty = number_value(row.get("建议销售张数"), 0)
        price = number_value(row.get("建议售价"), 0)
        revenue = number_value(row.get("预计销售收入"), 0)
        item["sales"] += qty
        item["revenue"] += revenue
        if price:
            item["prices"].append(price)
    if by_window:
        volume_window = max(by_window, key=lambda key: by_window[key]["sales"])
        high_window = max(
            by_window,
            key=lambda key: sum(by_window[key]["prices"]) / len(by_window[key]["prices"]) if by_window[key]["prices"] else 0,
        )
    else:
        volume_window = ""
        high_window = ""
    total_sales = sum(row.get("sales", 0) for row in by_window.values())
    total_revenue = sum(row.get("revenue", 0) for row in by_window.values())
    return {
        "销量窗口": volume_window,
        "高价窗口": high_window,
        "销售张数": round(total_sales),
        "销售收入": round(total_revenue),
        "数据来源": plan.get("modelSourceLabel") or "模拟生成模型",
    }


def actual_model_from_real_data(route, actual_source_mode="realImported", strategy_rows_override=None, calc_records_override=None, source_label_override=""):
    if strategy_rows_override is not None and calc_records_override is not None:
        strategy_rows = strategy_rows_override
        calc_df = pd.DataFrame(calc_records_override)
        if not strategy_rows:
            raise ValueError("指定真实Excel没有生成可用结果，请检查是否为销售数据表。")
    else:
        strategy_df = read_result_csv("route_strategy.csv")
        calc_df = read_result_csv("bucket_detail.csv")
        if strategy_df.empty:
            raise ValueError("还没有找到真实销售数据分析结果，请先载入真实已发生销售数据。")
        strategy_rows = clean_records(strategy_df)
    actual = row_for_route(strategy_rows, route)
    if not actual:
        raise ValueError(f"真实销售数据里没有找到 {route}，请确认校准航线和真实数据口径一致。")
    route_calc = calc_df[calc_df["航线"] == route].copy() if not calc_df.empty else pd.DataFrame()
    volume_window = actual.get("张数最多窗口") or actual.get("建议主卖窗口") or ""
    high_window = actual.get("单张收益最高窗口") or ""
    sales = number_value(actual.get("有效出票"), 0)
    price = number_value(actual.get("最高均价"), 0)
    revenue = round(sales * price) if sales and price else 0
    bucket_rows = []
    if not route_calc.empty:
        for row in clean_records(route_calc):
            bucket_rows.append({
                "提前窗口": row.get("提前分段"),
                "真实销售张数": sales_quantity_value(row),
                "真实均价": row.get("均价", ""),
                "真实最高价": row.get("最高价", ""),
            })
    source_label = {
        "realImported": "全量数据池 outputs/sales_strategy_all",
        "localActualExcel": "指定真实Excel",
        "manualActual": "本页手动录入真实结果",
    }.get(actual_source_mode, "全量数据池 outputs/sales_strategy_all")
    if source_label_override:
        source_label = source_label_override
    return {
        "summary": {
            "销量窗口": volume_window,
            "高价窗口": high_window,
            "销售张数": round(sales),
            "销售收入": round(revenue),
            "销售利润": "",
            "数据来源": source_label,
        },
        "bucketRows": bucket_rows,
    }


def actual_result_model_response(route, actual_source_mode="realImported", actual_volume_window="", actual_high_window="", actual_sales="", actual_revenue="", actual_profit=""):
    route = normalize_route(route)
    actual_data = actual_model_from_real_data(route, actual_source_mode)
    summary = actual_data["summary"]
    if actual_volume_window:
        summary["销量窗口"] = actual_volume_window
        summary["数据来源"] = "手动录入真实结果"
    if actual_high_window:
        summary["高价窗口"] = actual_high_window
        summary["数据来源"] = "手动录入真实结果"
    if number_value(actual_sales, 0):
        summary["销售张数"] = round(number_value(actual_sales, 0))
        summary["数据来源"] = "手动录入真实结果"
    if number_value(actual_revenue, 0):
        summary["销售收入"] = round(number_value(actual_revenue, 0))
        summary["数据来源"] = "手动录入真实结果"
    if number_value(actual_profit, 0):
        summary["销售利润"] = round(number_value(actual_profit, 0))
        summary["数据来源"] = "手动录入真实结果"
    return {
        "route": route,
        "actual": summary,
        "bucketRows": actual_data["bucketRows"],
        "basis": [
            f"真实结果取数位置：{summary['数据来源']}。",
            "该结果模型来自真实已发生销售数据分析；手动录入项只覆盖对应指标。",
        ],
    }


def model_calibration_compare(
    route,
    actual_volume_window="",
    actual_high_window="",
    actual_sales="",
    actual_revenue="",
    actual_profit="",
    model_source_mode="mixedForecast",
    actual_source_mode="realImported",
    horizon_days=0,
    departure_date="",
    departure_end="",
):
    route = normalize_route(route)
    strategy_df = read_result_csv("route_strategy.csv")
    if strategy_df.empty:
        raise ValueError("还没有找到模型策略结果，请先载入或生成销售数据分析。")

    strategy_rows = clean_records(strategy_df)
    generated_plan = sales_cycle_plan(
        route,
        departure_date=departure_date,
        departure_end=departure_end,
        horizon_days=horizon_days,
        model_source_mode=model_source_mode,
    )
    model_summary = summarize_generated_model(generated_plan)
    actual_data = actual_result_model_response(route, actual_source_mode, actual_volume_window, actual_high_window, actual_sales, actual_revenue, actual_profit)
    actual_summary = actual_data["actual"]

    model_volume_window = model_summary["销量窗口"]
    model_high_window = model_summary["高价窗口"]
    model_sales = number_value(model_summary["销售张数"], 0)
    model_revenue = number_value(model_summary["销售收入"], 0)
    model_profit = ""
    actual_volume_window = actual_summary["销量窗口"]
    actual_high_window = actual_summary["高价窗口"]
    actual_sales_value = number_value(actual_summary["销售张数"], 0)
    actual_revenue_value = number_value(actual_summary["销售收入"], 0)
    actual_profit_value = number_value(actual_summary.get("销售利润"), 0)
    model_basis = [
        f"预测模型取数位置：{model_summary['数据来源']}；模型周期提前{generated_plan.get('modelHorizonDays')}天至提前1天。",
        f"校准周期：起飞 {generated_plan.get('departureDate')} 至 {generated_plan.get('departureEndDate')}；提前周期 D-{generated_plan.get('modelHorizonDays')} 至 D-1。",
        f"真实结果取数位置：{actual_summary['数据来源']}；来自已发生销售数据分析结果，手动填写项会覆盖对应真实指标。",
        "校准含义：用预测/模拟生成的运营销售模型，对比真实已发生销售数据提炼出来的结果型模型。",
    ]

    volume_window_score = window_score(model_volume_window, actual_volume_window)
    high_window_score = window_score(model_high_window, actual_high_window)
    sales_accuracy = value_accuracy(model_sales, actual_sales_value)
    revenue_accuracy = value_accuracy(model_revenue, actual_revenue_value)
    profit_accuracy = value_accuracy(model_profit, actual_profit_value)
    source_looks_same = (
        model_summary["数据来源"] == actual_summary["数据来源"]
        or ("指定本地Excel" in str(model_summary["数据来源"]) and "指定真实Excel" in str(actual_summary["数据来源"]))
        or ("全量数据池" in str(actual_summary["数据来源"]) and ("指定本地Excel" in str(model_summary["数据来源"]) or "全量数据池" in str(model_summary["数据来源"])))
    )
    scale_looks_different = (
        model_sales > 0
        and actual_sales_value > 0
        and max(model_sales, actual_sales_value) / max(1, min(model_sales, actual_sales_value)) > 5
    ) or (
        model_revenue > 0
        and actual_revenue_value > 0
        and max(model_revenue, actual_revenue_value) / max(1, min(model_revenue, actual_revenue_value)) > 5
    )
    replay_only = source_looks_same or scale_looks_different

    weighted = []
    if replay_only:
        if volume_window_score is not None:
            weighted.append((volume_window_score, 0.50))
        if high_window_score is not None:
            weighted.append((high_window_score, 0.50))
    else:
        if volume_window_score is not None:
            weighted.append((volume_window_score, 0.28))
        if high_window_score is not None:
            weighted.append((high_window_score, 0.22))
        if sales_accuracy is not None:
            weighted.append((sales_accuracy, 0.22))
        if revenue_accuracy is not None:
            weighted.append((revenue_accuracy, 0.20))
        if profit_accuracy is not None:
            weighted.append((profit_accuracy, 0.08))
    if weighted:
        total_weight = sum(weight for _, weight in weighted)
        overall_score = round(sum(score * weight for score, weight in weighted) / total_weight)
    else:
        overall_score = 0

    if replay_only:
        score_label = "窗口自检一致度"
        if overall_score >= 85:
            conclusion = "同源窗口自检一致"
        elif overall_score >= 50:
            conclusion = "同源窗口部分一致"
        else:
            conclusion = "同源窗口自检偏离"
        tuning = "同源数据只能验证窗口提取是否一致；要做真实校准，需要按起飞日/销售周期切分预测样本和实际样本。"
        model_basis.append("当前属于同源/口径不一致回放：预测侧是按座位和起飞日生成的单次销售节奏模型，真实侧是已发生历史销售汇总；因此只做窗口自检，不用历史总销量/总收入拉低一致度。")
    elif overall_score >= 85:
        score_label = "综合一致度"
        conclusion = "高度一致"
        tuning = "维持当前权重，继续收集真实成交验证。"
    elif overall_score >= 65:
        score_label = "综合一致度"
        conclusion = "部分一致"
        tuning = "保留当前主逻辑，针对偏差项调高对应权重。"
    else:
        score_label = "综合一致度"
        conclusion = "偏差较大"
        tuning = "优先复盘真实数据口径、成本口径和市场供给，再调整模型权重。"

    scale_note = "不评估（预测为单次生成模型，真实为历史全量汇总）"
    compare_rows = [
        {"指标": "销量窗口", "预测模型口径": model_volume_window, "真实结果口径": actual_volume_window or "未填", "一致度": f"{volume_window_score}%" if volume_window_score is not None else "未评估", "偏差": ""},
        {"指标": "高价窗口", "预测模型口径": model_high_window, "真实结果口径": actual_high_window or "未填", "一致度": f"{high_window_score}%" if high_window_score is not None else "未评估", "偏差": ""},
        {"指标": "销售张数", "预测模型口径": round(model_sales), "真实结果口径": round(actual_sales_value) if actual_sales_value else "未填", "一致度": scale_note if replay_only else (f"{sales_accuracy}%" if sales_accuracy is not None else "未评估"), "偏差": "" if replay_only else pct_deviation(model_sales, actual_sales_value)},
        {"指标": "销售收入", "预测模型口径": round(model_revenue), "真实结果口径": round(actual_revenue_value) if actual_revenue_value else "未填", "一致度": scale_note if replay_only else (f"{revenue_accuracy}%" if revenue_accuracy is not None else "未评估"), "偏差": "" if replay_only else pct_deviation(model_revenue, actual_revenue_value)},
        {"指标": "销售利润", "预测模型口径": model_profit or "待接成本模型", "真实结果口径": round(actual_profit_value) if actual_profit_value else "未填", "一致度": f"{profit_accuracy}%" if profit_accuracy is not None else "未评估", "偏差": pct_deviation(model_profit, actual_profit_value)},
    ]

    return {
        "route": route,
        "overallScore": overall_score,
        "scoreLabel": score_label,
        "conclusion": conclusion,
        "tuning": tuning,
        "model": {
            "销量窗口": model_volume_window,
            "高价窗口": model_high_window,
            "销售张数": round(model_sales),
            "销售收入": round(model_revenue),
            "数据来源": model_summary["数据来源"],
        },
        "actual": {
            "销量窗口": actual_volume_window,
            "高价窗口": actual_high_window,
            "销售张数": round(actual_sales_value) if actual_sales_value else "",
            "销售收入": round(actual_revenue_value) if actual_revenue_value else "",
            "销售利润": round(actual_profit_value) if actual_profit_value else "",
            "数据来源": actual_summary["数据来源"],
        },
        "compareRows": compare_rows,
        "bucketRows": actual_data["bucketRows"],
        "basis": model_basis,
    }


def parse_seat_hint(value, default=10):
    text = str(value or "")
    nums = [int(item) for item in re.findall(r"\d+", text)]
    if not nums:
        return default
    return max(1, round(sum(nums) / len(nums)))


def current_strategy_version():
    metadata = load_json_file(FULL_STRATEGY_METADATA_FILE, {})
    if isinstance(metadata, dict):
        version = metadata.get("version", {})
        if isinstance(version, dict) and version.get("systemVersion"):
            return str(version.get("systemVersion"))
        if metadata.get("schemaVersion"):
            return str(metadata.get("schemaVersion"))
    strategy_status = file_status(FULL_STRATEGY_DIR / "route_strategy.csv")
    return f"local-{strategy_status.get('updated') or 'unknown'}"


def generate_execution_tasks(route="", channel="人工确认", limit=20):
    strategy_df = read_result_csv("route_strategy.csv")
    if strategy_df.empty:
        raise ValueError("还没有找到策略结果，请先载入或生成销售数据分析。")
    rows = clean_records(strategy_df)
    if route:
        target_route = normalize_route(route)
        rows = [row for row in rows if row.get("航线") == target_route]
    limit = max(1, min(100, int(number_value(limit, 20))))
    tasks = []
    today = pd.Timestamp.today().date().isoformat()
    current_ts = now_ts()
    strategy_version = current_strategy_version()
    for idx, row in enumerate(rows[:limit], start=1):
        route_code = row.get("航线")
        high_price = number_value(row.get("最高均价"), 0)
        self_high = number_value(row.get("自售最高价"), high_price)
        test_price = round(max(self_high, high_price * 1.12)) if high_price else ""
        main_price = round(high_price * 0.98) if high_price else ""
        protect_price = round(high_price * 0.82) if high_price else ""
        base_seats = parse_seat_hint(row.get("建议锁座"), max(5, round(number_value(row.get("有效出票"), 100) / 80)))
        task_base = {
            "渠道": channel,
            "航线": route_code,
            "航司": row.get("主要航司", "待填"),
            "航班号": "待填",
            "起飞日期": "待填",
            "保护价": protect_price,
            "审批状态": "待人工确认",
            "执行状态": "待执行",
            "生成日期": today,
            "schemaVersion": "1.0",
            "createdAt": current_ts,
            "updatedAt": current_ts,
            "sourceStrategyVersion": strategy_version,
            "依据": row.get("策略建议") or row.get("控价动作") or "模型策略生成",
        }
        actions = [
            ("改价", row.get("单张收益最高窗口"), max(1, round(base_seats * 0.25)), test_price, "高价窗口控量测试"),
            ("主推", row.get("建议主卖窗口"), max(1, round(base_seats * 0.55)), main_price, "主卖窗口集中成交"),
            ("放量", row.get("张数最多窗口"), max(1, round(base_seats * 0.40)), protect_price, "放量窗口清库存/促转化"),
        ]
        for action_idx, (action, window, seats, price, note) in enumerate(actions, start=1):
            task = dict(task_base)
            route_token = re.sub(r"[^A-Z0-9]+", "", str(route_code or "ROUTE"))
            task.update({
                "任务ID": f"TASK-{today.replace('-', '')}-{route_token}-{idx:03d}-{action_idx}",
                "动作": action,
                "执行窗口": window or "待确认",
                "目标库存": seats,
                "目标售价": price,
                "任务说明": note,
            })
            tasks.append(task)
    if tasks:
        saved = load_execution_tasks()
        existing_ids = {row.get("任务ID") for row in saved}
        new_tasks = [task for task in tasks if task.get("任务ID") not in existing_ids]
        saved.extend(new_tasks)
        save_execution_tasks(saved)
    else:
        new_tasks = []
    return {
        "channel": channel,
        "route": normalize_route(route) if route else "全部航线",
        "approvalMode": "人工确认",
        "count": len(new_tasks),
        "requestedCount": len(tasks),
        "skippedDuplicates": len(tasks) - len(new_tasks),
        "sourceStrategyVersion": strategy_version,
        "tasks": tasks,
        "allTasks": load_execution_tasks(),
        "notes": [
            "当前仅生成策略执行任务，不会自动调用OTA接口。",
            "同一策略版本、日期、航线、渠道和动作生成的任务会按任务ID防重复。",
            "真实接入携程/去哪儿后，任务需先经过人工确认，再交给平台适配器执行。",
            "任务按单程库存口径生成；同一航线后续通过航司、航班号、起飞日期区分。",
        ],
    }


def route_plan(route, strategy_rows=None, refresh=False):
    route = normalize_route(route)
    market = route_market(route)
    schedule = None
    fetch_error = ""
    if refresh:
        try:
            schedule = fetch_public_schedule(route)
        except Exception as exc:
            fetch_error = str(exc)
            schedule = None
    else:
        schedule = lookup_schedule(route)
    if not schedule or not schedule.get("airlines"):
        schedule = combined_city_schedule(route, refresh=refresh) or schedule
    if (not schedule or not schedule.get("airlines")) and not refresh:
        try:
            schedule = fetch_public_schedule(route)
        except Exception as exc:
            fetch_error = str(exc)
            schedule = schedule
        if not schedule or not schedule.get("airlines"):
            schedule = combined_city_schedule(route, refresh=True) or schedule
    airlines = schedule["airlines"] if schedule else []
    weekly_capacity = sum(item["座位"] * item["每周班次"] for item in airlines)

    internal = None
    if strategy_rows:
        internal = next((row for row in strategy_rows if row["航线"] == route), None)

    if internal:
        lock_base = internal["锁座基准"]
        main_window = internal["建议主卖窗口"]
        high_window = internal["单张收益最高窗口"]
        volume_window = internal["张数最多窗口"]
        target_price = internal.get("市场参考最高价") or internal.get("自售最高价") or round(number_value(internal.get("最高均价"), 900) * 1.12)
        basis = "使用内部历史出票数据 + 航线市场因子生成。"
    else:
        capacity_base = weekly_capacity or 240
        lock_base = round_seats(capacity_base * 0.045 * market["锁座系数"])
        main_window = "10-14天" if market["市场类型"] in ["东南亚休闲/中转", "区域补充航线"] else "5-9天"
        high_window = "15-21天" if market["市场类型"] == "东南亚休闲/中转" else "10-14天"
        volume_window = "2-4天"
        usd = schedule.get("marketRoundTripUsd", 220) if schedule else 220
        target_price = round(usd * 7.2 / 2 * 1.15)
        basis = "该航线暂未在内部出票明细中命中，使用公开航班供给 + 市场类型因子生成。"

    conservative = max(1, round_seats(lock_base * 0.7))
    recommended = max(conservative, round_seats(lock_base))
    aggressive = max(recommended, round_seats(lock_base * 1.35))

    if airlines:
        sorted_airlines = sorted(airlines, key=lambda x: x["座位"] * x["每周班次"], reverse=True)
        primary = sorted_airlines[0]
        secondary = sorted_airlines[1] if len(sorted_airlines) > 1 else None
        primary_seats = round_seats(recommended * 0.6)
        secondary_seats = recommended - primary_seats if secondary else 0
        airline_action = f"优先向{primary['航司']}控{primary_seats}座/周"
        if secondary:
            airline_action += f"，向{secondary['航司']}控{secondary_seats}座/周做价格对照。"
        else:
            airline_action += "。"
    else:
        airline_action = "未找到公开通飞航司数据，先按航司报价表补录后再拆分控位。"

    take_price = round(target_price * 0.68)
    ceiling_price = round(target_price * 0.78)
    sale_price = round(target_price * 1.08)
    control_period = procurement_control_period(route, market)

    if schedule:
        schedule_note = schedule["sourceNote"]
        source_mode = schedule.get("sourceMode", "内置/公开数据")
        sources = schedule["sources"]
    elif internal:
        schedule_note = "已使用内部历史出票数据生成采购策略；外部公开航班供给暂未补录成功，可后续用航司报价表或公开供给手动校准。"
        if fetch_error:
            schedule_note += f" 外部联网补录失败：{fetch_error}"
        source_mode = "内部历史出票数据"
        sources = []
    else:
        schedule_note = "联网补录失败：" + fetch_error if fetch_error else "自动联网未识别到可结构化的直飞供给。可能是公开网页限制、航线无直飞，或需要人工确认后补录。"
        source_mode = "未识别"
        sources = []

    return {
        "route": route,
        "market": market,
        "basis": basis,
        "airlines": airlines,
        "weeklyCapacity": weekly_capacity,
        "lockSeats": {"保守": conservative, "推荐": recommended, "激进": aggressive},
        "windows": {
            "控位提前周期": control_period["周期"],
            "高价窗口": high_window,
            "主卖窗口": main_window,
            "放量窗口": volume_window,
        },
        "controlPeriod": control_period,
        "price": {"合理控位价": take_price, "最高控位价": ceiling_price, "建议销售测试价": sale_price},
        "recommendation": f"{control_period['周期']}；{airline_action}{main_window}主推销售，{volume_window}根据余位放量，高价窗口保留在{high_window}。",
        "salesStrategy": f"先用{sale_price}附近测试市场高价，转化不足时回落到{target_price}附近；避免在{high_window}之前释放低价库存。",
        "scheduleNote": schedule_note,
        "sourceMode": source_mode,
        "fetchError": fetch_error,
        "fetchTried": bool(refresh),
        "sources": sources,
    }


def bucket_lead(days):
    if pd.isna(days) or days < 0:
        return None
    if days <= 1:
        return "1天"
    if days <= 4:
        return "2-4天"
    if days <= 9:
        return "5-9天"
    if days <= 14:
        return "10-14天"
    if days <= 21:
        return "15-21天"
    if days <= 30:
        return "22-30天"
    if days <= 45:
        return "31-45天"
    return "46天以上"


def stars(avg, route_min, route_max):
    if pd.isna(avg) or pd.isna(route_min) or pd.isna(route_max) or route_max <= route_min:
        return "★"
    level = int(((avg - route_min) / (route_max - route_min)) * 4) + 1
    return "★" * max(1, min(5, level))


def round_seats(value):
    if value <= 0:
        return 0
    if value < 10:
        return max(1, round(value))
    return int(round(value / 5) * 5)


def strategy_type(price_window, volume_window, price_premium, peak_share):
    if price_window == volume_window:
        return "收益销量同窗"
    if price_premium >= 0.35 and peak_share < 0.35:
        return "高价机会型"
    if peak_share >= 0.45:
        return "集中放量型"
    return "双窗口运营型"


def market_price_factor(market):
    if market["市场类型"] == "日韩短线高频":
        return 1.18
    if market["市场类型"] == "东南亚休闲/中转":
        return 1.15
    if market["市场类型"] == "长航程远程":
        return 1.22
    if market["市场类型"] == "韩国国内/区域":
        return 1.10
    return 1.12


def normalize_flight_no(value):
    text = re.sub(r"\s+", "", str(value or "").strip().upper())
    match = re.search(r"\b([A-Z0-9]{2}\d{1,4}[A-Z]?)\b", text)
    return match.group(1) if match else text


def flight_airline_code(value):
    flight = normalize_flight_no(value)
    match = re.match(r"([A-Z0-9]{2})\d", flight)
    return match.group(1) if match else ""


def sample_values(values, limit=5):
    seen = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "、".join(seen)


def parse_workbook(path: Path, source_name=""):
    raw = pd.read_excel(path, sheet_name=0)

    def normalized_name(value):
        return re.sub(r"[\s_\-/（）()]+", "", str(value or "").strip().lower())

    normalized_columns = {normalized_name(col): col for col in raw.columns}

    def pick_column(label, candidates, required=True):
        for candidate in candidates:
            key = normalized_name(candidate)
            if key in normalized_columns:
                return normalized_columns[key]
        for col in raw.columns:
            key = normalized_name(col)
            if any(normalized_name(candidate) in key for candidate in candidates):
                return col
        if required:
            raise ValueError(f"无法自动识别{label}字段，请确认 Excel 中包含相关列。")
        return None

    sales_date_col = pick_column("销售/出票日期", ["操作时间", "出票日期", "销售日期", "下单日期", "订单日期", "创建时间", "支付时间"])
    amount_col = pick_column("票价/金额", ["款项金额", "航司售价", "销售价", "票价", "成交价", "实收金额", "订单金额", "结算金额"])
    route_col = pick_column("航线", ["起飞-到达", "航程", "航线", "航段", "OD"])
    departure_col = pick_column("起飞时间", ["起飞时间/航班号", "起飞时间", "航班日期", "起飞日期", "出发时间", "航班时间"])
    type_col = pick_column("款项/产品类型", ["款项类型", "产品类型", "业务类型", "订单类型"], required=False)
    flight_col = pick_column("航班号", ["航班号", "航班"], required=False)

    df = raw.copy()
    df["款项金额"] = pd.to_numeric(df[amount_col], errors="coerce")
    df["航线"] = df[route_col].astype(str).str.strip().str.upper()
    df["起飞日期"] = pd.to_datetime(df[departure_col].astype(str).str[:19], errors="coerce").dt.normalize()
    df["销售日期"] = pd.to_datetime(df[sales_date_col], errors="coerce").dt.normalize()
    df["提前天数"] = (df["起飞日期"] - df["销售日期"]).dt.days
    df["提前分段"] = df["提前天数"].apply(bucket_lead)

    flight_source_col = flight_col or departure_col
    df["航班号"] = df[flight_source_col].apply(normalize_flight_no) if flight_source_col else ""
    df["航司"] = df["航班号"].apply(flight_airline_code)
    if type_col:
        type_mask = df[type_col].astype(str).str.strip().eq("出票")
        if not type_mask.any():
            type_mask = pd.Series(True, index=df.index)
    else:
        type_mask = pd.Series(True, index=df.index)

    filtered = df[
        type_mask
        & (df["款项金额"] > 0)
        & df["航线"].ne("")
        & df["起飞日期"].notna()
        & df["销售日期"].notna()
        & df["提前分段"].notna()
    ].copy()

    grouped = (
        filtered.groupby(["航线", "提前分段"], dropna=False)
        .agg(销售数量=("款项金额", "size"), 均价=("款项金额", "mean"), 最低价=("款项金额", "min"), 最高价=("款项金额", "max"))
        .reset_index()
    )

    routes = sorted(filtered["航线"].unique().tolist())
    route_ranges = grouped.groupby("航线").agg(route_min=("均价", "min"), route_max=("均价", "max")).to_dict("index")

    calc_rows = []
    for route in routes:
        route_rows = grouped[grouped["航线"] == route].set_index("提前分段")
        route_range = route_ranges.get(route, {})
        best_avg = route_rows["均价"].max() if not route_rows.empty else None
        for bucket in BUCKETS:
            if bucket in route_rows.index:
                row = route_rows.loc[bucket]
                avg = float(row["均价"])
                qty = int(row["销售数量"])
                low = float(row["最低价"])
                high = float(row["最高价"])
                calc_rows.append(
                    {
                        "航线": route,
                        "提前分段": bucket,
                        "销售数量": qty,
                        "均价": round(avg),
                        "最低价": round(low),
                        "最高价": round(high),
                        "价格区间": f"{round(low)}-{round(high)}",
                        "高价等级": stars(avg, route_range.get("route_min"), route_range.get("route_max")),
                        "最佳窗口": "✓ 是" if avg == best_avg and qty > 0 else "",
                    }
                )
            else:
                calc_rows.append(
                    {
                        "航线": route,
                        "提前分段": bucket,
                        "销售数量": 0,
                        "均价": "-",
                        "最低价": "-",
                        "最高价": "-",
                        "价格区间": "-",
                        "高价等级": "",
                        "最佳窗口": "",
                    }
                )

    calc = pd.DataFrame(calc_rows)
    nonzero = calc[calc["销售数量"] > 0].copy()
    pivot_rows = []
    for route in routes:
        source = filtered[filtered["航线"] == route]
        report = nonzero[nonzero["航线"] == route]
        main_window = ""
        if not report.empty:
            main_window = report.sort_values(["销售数量", "均价"], ascending=[False, False]).iloc[0]["提前分段"]
        pivot_rows.append(
            {
                "航线": route,
                "总销售数量": int(len(source)),
                "平均票价": round(source["款项金额"].mean()) if len(source) else 0,
                "最低票价": round(source["款项金额"].min()) if len(source) else 0,
                "最高票价": round(source["款项金额"].max()) if len(source) else 0,
                "主要销售窗口": main_window,
            }
        )

    pivot = pd.DataFrame(pivot_rows).sort_values("总销售数量", ascending=False)
    strategy_rows = []
    sales_days = max((filtered["销售日期"].max() - filtered["销售日期"].min()).days + 1, 1) if len(filtered) else 1
    for route in routes:
        report = calc[(calc["航线"] == route) & (calc["销售数量"] > 0)].copy()
        if report.empty:
            continue
        report["总到账"] = report["销售数量"] * pd.to_numeric(report["均价"], errors="coerce")
        source = filtered[filtered["航线"] == route]
        avg_ticket = float(source["款项金额"].mean()) if len(source) else 0
        max_qty = report["销售数量"].max()
        min_qty = report["销售数量"].min()
        max_avg = pd.to_numeric(report["均价"], errors="coerce").max()
        min_avg = pd.to_numeric(report["均价"], errors="coerce").min()

        qty_span = max(max_qty - min_qty, 1)
        avg_span = max(max_avg - min_avg, 1)
        report["综合评分"] = (
            ((pd.to_numeric(report["均价"], errors="coerce") - min_avg) / avg_span) * 55
            + ((report["销售数量"] - min_qty) / qty_span) * 45
        )

        best_avg = report.sort_values(["均价", "销售数量"], ascending=[False, False]).iloc[0]
        best_qty = report.sort_values(["销售数量", "均价"], ascending=[False, False]).iloc[0]
        best_score = report.sort_values(["综合评分", "总到账"], ascending=[False, False]).iloc[0]
        market = route_market(route)
        self_peak_price = int(best_avg["最高价"])
        market_peak_price = round(self_peak_price * market_price_factor(market))
        price_gap = market_peak_price - self_peak_price
        if price_gap > max(80, self_peak_price * 0.08):
            price_action = f"自售最高价低于市场参考约{price_gap}，{best_avg['提前分段']}可小批量抬价测试。"
        elif self_peak_price >= market_peak_price:
            price_action = f"自售最高价已接近或高于市场参考，{best_avg['提前分段']}重点控量保价。"
        else:
            price_action = f"自售最高价接近市场参考，{best_avg['提前分段']}维持现价并观察转化。"
        weekly_demand = len(source) / sales_days * 7
        peak_share = float(best_qty["销售数量"]) / max(len(source), 1)
        price_premium = (float(best_avg["均价"]) / avg_ticket - 1) if avg_ticket else 0
        lock_multiplier = market["锁座系数"] * (0.85 + min(peak_share, 0.55)) * (1.1 if price_premium > 0.25 else 1)
        recommend_seats = round_seats(weekly_demand * lock_multiplier)
        min_seats = max(1, round_seats(recommend_seats * 0.7)) if recommend_seats else 0
        max_seats = max(min_seats, round_seats(recommend_seats * 1.25)) if recommend_seats else 0
        sell_type = strategy_type(best_avg["提前分段"], best_qty["提前分段"], price_premium, peak_share)

        if best_avg["提前分段"] == best_qty["提前分段"]:
            action = f"主推{best_avg['提前分段']}，该窗口收益和销量同时占优；锁座后按销量节奏逐步放价。"
        elif best_score["提前分段"] == best_avg["提前分段"]:
            action = f"优先保价在{best_avg['提前分段']}，用{best_qty['提前分段']}做放量补充；低价库存不要过早释放。"
        elif best_score["提前分段"] == best_qty["提前分段"]:
            action = f"优先放量在{best_qty['提前分段']}，高价库存留给{best_avg['提前分段']}；临近窗口观察涨价空间。"
        else:
            action = f"综合主推{best_score['提前分段']}，同时监控{best_avg['提前分段']}的高收益机会。"

        strategy_rows.append(
            {
                "航线": route,
                "有效出票": int(report["销售数量"].sum()),
                "市场类型": market["市场类型"],
                "外部热度": market["外部热度"],
                "竞争强度": market["竞争强度"],
                "策略类型": sell_type,
                "建议主卖窗口": best_score["提前分段"],
                "单张收益最高窗口": best_avg["提前分段"],
                "最高均价": int(best_avg["均价"]),
                "自售最高价": self_peak_price,
                "市场参考最高价": market_peak_price,
                "价差空间": price_gap,
                "张数最多窗口": best_qty["提前分段"],
                "最多张数": int(best_qty["销售数量"]),
                "综合建议窗口": best_score["提前分段"],
                "建议锁座": f"{min_seats}-{max_seats}座/周",
                "锁座基准": int(recommend_seats),
                "锁座节奏": f"先锁{min_seats}座，{best_qty['提前分段']}放量；{best_avg['提前分段']}保留高价库存。",
                "控价动作": f"{best_avg['提前分段']}做最高价测试，自售最高{self_peak_price}，市场参考{market_peak_price}；{best_qty['提前分段']}控制主销量。",
                "价差建议": price_action,
                "策略建议": action,
                "外部判断": market["外部判断"],
            }
        )

    strategy = pd.DataFrame(strategy_rows).sort_values(["有效出票", "最高均价"], ascending=False)
    backtest_rows = []
    for row in strategy.to_dict("records"):
        main_hit = row["建议主卖窗口"] == row["张数最多窗口"]
        price_hit = row["建议主卖窗口"] == row["单张收益最高窗口"]
        if main_hit and price_hit:
            verdict = "完全命中"
        elif main_hit:
            verdict = "销量命中"
        elif price_hit:
            verdict = "高价命中"
        else:
            verdict = "偏离"
        backtest_rows.append({
            "航线": row["航线"],
            "模型建议窗口": row["建议主卖窗口"],
            "实际销量窗口": row["张数最多窗口"],
            "实际高价窗口": row["单张收益最高窗口"],
            "销量是否命中": "是" if main_hit else "否",
            "高价是否命中": "是" if price_hit else "否",
            "结论": verdict,
            "调参建议": "维持模型" if verdict in ["完全命中", "销量命中"] else "提高高价窗口权重" if price_hit else "提高销量窗口权重",
        })
    top_routes = pivot.head(12).to_dict("records")
    totals_by_bucket = (
        filtered.groupby("提前分段").agg(销售数量=("款项金额", "size"), 平均票价=("款项金额", "mean")).reindex(BUCKETS).fillna(0)
    )
    strategy_records = strategy.to_dict("records")

    return {
        "fileName": source_name or path.name,
        "sourceRows": int(len(raw)),
        "validRows": int(len(filtered)),
        "routeCount": int(len(routes)),
        "amountTotal": round(float(filtered["款项金额"].sum()), 2),
        "dateRange": {
            "start": str(filtered["销售日期"].min().date()) if len(filtered) else "",
            "end": str(filtered["销售日期"].max().date()) if len(filtered) else "",
        },
        "pivot": pivot.to_dict("records"),
        "calc": calc.to_dict("records"),
        "strategy": strategy_records,
        "backtest": backtest_rows,
        "defaultRoutePlan": route_plan("PKX-CJU", strategy_records),
        "topRoutes": top_routes,
        "bucketSummary": [
            {"提前分段": idx, "销售数量": int(row["销售数量"]), "平均票价": round(float(row["平均票价"])) if row["销售数量"] else 0}
            for idx, row in totals_by_bucket.iterrows()
        ],
        "notes": [
            "按自动字段识别结果输出：数据源 → 计算层 → 透视表 → 航线报告。",
            f"字段映射：销售日期={sales_date_col}，起飞时间={departure_col}，航线={route_col}，金额={amount_col}。",
            "筛选口径：金额大于 0、且可识别航线/起飞日期/销售日期；如表内存在“款项类型=出票”则优先按出票过滤。",
            "策略口径：因原始表没有独立成本字段，当前用款项金额/均价作为单张收益代理，并与销量窗口对比。",
            "外部市场层：参考区域客运增长、航班频次/座位数据可用口径，将航线分为日韩短线、东南亚、远程等市场类型；后续可接入航司/OAG/Cirium明细。",
            "市场参考最高价：当前为市场类型因子估算，用于页面结构和策略判断；接入真实竞品价格后会替换为同期市场最高价。",
            "锁座口径：按历史有效出票周化需求、销量集中度、价格溢价和外部市场系数估算，输出每周建议锁座区间。",
            "提前分段按“起飞日期 - 操作日期”计算；0-1天归入“1天”，46天以上归入“46天以上”。",
        ],
        "externalSources": [
            {"name": "IATA Air Passenger Market Analysis", "url": "https://www.iata.org/en/iata-repository/publications/economic-reports/air-passenger-market-analysis-march-2026/"},
            {"name": "OAG Airline Schedules Data", "url": "https://www.oag.com/airline-schedules-data"},
            {"name": "Cirium aviation schedules and capacity data", "url": "https://www.cirium.com/data/"},
        ],
    }


def clean_records(df):
    df = df.where(pd.notna(df), None)
    return df.to_dict("records")


def read_result_csv(name):
    path = FULL_STRATEGY_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def report_value(pattern, text, default=""):
    match = re.search(pattern, text)
    return match.group(1) if match else default


def load_full_strategy_metadata(report_text=""):
    metadata = load_json_file(FULL_STRATEGY_METADATA_FILE, {})
    metrics = metadata.get("metrics", {}) if isinstance(metadata, dict) else {}
    date_range = metadata.get("dateRange", {}) if isinstance(metadata, dict) else {}
    source = metadata.get("source", {}) if isinstance(metadata, dict) else {}

    source_rows = int(number_value(metrics.get("ticketSourceRows"), 0))
    valid_rows = int(number_value(metrics.get("ticketValidRows"), 0))
    route_count = int(number_value(metrics.get("routeCount"), 0))
    if not source_rows:
        source_rows = int(report_value(r"出票口径：原始 ([\d,]+) 行", report_text, "0").replace(",", ""))
    if not valid_rows:
        valid_rows = int(report_value(r"去重有效 ([\d,]+) 行", report_text, "0").replace(",", ""))
    if not route_count:
        route_count = int(report_value(r"航线数量：(\d+) 条", report_text, "0"))
    if not date_range.get("start") or not date_range.get("end"):
        date_match = re.search(r"销售日期：(\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2})", report_text)
        date_range = {
            "start": date_match.group(1) if date_match else "",
            "end": date_match.group(2) if date_match else "",
        }

    return {
        "sourceRows": source_rows,
        "validRows": valid_rows,
        "routeCount": route_count,
        "amountTotal": metrics.get("amountTotal"),
        "dateRange": {"start": date_range.get("start", ""), "end": date_range.get("end", "")},
        "sourceLabel": source.get("label") or "销售数据文件夹全量分析",
        "metadata": metadata,
    }


def load_full_sales_strategy():
    strategy = read_result_csv("route_strategy.csv")
    calc = read_result_csv("bucket_detail.csv")
    airline = read_result_csv("route_airline_summary.csv")
    manifest = read_result_csv("file_manifest.csv")
    report_path = FULL_STRATEGY_DIR / "report.md"
    report_text = report_path.read_text("utf-8") if report_path.exists() else ""
    metadata = load_full_strategy_metadata(report_text)

    if strategy.empty:
        raise ValueError("还没有找到全量销售策略结果，请先分析桌面销售数据文件夹。")

    airline = airline.rename(columns={"route": "航线", "airline": "航司"})
    source_rows = metadata["sourceRows"]
    valid_rows = metadata["validRows"] or int(pd.to_numeric(strategy["有效出票"], errors="coerce").sum())
    route_count = metadata["routeCount"] or int(strategy["航线"].nunique())
    date_range = metadata["dateRange"]

    pivot = strategy[["航线", "有效出票", "最高均价", "自售最高价", "建议主卖窗口"]].copy()
    pivot = pivot.rename(columns={
        "有效出票": "总销售数量",
        "最高均价": "平均票价",
        "自售最高价": "最高票价",
        "建议主卖窗口": "主要销售窗口",
    })
    pivot["最低票价"] = ""
    pivot = pivot[["航线", "总销售数量", "平均票价", "最低票价", "最高票价", "主要销售窗口"]]

    backtest = []
    for row in clean_records(strategy):
        main_hit = row.get("建议主卖窗口") == row.get("张数最多窗口")
        price_hit = row.get("建议主卖窗口") == row.get("单张收益最高窗口")
        backtest.append({
            "航线": row.get("航线"),
            "模型建议窗口": row.get("建议主卖窗口"),
            "实际销量窗口": row.get("张数最多窗口"),
            "实际高价窗口": row.get("单张收益最高窗口"),
            "销量是否命中": "是" if main_hit else "否",
            "高价是否命中": "是" if price_hit else "否",
            "结论": row.get("模型回测"),
            "调参建议": row.get("调参建议"),
        })

    if not calc.empty:
        bucket_df = (
            calc.groupby("提前分段", dropna=False)
            .agg(销售数量=("销售数量", "sum"), 平均票价=("均价", "mean"))
            .reindex(BUCKETS)
            .fillna(0)
        )
        bucket_summary = [
            {"提前分段": idx, "销售数量": int(row["销售数量"]), "平均票价": round(float(row["平均票价"])) if row["销售数量"] else 0}
            for idx, row in bucket_df.iterrows()
        ]
    else:
        bucket_summary = []

    strategy_records = clean_records(strategy)
    high_price_evidence = high_price_context_from_manifest(manifest)
    operating_layers = build_operating_layers(strategy, calc, airline, high_price_evidence)
    return {
        "fileName": metadata["sourceLabel"],
        "sourceRows": source_rows,
        "validRows": valid_rows,
        "routeCount": route_count,
        "amountTotal": metadata["amountTotal"],
        "dateRange": date_range,
        "pivot": clean_records(pivot),
        "calc": clean_records(calc),
        "strategy": strategy_records,
        "backtest": backtest,
        "airline": clean_records(airline),
        "risk": operating_layers["risk"],
        "rhythm": operating_layers["rhythm"],
        "airlinePriority": operating_layers["airlinePriority"],
        "calibration": operating_layers["calibration"],
        "inventory": operating_layers["inventory"],
        "inventoryAlerts": operating_layers["inventoryAlerts"],
        "externalApis": operating_layers["externalApis"],
        "fileManifest": clean_records(manifest),
        "fullReport": report_text,
        "metadata": metadata["metadata"],
        "defaultRoutePlan": route_plan("PKX-CJU", strategy_records),
        "topRoutes": clean_records(pivot.head(12)),
        "bucketSummary": bucket_summary,
        "notes": [
            "当前展示的是桌面“销售数据”文件夹的全量结果，内部 CP 出票数据为主，DZ 到账数据用于辅助校验。",
            "策略依据：按航线拆分提前销售窗口，对比销量峰值、均价峰值、自售最高价、航司贡献和模型回测。",
            "总到账暂不作为策略核心指标；页面重点看有效出票、销售窗口、价格窗口、锁座建议和航司分布。",
            "航司汇总用于判断可优先沟通的承运方；外部通飞数据仍由航线采购策略模块补充。",
        ],
    }


def normalize_route_filter(value):
    raw = str(value or "").strip().upper().replace(" ", "")
    if re.fullmatch(r"[A-Z]{6}", raw):
        return f"{raw[:3]}-{raw[3:]}"
    return raw


def ai_strategy_level(row):
    text = " ".join(str(row.get(key, "")) for key in ("策略类型", "模型回测", "调参建议", "策略建议"))
    if "偏离" in text or "提高" in text:
        return "谨慎主推"
    if "维持" in text or "销量命中" in text:
        return "正常主推"
    if "样本" in text or "风险" in text:
        return "人工复核"
    return row.get("策略类型") or "待AI判断"


def build_route_ai_facts(route_row, bucket_rows, airline_rows):
    route = route_row.get("航线", "")
    buckets = [row for row in bucket_rows if row.get("航线") == route]
    airlines = [row for row in airline_rows if row.get("航线") == route]
    airlines = sorted(airlines, key=lambda row: number_value(row.get("出票量"), 0), reverse=True)[:5]
    return {
        "route": route,
        "market_type": route_row.get("市场类型"),
        "strategy_type": route_row.get("策略类型"),
        "sales_windows": {
            "recommended_main_window": route_row.get("建议主卖窗口"),
            "actual_volume_window": route_row.get("张数最多窗口"),
            "actual_high_price_window": route_row.get("单张收益最高窗口"),
            "combined_window": route_row.get("综合建议窗口"),
        },
        "price_and_volume": {
            "valid_tickets": route_row.get("有效出票"),
            "highest_average_price": route_row.get("最高均价"),
            "self_highest_price": route_row.get("自售最高价"),
            "market_reference_highest_price": route_row.get("市场参考最高价"),
            "price_gap_space": route_row.get("价差空间"),
            "peak_volume": route_row.get("最多张数"),
        },
        "seat_and_action": {
            "recommended_seats": route_row.get("建议锁座"),
            "seat_basis": route_row.get("锁座基准"),
            "seat_rhythm": route_row.get("锁座节奏"),
            "price_control_action": route_row.get("控价动作"),
            "strategy_advice": route_row.get("策略建议"),
        },
        "model_backtest": {
            "result": route_row.get("模型回测"),
            "tuning_advice": route_row.get("调参建议"),
            "data_source": route_row.get("数据来源"),
        },
        "bucket_detail": buckets,
        "airline_summary": airlines,
        "questions_for_ai": [
            "当前航线是否应该继续主推、谨慎主推、控量保价或暂缓？",
            "模型偏差主要来自价格、销售窗口、航司供给、样本结构还是库存节奏？",
            "下一轮锁座数量、主卖窗口和控价动作应该如何调整？",
            "哪些结论需要人工复核后才能进入策略执行任务？",
        ],
        "expected_ai_output_schema": {
            "ai_strategy_level": "正常主推 / 谨慎主推 / 控量保价 / 暂缓 / 人工复核",
            "recommended_seats_adjustment": "建议锁座调整说明",
            "price_action": "保价、测试降价、分批放量或暂停动作",
            "risk_tags": ["窗口偏移", "价格风险", "供给竞争", "样本不足"],
            "human_review_required": True,
        },
    }


def build_ai_local_suggestion(route_facts):
    backtest = route_facts.get("model_backtest", {})
    seat = route_facts.get("seat_and_action", {})
    windows = route_facts.get("sales_windows", {})
    bias_tags = []
    if backtest.get("result") and "偏离" in str(backtest.get("result")):
        bias_tags.append("模型偏离")
    if windows.get("recommended_main_window") != windows.get("actual_volume_window"):
        bias_tags.append("销量窗口偏移")
    if windows.get("actual_high_price_window") != windows.get("actual_volume_window"):
        bias_tags.append("高价与放量窗口分离")
    return {
        "route": route_facts.get("route"),
        "source": "本地规则预建议，等待外部AI复核",
        "ai_strategy_level": ai_strategy_level({
            "策略类型": route_facts.get("strategy_type"),
            "模型回测": backtest.get("result"),
            "调参建议": backtest.get("tuning_advice"),
            "策略建议": seat.get("strategy_advice"),
        }),
        "seat_adjustment": {
            "current_recommendation": seat.get("recommended_seats"),
            "suggestion": "先保持本地模型锁座建议，待AI结合外部供给与近期成交后再调整。",
        },
        "price_action": seat.get("price_control_action") or "待AI结合价格窗口判断",
        "risk_tags": bias_tags or ["待AI深度诊断"],
        "human_review_required": True,
    }


def generate_ai_analysis_package(route="", limit=8):
    strategy = read_result_csv("route_strategy.csv")
    calc = read_result_csv("bucket_detail.csv")
    airline = read_result_csv("route_airline_summary.csv")
    if strategy.empty:
        raise ValueError("还没有找到全量销售策略结果，请先读取销售数据文件夹或系统已有数据。")

    route_filter = normalize_route_filter(route)
    strategy_rows = clean_records(strategy)
    if route_filter:
        selected_rows = [row for row in strategy_rows if row.get("航线") == route_filter]
        if not selected_rows:
            raise ValueError(f"没有找到 {route_filter} 的销售策略结果。")
    else:
        selected_rows = strategy_rows[:max(1, int(number_value(limit, 8)))]

    bucket_rows = clean_records(calc) if not calc.empty else []
    airline_rows = clean_records(airline.rename(columns={"route": "航线", "airline": "航司"})) if not airline.empty else []
    report_path = FULL_STRATEGY_DIR / "report.md"
    report_text = report_path.read_text("utf-8") if report_path.exists() else ""
    metadata = load_full_strategy_metadata(report_text)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    route_label = route_filter or "ALL"
    package_id = f"ai_pkg_{route_label.replace('-', '')}_{time.strftime('%Y%m%d_%H%M%S')}"
    route_facts = [build_route_ai_facts(row, bucket_rows, airline_rows) for row in selected_rows]
    package = {
        "package_id": package_id,
        "version": "ai-analysis-package-v1",
        "generated_at": generated_at,
        "scope": {
            "route": route_filter or "top_routes",
            "route_count": len(route_facts),
            "source_label": metadata["sourceLabel"],
            "date_range": metadata["dateRange"],
        },
        "data_boundary": {
            "storage": "system_internal_outputs",
            "raw_data_exposed_to_ai": False,
            "contains_personal_data": False,
            "rule": "AI 只接收本地系统整理后的事实包，不直接读取原始 Excel、乘客或订单明细。",
        },
        "flow": [
            "本地系统读取和计算销售事实",
            "生成脱敏结构化 AI 分析包",
            "AI 输出结构化策略建议",
            "本地系统写入建议池并等待人工确认",
            "确认后再进入模型校准或策略执行任务",
        ],
        "routes": route_facts,
        "local_suggestion_preview": [build_ai_local_suggestion(item) for item in route_facts],
        "next_steps": [
            "先在本页人工检查分析包字段是否足够支撑判断。",
            "确认字段后接入 DeepSeek/OpenAI/本地模型中的一个作为 AI 分析器。",
            "AI 结果先进入 suggestions 目录和页面建议池，不直接改库存、不自动上架、不自动调价。",
            "累计真实执行结果后，再用 AI 建议命中率做闭环校准。",
        ],
    }

    AI_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    AI_SUGGESTION_DIR.mkdir(parents=True, exist_ok=True)
    AI_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    package_path = AI_PACKAGE_DIR / f"{package_id}.json"
    package_path.write_text(json.dumps(json_safe(package), ensure_ascii=False, indent=2), "utf-8")
    audit_path = AI_AUDIT_DIR / "package_index.json"
    audits = load_json_file(audit_path, [])
    if not isinstance(audits, list):
        audits = []
    audits.insert(0, {
        "package_id": package_id,
        "generated_at": generated_at,
        "route": route_filter or "top_routes",
        "route_count": len(route_facts),
        "path": str(package_path),
    })
    audit_path.write_text(json.dumps(json_safe(audits[:200]), ensure_ascii=False, indent=2), "utf-8")
    return {
        "ok": True,
        "package": package,
        "packagePath": str(package_path),
        "suggestions": list_ai_suggestions(),
        "audits": audits[:20],
    }


def load_ai_package_by_id(package_id=""):
    AI_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    package_id = str(package_id or "").strip()
    if not package_id:
        audits = load_json_file(AI_AUDIT_DIR / "package_index.json", [])
        if isinstance(audits, list) and audits:
            package_id = str(audits[0].get("package_id", "")).strip()
    if not re.match(r"^ai_pkg_[A-Za-z0-9_]+$", package_id):
        raise ValueError("分析包ID不正确。")
    package_path = AI_PACKAGE_DIR / f"{package_id}.json"
    if not package_path.exists() or package_path.resolve().parent != AI_PACKAGE_DIR.resolve():
        raise ValueError(f"没有找到分析包：{package_id}")
    data = load_json_file(package_path, {})
    if not isinstance(data, dict) or data.get("package_id") != package_id:
        raise ValueError("分析包文件内容不完整或ID不匹配。")
    return data, package_path


def build_ai_package_prompt(package):
    schema = {
        "package_id": package.get("package_id"),
        "ai_strategy_level": "正常主推 / 谨慎主推 / 控量保价 / 暂缓 / 人工复核",
        "recommended_seats_adjustment": "锁座数量、节奏或不调整的明确说明",
        "price_action": "保价、测试降价、分批放量、暂停动作等",
        "risk_tags": ["窗口偏移", "价格风险", "供给竞争", "样本不足"],
        "human_review_required": True,
        "reasoning": "基于分析包事实的简要判断依据",
        "write_back_position": "建议写入：outputs/ai_analysis/suggestions，待人工确认",
    }
    return (
        "你是航空航线收益优化智能执行平台的外部AI复核器。\n"
        "请只基于下面的脱敏AI分析包输出策略建议，不要假设未提供的数据。\n"
        "禁止输出可直接自动执行的改价、上架、关仓、支付或订单动作；所有建议都必须标记为待人工复核。\n"
        "请严格返回一个JSON对象，不要返回Markdown。\n\n"
        "必须返回的JSON结构示例：\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "待分析的AI分析包：\n"
        f"{json.dumps(json_safe(package), ensure_ascii=False, indent=2)}"
    )


def ai_package_export(package_id="", mode="package"):
    package, package_path = load_ai_package_by_id(package_id)
    if mode == "prompt":
        text = build_ai_package_prompt(package)
        filename = f"{package.get('package_id')}_prompt.txt"
        content_type = "text/plain; charset=utf-8"
        return text.encode("utf-8"), filename, content_type
    filename = package_path.name
    content_type = "application/json; charset=utf-8"
    return package_path.read_bytes(), filename, content_type


def import_external_ai_suggestion(payload, session=None, client_ip=""):
    AI_SUGGESTION_DIR.mkdir(parents=True, exist_ok=True)
    AI_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    package_id = str(payload.get("package_id") or payload.get("packageId") or "").strip()
    package, package_path = load_ai_package_by_id(package_id)
    raw_suggestion = payload.get("suggestion")
    if raw_suggestion is None:
        raw_suggestion = payload.get("ai_result") or payload.get("aiResult")
    if isinstance(raw_suggestion, str):
        raw_suggestion = json.loads(raw_suggestion)
    if not isinstance(raw_suggestion, dict):
        raise ValueError("AI返回结果必须是JSON对象。")

    required = ["ai_strategy_level", "recommended_seats_adjustment", "price_action", "human_review_required"]
    missing = [field for field in required if field not in raw_suggestion]
    if missing:
        raise ValueError("AI返回结果缺少字段：" + "、".join(missing))
    if raw_suggestion.get("human_review_required") is not True:
        raise ValueError("AI返回结果必须明确 human_review_required=true，不能直接进入执行。")
    risk_tags = raw_suggestion.get("risk_tags", [])
    if not isinstance(risk_tags, list):
        raise ValueError("risk_tags 必须是数组。")

    package_routes = {item.get("route") for item in package.get("routes", []) if item.get("route")}
    suggestion_route = raw_suggestion.get("route") or (next(iter(package_routes)) if len(package_routes) == 1 else package.get("scope", {}).get("route"))
    if suggestion_route and package_routes and suggestion_route not in package_routes and package.get("scope", {}).get("route") != "top_routes":
        raise ValueError("AI返回航线与分析包范围不一致。")

    actor, role = session_actor(session)
    imported_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record_id = f"external_ai_suggestion_{package.get('package_id')}_{time.strftime('%Y%m%d_%H%M%S')}"
    record = {
        "id": record_id,
        "type": "external_ai_strategy_suggestion",
        "status": "待人工复核",
        "package_id": package.get("package_id"),
        "package_path": str(package_path),
        "route": suggestion_route or "",
        "model": payload.get("model") or payload.get("provider") or "外部AI",
        "source": "外部AI返回结果",
        "ai_strategy_level": raw_suggestion.get("ai_strategy_level"),
        "recommended_seats_adjustment": raw_suggestion.get("recommended_seats_adjustment"),
        "price_action": raw_suggestion.get("price_action"),
        "risk_tags": risk_tags,
        "human_review_required": True,
        "reasoning": raw_suggestion.get("reasoning") or raw_suggestion.get("reason") or "",
        "write_back_position": raw_suggestion.get("write_back_position") or "outputs/ai_analysis/suggestions",
        "raw_ai_result": raw_suggestion,
        "control_boundary": "只写入建议池和审计日志；不写售价、不写库存、不自动上架、不自动调价、不执行OTA。",
        "createdAt": imported_at,
        "createdBy": actor,
    }
    output_path = AI_SUGGESTION_DIR / f"{record_id}.json"
    output_path.write_text(json.dumps(json_safe(record), ensure_ascii=False, indent=2), "utf-8")
    append_audit_log(actor, role, "导入外部AI建议至建议池", package.get("package_id"), "成功", str(output_path), client_ip)
    return {
        "ok": True,
        "record": record,
        "path": str(output_path),
        "suggestions": list_ai_suggestions(),
    }


def list_ai_suggestions():
    AI_SUGGESTION_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(AI_SUGGESTION_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = load_json_file(path, {})
        if isinstance(data, dict):
            rows.append({
                "文件": path.name,
                "航线": data.get("route") or data.get("航线") or "",
                "策略等级": data.get("ai_strategy_level") or data.get("策略等级") or "",
                "来源": data.get("source") or data.get("type") or "",
                "价格动作": data.get("price_action") or "",
                "风险标签": data.get("risk_tags") or [],
                "需要人工确认": data.get("human_review_required", True),
                "更新时间": int(path.stat().st_mtime),
            })
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    "文件": path.name,
                    "航线": item.get("route") or item.get("航线") or "",
                    "策略等级": item.get("ai_strategy_level") or item.get("策略等级") or item.get("type") or "",
                    "来源": item.get("source") or item.get("type") or "",
                    "价格动作": item.get("price_action") or item.get("note") or "",
                    "风险标签": item.get("risk_tags") or [],
                    "需要人工确认": item.get("human_review_required", True),
                    "更新时间": int(path.stat().st_mtime),
                })
    return rows


def bucket_day_count(bucket):
    return {
        "1天": 1,
        "2-4天": 3,
        "5-9天": 5,
        "10-14天": 5,
        "15-21天": 7,
        "22-30天": 9,
        "31-45天": 15,
        "46天以上": 16,
    }.get(bucket, 1)


def bucket_max_day(bucket):
    return {
        "1天": 1,
        "2-4天": 4,
        "5-9天": 9,
        "10-14天": 14,
        "15-21天": 21,
        "22-30天": 30,
        "31-45天": 45,
        "46天以上": 60,
    }.get(bucket, 15)


def route_model_horizon(route_calc):
    if route_calc.empty:
        return 15
    rows = clean_records(route_calc)
    active_days = [
        bucket_max_day(row.get("提前分段"))
        for row in rows
        if sales_quantity_value(row) > 0
    ]
    return max(active_days or [15])


def distribute_seats(day_weights, seats):
    if seats <= 0:
        return {day: 0 for day in day_weights}
    total_weight = sum(day_weights.values()) or 1
    raw = {day: day_weights[day] / total_weight * seats for day in day_weights}
    assigned = {day: int(raw[day]) for day in raw}
    remaining = seats - sum(assigned.values())
    for day in sorted(raw, key=lambda item: raw[item] - assigned[item], reverse=True)[:remaining]:
        assigned[day] += 1
    return assigned


def sales_cycle_plan(
    route,
    seats=40,
    departure_date="",
    cost=0,
    departure_end="",
    flights_per_day=1,
    seats_per_flight=0,
    airline="",
    flight_no="",
    horizon_days=0,
    model_source_mode="mixedForecast",
    decision_date="",
    strategy_rows_override=None,
    calc_records_override=None,
    model_source_label_override="",
    actual_inventory=0,
):
    route = normalize_route(route)
    airline = str(airline).strip().upper()
    flight_no = str(flight_no).strip().upper()
    flights_per_day = max(1, int(number_value(flights_per_day, 1)))
    seats_per_flight = int(number_value(seats_per_flight, 0))
    seats = max(1, int(number_value(seats, 40)))
    actual_inventory = int(number_value(actual_inventory, 0))
    if seats_per_flight > 0:
        daily_seats = flights_per_day * seats_per_flight
    else:
        daily_seats = seats
        seats_per_flight = max(1, round(daily_seats / flights_per_day))
    cost = number_value(cost, 0)
    if strategy_rows_override is not None and calc_records_override is not None:
        strategy_rows = strategy_rows_override
        calc_df = pd.DataFrame(calc_records_override)
        if not strategy_rows or calc_df.empty:
            raise ValueError("指定的本地Excel没有生成可用策略结果，请检查是否为销售数据表。")
    else:
        strategy_df = read_result_csv("route_strategy.csv")
        calc_df = read_result_csv("bucket_detail.csv")
        if strategy_df.empty or calc_df.empty:
            raise ValueError("还没有找到全量销售策略结果，请先载入或生成销售数据分析。")
        strategy_rows = clean_records(strategy_df)
    strategy = row_for_route(strategy_rows, route) or {}
    route_calc = calc_df[calc_df["航线"] == route].copy()
    if model_source_mode == "localExcel" and route_calc.empty:
        raise ValueError(f"指定的本地Excel里没有找到航线 {route} 的有效销售记录。")
    route_plan_data = route_plan(route, strategy_rows)
    source_labels = {
        "mixedForecast": "全量数据池 outputs/sales_strategy_all + 航线公开供给缓存/联网参考",
        "currentGlobal": "当前全局数据/全量数据池 outputs/sales_strategy_all + 航线公开供给缓存/联网参考",
        "internalOnly": "全量数据池 outputs/sales_strategy_all",
        "localExcel": "指定本地Excel",
        "externalReference": "航线公开供给缓存/联网参考 + 全量数据池兜底",
    }
    model_source_label = source_labels.get(model_source_mode, source_labels["mixedForecast"])
    if model_source_label_override:
        model_source_label = model_source_label_override
    horizon_days = int(number_value(horizon_days, 0))
    if horizon_days <= 0:
        horizon_days = route_model_horizon(route_calc)
    horizon_days = max(1, min(horizon_days, 120))

    def parse_date_range(start_value, end_value, fallback_days):
        start = pd.to_datetime(start_value, errors="coerce")
        if pd.isna(start):
            start = pd.Timestamp.today().normalize() + pd.Timedelta(days=fallback_days)
        end = pd.to_datetime(end_value, errors="coerce")
        if pd.isna(end):
            end = start
        if end < start:
            start, end = end, start
        return start, end, list(pd.date_range(start, end, freq="D"))

    departure, end_departure, departure_dates = parse_date_range(departure_date, departure_end, 15)
    decision_ts = pd.to_datetime(decision_date, errors="coerce")
    if pd.isna(decision_ts):
        decision_ts = pd.Timestamp.today().normalize()
    else:
        decision_ts = decision_ts.normalize()
    total_flights = len(departure_dates) * flights_per_day
    default_total_seats = len(departure_dates) * daily_seats
    total_seats = actual_inventory if actual_inventory > 0 else default_total_seats
    if actual_inventory > 0:
        base_inventory = actual_inventory // len(departure_dates)
        extra_inventory = actual_inventory % len(departure_dates)
        inventory_by_departure = {
            flight_date.date().isoformat(): base_inventory + (1 if idx < extra_inventory else 0)
            for idx, flight_date in enumerate(departure_dates)
        }
    else:
        inventory_by_departure = {
            flight_date.date().isoformat(): daily_seats
            for flight_date in departure_dates
        }

    calc_by_bucket = {row["提前分段"]: row for row in clean_records(route_calc)}
    if model_source_mode == "externalReference":
        main_window = route_plan_data["windows"]["主卖窗口"]
        high_window = route_plan_data["windows"]["高价窗口"]
        volume_window = route_plan_data["windows"]["放量窗口"]
    else:
        main_window = strategy.get("建议主卖窗口") or route_plan_data["windows"]["主卖窗口"]
        high_window = strategy.get("单张收益最高窗口") or route_plan_data["windows"]["高价窗口"]
        volume_window = strategy.get("张数最多窗口") or route_plan_data["windows"]["放量窗口"]
    fallback_price = number_value(strategy.get("最高均价"), route_plan_data["price"]["建议销售测试价"])
    self_high = number_value(strategy.get("自售最高价"), fallback_price)

    day_weights = {}
    day_meta = {}
    for day in range(horizon_days, 0, -1):
        bucket = bucket_lead(day)
        bucket_row = calc_by_bucket.get(bucket, {})
        hist_qty = sales_quantity_value(bucket_row)
        hist_avg = number_value(bucket_row.get("均价"), fallback_price)
        hist_high = number_value(bucket_row.get("最高价"), max(hist_avg, self_high))
        weight = hist_qty / bucket_day_count(bucket) if hist_qty else 1
        if bucket == volume_window:
            weight *= 1.35
        if bucket == main_window:
            weight *= 1.18
        if bucket == high_window and bucket != volume_window:
            weight *= 0.78
        if day <= 2 and volume_window in ["1天", "2-4天"]:
            weight *= 1.12
        day_weights[day] = max(weight, 0.1)
        day_meta[day] = {
            "bucket": bucket,
            "histQty": int(hist_qty),
            "histAvg": round(hist_avg) if hist_avg else round(fallback_price),
            "histHigh": round(hist_high) if hist_high else round(self_high),
        }

    rows = []
    flight_identity = " / ".join([item for item in [airline, flight_no] if item]) or "未填航司航班"
    for flight_date in departure_dates:
        available_seats = int(inventory_by_departure.get(flight_date.date().isoformat(), daily_seats))
        date_weights = {}
        date_factors = {}
        for day in range(horizon_days, 0, -1):
            sale_ts = flight_date - pd.Timedelta(days=day)
            factor_text = price_factor_notes(sale_ts, flight_date, day)
            date_factors[day] = factor_text
            date_weights[day] = day_weights[day] * date_factor_multiplier(factor_text)
        allocation = distribute_seats(date_weights, available_seats)
        remaining = available_seats
        for day in range(horizon_days, 0, -1):
            meta = day_meta[day]
            bucket = meta["bucket"]
            sell_count = allocation[day]
            base_price = meta["histAvg"] or fallback_price
            factor_text = date_factors.get(day, "")
            price_multiplier = date_factor_multiplier(factor_text)
            if bucket == high_window:
                price = max(base_price, round(fallback_price * 1.08))
                action = "控量高价测试"
            elif bucket == main_window:
                price = round(base_price * 1.02)
                action = "主推成交"
            elif bucket == volume_window:
                price = round(base_price * 0.96)
                action = "放量转化"
            else:
                price = round(base_price)
                action = "观察/小量测试"
            if factor_text:
                price = max(price, round(base_price * price_multiplier))
            if remaining > available_seats * 0.45 and day <= 4 and not factor_text:
                action = "临近放量清库存"
                price = min(price, round(base_price * 0.94))
            action = date_level_action(action, factor_text, bucket, high_window, volume_window, remaining, available_seats, day)
            sale_date = (flight_date - pd.Timedelta(days=day)).date().isoformat()
            revenue = int(sell_count * price)
            gross_profit = int(sell_count * (price - cost)) if cost else None
            remaining -= sell_count
            factor_note = factor_text or "普通销售日，按历史窗口节奏执行"
            date_strategy = (
                f"{sale_date}按{bucket}单日处理：{factor_note}；"
                f"历史窗口销量{meta['histQty']}张、均价{meta['histAvg']}，建议{sell_count}张，售价{price}。"
            )
            rows.append({
                "航司": airline,
                "航班号": flight_no,
                "航线": route,
                "起飞日期": flight_date.date().isoformat(),
                "当日航班数": flights_per_day,
                "每班座位": seats_per_flight,
                "当日可售座位": available_seats,
                "销售日期": sale_date,
                "提前天数": f"D-{day}",
                "提前窗口": bucket,
                "建议销售张数": sell_count,
                "建议售价": price,
                "预计销售收入": revenue,
                "预计毛利": gross_profit,
                "售后剩余": max(0, remaining),
                "动作": action,
                "日期因素": factor_note,
                "日期策略": date_strategy,
                "依据": f"{flight_identity}，{flight_date.date().isoformat()}当日{flights_per_day}班、每班{seats_per_flight}座、实际可售库存{available_seats}座；{sale_date}为独立销售日；历史{bucket}销量{meta['histQty']}张、均价{meta['histAvg']}；模型主卖{main_window}、高价{high_window}、放量{volume_window}。",
            })

    today_decisions = build_today_decisions(
        route,
        departure_dates,
        decision_ts,
        daily_seats,
        fallback_price,
        calc_by_bucket,
        high_window,
        main_window,
        volume_window,
        cost,
        inventory_by_departure,
    )
    decision_calendar = build_decision_calendar(
        route,
        departure_dates,
        decision_ts,
        daily_seats,
        fallback_price,
        calc_by_bucket,
        high_window,
        main_window,
        volume_window,
        cost,
        inventory_by_departure,
    )
    revenue_total = sum(row["预计销售收入"] for row in rows)
    gross_total = sum(row["预计毛利"] or 0 for row in rows) if cost else None
    avg_price = round(revenue_total / total_seats) if total_seats else 0
    return {
        "route": route,
        "tripType": "单程",
        "airline": airline,
        "flightNo": flight_no,
        "departureDate": departure.date().isoformat(),
        "departureEndDate": end_departure.date().isoformat(),
        "decisionDate": decision_ts.date().isoformat(),
        "decisionDateOptions": [item["决策日期"] for item in decision_calendar],
        "departureDays": len(departure_dates),
        "flightsPerDay": flights_per_day,
        "seatsPerFlight": seats_per_flight,
        "dailySeats": daily_seats,
        "actualInventory": actual_inventory or None,
        "inventoryByDeparture": inventory_by_departure,
        "totalFlights": total_flights,
        "lockedSeats": total_seats,
        "cost": cost or None,
        "revenueEstimate": revenue_total,
        "grossProfitEstimate": gross_total,
        "avgPriceEstimate": avg_price,
        "modelHorizonDays": horizon_days,
        "modelSourceMode": model_source_mode,
        "modelSourceLabel": model_source_label,
        "windows": {"主卖窗口": main_window, "高价窗口": high_window, "放量窗口": volume_window},
        "supply": {
            "sourceMode": route_plan_data.get("sourceMode"),
            "weeklyCapacity": route_plan_data.get("weeklyCapacity"),
            "note": route_plan_data.get("scheduleNote"),
        },
        "basis": [
            f"预测取数口径：{model_source_label}；本次模型周期为提前{horizon_days}天至提前1天。",
            f"销售日历口径：从 {decision_ts.date().isoformat()} 开始逐日生成决策；每个决策日只展示该日以后仍可销售的起飞库存，并按真实提前天数、周几、节假日/暑期因子和剩余销售周期单独生成当日卖几张、卖多少钱。",
            f"库存口径：{'使用实际库存数覆盖航班座位推算' if actual_inventory > 0 else '未填实际库存数，使用航班座位推算'}；单程；{flight_identity}；起飞区间 {departure.date().isoformat()} 至 {end_departure.date().isoformat()}，共{len(departure_dates)}天；每天{flights_per_day}班，每班{seats_per_flight}座，默认每日座位{daily_seats}座，总计{total_flights}班/{total_seats}座。",
            "分配方法：先按各提前窗口历史销量强度分配每个起飞日的可售座位，再对主卖/放量窗口加权，对高价窗口控量。",
            "外部依据：公开航班供给和市场类型只用于校验航线热度、供给规模与风险，不直接替代内部成交数据。",
            "后续可接入航司报价、航信/GDS余位、OTA实时售价后，替换当前价格和余位估算。",
        ],
        "todayDecisions": today_decisions,
        "decisionCalendar": decision_calendar,
        "rows": rows,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, payload, status=HTTPStatus.OK, extra_headers=None):
        body = json.dumps(json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html_file(self, filename):
        body = (ROOT / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, target, extra_headers=None):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", target)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def is_authenticated(self):
        return auth_session_from_cookie(self.headers.get("Cookie"))

    def require_auth(self):
        if self.is_authenticated():
            return True
        self.send_json({"error": "需要登录后访问。"}, HTTPStatus.UNAUTHORIZED)
        return False

    def require_permission(self, permission, message="当前账号没有此操作权限。"):
        session = self.is_authenticated()
        if not session:
            self.send_json({"error": "需要登录后访问。"}, HTTPStatus.UNAUTHORIZED)
            return None
        if not has_permission(session, permission):
            actor, role = session_actor(session)
            append_audit_log(actor, role, "权限拒绝", permission, "失败", message, self.client_address[0])
            self.send_json({"error": message, "permission": permission}, HTTPStatus.FORBIDDEN)
            return None
        return session

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/auth":
            self.send_html_file("auth.html")
            return
        if parsed.path == "/api/auth/status":
            session = self.is_authenticated()
            if session:
                session = {**session, "permissions": session_permissions(session)}
            self.send_json({"authenticated": bool(session), "session": session or {}})
            return
        if parsed.path == "/api/permission-catalog":
            session = self.require_permission("settings.accounts", "需要账号管理权限后查看角色模板。")
            if not session:
                return
            self.send_json(permission_catalog())
            return
        if parsed.path == "/api/accounts":
            session = self.require_permission("settings.accounts", "需要账号管理权限后管理账号。")
            if not session:
                return
            try:
                self.send_json(list_employee_accounts())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/audit-logs":
            session = self.require_permission("settings.logs", "需要日志查看权限。")
            if not session:
                return
            qs = parse_qs(parsed.query)
            try:
                self.send_json(list_audit_logs(
                    qs.get("actor", [""])[0],
                    qs.get("actorName", [""])[0],
                    qs.get("action", [""])[0],
                    qs.get("startDate", [""])[0],
                    qs.get("endDate", [""])[0],
                    qs.get("limit", ["200"])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/":
            if not self.is_authenticated():
                self.send_html_file("auth.html")
                return
            body = (ROOT / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/operation-center":
            qs = parse_qs(parsed.query)
            try:
                collection = qs.get("collection", ["cutInventory"])[0]
                self.send_json(operation_collection_payload(collection))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/api/") and not self.require_auth():
            return
        if parsed.path == "/api/automation-jobs":
            session = self.require_permission("operation.view", "当前账号没有查看自动化预留配置权限。")
            if not session:
                return
            try:
                self.send_json(automation_jobs_payload())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/analyze-default":
            qs = parse_qs(parsed.query)
            target = Path(qs.get("path", [str(DEFAULT_FILE)])[0]).expanduser()
            try:
                self.send_json(parse_workbook(target))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/full-sales-strategy":
            try:
                self.send_json(load_full_sales_strategy())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/ai-analysis-package":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(generate_ai_analysis_package(
                    qs.get("route", [""])[0],
                    qs.get("limit", ["8"])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/ai-analysis-package-download":
            qs = parse_qs(parsed.query)
            try:
                body, filename, content_type = ai_package_export(
                    qs.get("package_id", [""])[0],
                    qs.get("mode", ["package"])[0],
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/ai-analysis-package-prompt":
            qs = parse_qs(parsed.query)
            try:
                package, _ = load_ai_package_by_id(qs.get("package_id", [""])[0])
                self.send_json({"ok": True, "package_id": package.get("package_id"), "prompt": build_ai_package_prompt(package)})
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/route-plan":
            qs = parse_qs(parsed.query)
            route = qs.get("route", ["PKX-CJU"])[0]
            refresh = qs.get("refresh", ["0"])[0] == "1"
            try:
                strategy_df = read_result_csv("route_strategy.csv")
                strategy_rows = clean_records(strategy_df) if not strategy_df.empty else None
                self.send_json(route_plan(route, strategy_rows=strategy_rows, refresh=refresh))
            except Exception as exc:
                message = str(exc).strip() or traceback.format_exc().splitlines()[-1]
                self.send_json({"error": message, "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/sales-cycle-plan":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(sales_cycle_plan(
                    qs.get("route", ["BKK-KUL"])[0],
                    qs.get("seats", ["40"])[0],
                    qs.get("departure", [""])[0],
                    qs.get("cost", ["0"])[0],
                    qs.get("departureEnd", [""])[0],
                    qs.get("flightsPerDay", ["1"])[0],
                    qs.get("seatsPerFlight", ["0"])[0],
                    qs.get("airline", [""])[0],
                    qs.get("flightNo", [""])[0],
                    qs.get("horizonDays", ["0"])[0],
                    qs.get("modelSourceMode", ["mixedForecast"])[0],
                    qs.get("decisionDate", [""])[0],
                    actual_inventory=qs.get("actualInventory", ["0"])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/nightly-sales-review":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(nightly_sales_review(
                    route=qs.get("route", ["BKK-KUL"])[0],
                    review_date=qs.get("reviewDate", [""])[0],
                    seats=qs.get("seats", ["40"])[0],
                    departure_date=qs.get("departure", [""])[0],
                    cost=qs.get("cost", ["0"])[0],
                    departure_end=qs.get("departureEnd", [""])[0],
                    flights_per_day=qs.get("flightsPerDay", ["1"])[0],
                    seats_per_flight=qs.get("seatsPerFlight", ["0"])[0],
                    airline=qs.get("airline", [""])[0],
                    flight_no=qs.get("flightNo", [""])[0],
                    horizon_days=qs.get("horizonDays", ["0"])[0],
                    model_source_mode=qs.get("modelSourceMode", ["mixedForecast"])[0],
                    actual_inventory=qs.get("actualInventory", ["0"])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/price-adjustment-backtest":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(price_adjustment_backtest(
                    route=qs.get("route", ["PKX-CJU"])[0],
                    seats=qs.get("seats", ["40"])[0],
                    departure_date=qs.get("departure", [""])[0],
                    cost=qs.get("cost", ["0"])[0],
                    departure_end=qs.get("departureEnd", [""])[0],
                    flights_per_day=qs.get("flightsPerDay", ["1"])[0],
                    seats_per_flight=qs.get("seatsPerFlight", ["0"])[0],
                    airline=qs.get("airline", [""])[0],
                    flight_no=qs.get("flightNo", [""])[0],
                    horizon_days=qs.get("horizonDays", ["0"])[0],
                    model_source_mode=qs.get("modelSourceMode", ["mixedForecast"])[0],
                    decision_date=qs.get("decisionDate", [""])[0],
                    actual_inventory=qs.get("actualInventory", ["0"])[0],
                    cost_floor=qs.get("costFloor", ["0"])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/model-calibration":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(model_calibration_compare(
                    qs.get("route", [""])[0],
                    qs.get("actualVolumeWindow", [""])[0],
                    qs.get("actualHighWindow", [""])[0],
                    qs.get("actualSales", [""])[0],
                    qs.get("actualRevenue", [""])[0],
                    qs.get("actualProfit", [""])[0],
                    qs.get("modelSourceMode", ["mixedForecast"])[0],
                    qs.get("actualSourceMode", ["realImported"])[0],
                    qs.get("horizonDays", ["0"])[0],
                    qs.get("departure", [""])[0],
                    qs.get("departureEnd", [""])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/actual-result-model":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(actual_result_model_response(
                    qs.get("route", [""])[0],
                    qs.get("actualSourceMode", ["realImported"])[0],
                    qs.get("actualVolumeWindow", [""])[0],
                    qs.get("actualHighWindow", [""])[0],
                    qs.get("actualSales", [""])[0],
                    qs.get("actualRevenue", [""])[0],
                    qs.get("actualProfit", [""])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/data-status":
            try:
                self.send_json(data_status())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/operation-center-export":
            qs = parse_qs(parsed.query)
            try:
                session = self.require_permission("operation.export", "当前账号没有导出运营中心数据权限。")
                if not session:
                    return
                collection = qs.get("collection", ["cutInventory"])[0]
                save_dir = qs.get("saveDir", [""])[0].strip()
                body, filename, count = operation_export_xlsx(collection)
                if save_dir:
                    target_dir = Path(save_dir).expanduser()
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / filename
                    target.write_bytes(body)
                    self.send_json({"ok": True, "savedPath": str(target), "filename": filename, "count": count})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f"attachment; filename=\"operation-export.xlsx\"; filename*=UTF-8''{quote(filename)}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/integration-blueprint":
            try:
                self.send_json(integration_blueprint())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if is_execution_task_api(parsed.path):
            qs = parse_qs(parsed.query)
            try:
                self.send_json(generate_execution_tasks(
                    qs.get("route", [""])[0],
                    qs.get("channel", ["人工确认"])[0],
                    qs.get("limit", ["20"])[0],
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if is_execution_task_store_api(parsed.path):
            try:
                self.send_json(execution_task_store_payload())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path == "/api/auth/admin-login-page":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8")
                payload = parse_qs(raw)
                password = payload.get("password", [""])[0]
                token, session = admin_login(password)
                max_age = max(1, int(session["expiresAt"] - now_ts()))
                self.redirect(
                    "/",
                    {"Set-Cookie": f"air_skill_session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"},
                )
            except Exception as exc:
                message = str(exc) or "管理员登录失败"
                body = f"""<!doctype html><meta charset="utf-8"><title>登录失败</title>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:32px;">
<h2>管理员登录失败</h2><p>{message}</p><p><a href="/auth">返回登录页</a></p></body>""".encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if self.path == "/api/auth/admin-login":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                token, session = admin_login(payload.get("password", ""))
                max_age = max(1, int(session["expiresAt"] - now_ts()))
                self.send_json(
                    {"ok": True, "session": session},
                    extra_headers={"Set-Cookie": f"air_skill_session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"},
                )
            except Exception as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/auth/employee-login":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                token, session = login_with_employee(payload.get("employeeId", ""), payload.get("password", ""))
                max_age = max(1, int(session["expiresAt"] - now_ts()))
                self.send_json(
                    {"ok": True, "session": session},
                    extra_headers={"Set-Cookie": f"air_skill_session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"},
                )
            except Exception as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/accounts":
            session = self.require_permission("settings.accounts", "需要账号管理权限后管理账号。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                result = upsert_employee_account(
                    payload.get("employeeId", ""),
                    payload.get("name", ""),
                    payload.get("password", ""),
                    payload.get("role", "employee"),
                    payload.get("status", "active"),
                    payload.get("validityMode", "longTerm"),
                    payload.get("customExpiresAt", ""),
                    payload.get("permissions"),
                )
                actor, role = session_actor(session)
                append_audit_log(actor, role, result.get("action", "保存员工账号"), result.get("account", {}).get("employeeId", ""), "成功", result.get("account", {}).get("name", ""), self.client_address[0])
                self.send_json(result)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "保存员工账号", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/accounts/status":
            session = self.require_permission("settings.accounts", "需要账号管理权限后管理账号。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                result = set_employee_status(payload.get("employeeId", ""), payload.get("status", "active"))
                actor, role = session_actor(session)
                append_audit_log(actor, role, "切换员工状态", result.get("account", {}).get("employeeId", ""), "成功", result.get("account", {}).get("status", ""), self.client_address[0])
                self.send_json(result)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "切换员工状态", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/accounts/delete":
            session = self.require_permission("settings.accounts", "需要账号管理权限后管理账号。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                result = delete_employee_account(payload.get("employeeId", ""))
                actor, role = session_actor(session)
                append_audit_log(actor, role, "删除员工账号", result.get("account", {}).get("employeeId", ""), "成功", result.get("account", {}).get("name", ""), self.client_address[0])
                self.send_json(result)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "删除员工账号", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/auth/create-pass":
            session = self.is_authenticated()
            if not session or session.get("role") != "admin":
                self.send_json({"error": "需要管理员登录后生成授权。"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                result = create_access_pass(payload.get("phone"), payload.get("hours", 1), payload.get("note", ""))
                actor, role = session_actor(session)
                append_audit_log(actor, role, "生成访客授权", result.get("phone", ""), "成功", f"{result.get('hours')}小时 {result.get('note', '')}", self.client_address[0])
                self.send_json(result)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "生成访客授权", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/auth/change-admin-password":
            session = self.is_authenticated()
            if not session or session.get("role") != "admin":
                self.send_json({"error": "需要管理员登录后修改密码。"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                result = change_admin_password(payload.get("oldPassword", ""), payload.get("newPassword", ""))
                actor, role = session_actor(session)
                append_audit_log(actor, role, "修改管理员密码", "admin", "成功", "", self.client_address[0])
                self.send_json(result)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "修改管理员密码", "admin", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/auth/login":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                token, session = login_with_access(payload.get("phone"), payload.get("accessPassword"), payload.get("smsCode"))
                max_age = max(1, int(session["expiresAt"] - now_ts()))
                self.send_json(
                    {"ok": True, "session": session},
                    extra_headers={"Set-Cookie": f"air_skill_session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"},
                )
            except Exception as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/auth/logout":
            session = self.is_authenticated()
            actor, role = session_actor(session)
            revoke_session(self.headers.get("Cookie"))
            append_audit_log(actor, role, "退出登录", actor, "成功", "", self.client_address[0])
            self.send_json({"ok": True}, extra_headers={"Set-Cookie": "air_skill_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
            return
        if self.path == "/api/mock-ota/order-callback":
            if not verify_mock_ota_token(self.headers):
                self.send_json({"ok": False, "error": "Mock OTA token 校验失败"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(handle_mock_ota_order_callback(payload, self.client_address[0]))
            except Exception as exc:
                append_audit_log("Mock OTA", "外部渠道", "Mock OTA订单回流", "", "失败", str(exc), self.client_address[0])
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/mock-ota/publish":
            session = self.require_permission("execution.manage", "当前账号没有发布政策到 Mock OTA 的权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
                self.send_json(publish_policies_to_channels(session, payload.get("channels"), self.client_address[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc(), "mockOtaBaseUrl": MOCK_OTA_BASE_URL}, HTTPStatus.BAD_REQUEST)
            return
        if self.path.startswith("/api/") and not self.require_auth():
            return
        if self.path == "/api/table-export":
            session = self.require_permission("operation.export", "当前账号没有导出表格数据权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
                title = str(payload.get("title") or "导出表格").strip()
                fields = [str(item) for item in payload.get("fields", [])]
                source_rows = payload.get("rows", [])
                if not fields:
                    raise ValueError("导出表格缺少字段")
                if not isinstance(source_rows, list):
                    raise ValueError("导出表格数据格式不正确")
                rows = []
                for source in source_rows:
                    if isinstance(source, dict):
                        rows.append([source.get(field, "") for field in fields])
                    elif isinstance(source, list):
                        rows.append(source[:len(fields)])
                body, filename, count = build_xlsx_workbook(title, fields, rows)
                save_dir = str(payload.get("saveDir") or "").strip()
                if save_dir:
                    target_dir = Path(save_dir).expanduser()
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / filename
                    target.write_bytes(body)
                    self.send_json({"ok": True, "savedPath": str(target), "filename": filename, "count": count})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f"attachment; filename=\"table-export.xlsx\"; filename*=UTF-8''{quote(filename)}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "导出表格数据", "table-export", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/clear-data":
            session = self.require_permission("data.manage", "当前账号没有数据清理权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                targets = payload.get("targets", [])
                if not isinstance(targets, list):
                    raise ValueError("清空目标格式不正确")
                self.send_json(clear_data_targets([str(item) for item in targets]))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/automation-jobs":
            session = self.require_permission("operation.write", "当前账号没有保存自动化预留配置权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(save_automation_job_config(payload, session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "保存自动化预留配置", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/automation-run-now":
            session = self.require_permission("operation.bulk", "当前账号没有触发自动化预留执行权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(automation_run_now_placeholder(payload, session, self.client_address[0]), HTTPStatus.ACCEPTED)
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "触发自动化预留执行", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center":
            session = self.require_permission("operation.write", "当前账号没有保存运营中心记录权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                collection = str(payload.get("collection", "cutInventory"))
                if payload.get("action") == "delete":
                    self.send_json(delete_operation_record(collection, payload.get("id", ""), session, self.client_address[0]))
                elif payload.get("action") == "set-status":
                    self.send_json(set_operation_record_status(
                        collection,
                        payload.get("id", ""),
                        payload.get("field", ""),
                        payload.get("enabled", False),
                        session,
                        self.client_address[0],
                    ))
                else:
                    self.send_json(upsert_operation_record(collection, payload.get("record", payload), session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "保存运营中心记录", payload.get("collection", "") if "payload" in locals() else "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-bulk":
            session = self.require_permission("operation.bulk", "当前账号没有批量处理运营中心记录权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(operation_bulk_action(
                    str(payload.get("collection", "cutInventory")),
                    str(payload.get("action", "")),
                    payload.get("ids", []),
                    session,
                    self.client_address[0],
                ))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "批量处理运营中心记录", payload.get("collection", "") if "payload" in locals() else "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-import-inventory":
            session = self.require_permission("operation.bulk", "当前账号没有批量导入切位库存权限。")
            if not session:
                return
            tmp_path = None
            try:
                content_type = self.headers.get("Content-Type", "")
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
                )
                file_item = form["file"] if "file" in form else None
                filename = Path(getattr(file_item, "filename", "") or "").name
                if file_item is None or not filename:
                    raise ValueError("请先选择库存 Excel。")
                suffix = Path(filename).suffix.lower()
                if suffix not in {".xlsx", ".xls"}:
                    raise ValueError("只支持 .xlsx 或 .xls 库存 Excel。")
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file_item.file.read())
                    tmp_path = Path(tmp.name)
                self.send_json(import_cut_inventory_excel(tmp_path, filename, session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "批量导入切位库存", "cutInventory", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
            return
        if self.path == "/api/operation-center-seed-demo-orders":
            session = self.require_permission("operation.bulk", "当前账号没有生成模拟订单权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
                self.send_json(seed_demo_orders(session, self.client_address[0], payload.get("count", 20)))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "生成模拟订单", "orders", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-sync-inventory":
            session = self.require_permission("operation.bulk", "当前账号没有订单库存联动权限。")
            if not session:
                return
            try:
                self.send_json(sync_orders_to_inventory(session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "订单库存联动同步", "cutInventory", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-sync-platforms":
            session = self.require_permission("operation.bulk", "当前账号没有接口平台联动权限。")
            if not session:
                return
            try:
                self.send_json(sync_platforms_to_store_channels(session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "接口平台同步店铺渠道", "stores/channels", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-sync-ticket-tasks":
            session = self.require_permission("operation.bulk", "当前账号没有订单出票联动权限。")
            if not session:
                return
            try:
                self.send_json(sync_orders_to_ticket_tasks(session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "订单同步出票任务", "ticketTasks", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-ticket-process":
            session = self.require_permission("operation.write", "当前账号没有处理出票任务权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
                self.send_json(process_ticket_task(
                    payload.get("id", ""),
                    payload.get("mode", ""),
                    payload,
                    session,
                    self.client_address[0],
                ))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "处理出票任务", payload.get("id", "") if "payload" in locals() else "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-sync-ticket-checks":
            session = self.require_permission("operation.bulk", "当前账号没有出票验票联动权限。")
            if not session:
                return
            try:
                self.send_json(sync_ticket_tasks_to_checks(session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "出票任务同步验票记录", "ticketChecks", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-post-ticket-process":
            session = self.require_permission("operation.write", "当前账号没有处理验票或支付回填的权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
                self.send_json(process_post_ticket_record(
                    str(payload.get("collection", "")),
                    payload.get("id", ""),
                    payload.get("mode", ""),
                    payload,
                    session,
                    self.client_address[0],
                ))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "处理出票后流程", payload.get("id", "") if "payload" in locals() else "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-sync-after-sales":
            session = self.require_permission("operation.bulk", "当前账号没有退改售后联动权限。")
            if not session:
                return
            try:
                self.send_json(sync_refunds_to_after_sales(session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "退改订单同步售后工单", "afterSalesCases", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-sync-payment-returns":
            session = self.require_permission("operation.bulk", "当前账号没有订单支付回填联动权限。")
            if not session:
                return
            try:
                self.send_json(sync_orders_to_payment_returns(session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "订单同步支付回填", "paymentReturns", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/operation-center-statistics":
            session = self.require_permission("operation.view", "当前账号没有查看运营统计权限。")
            if not session:
                return
            try:
                self.send_json(operation_statistics())
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if is_execution_task_api(self.path):
            session = self.require_permission("execution.manage", "当前账号没有生成策略执行任务权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(generate_execution_tasks(
                    payload.get("route", ""),
                    payload.get("channel", "人工确认"),
                    payload.get("limit", 20),
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/ai-analysis-package":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(generate_ai_analysis_package(
                    payload.get("route", ""),
                    payload.get("limit", 8),
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/ai-suggestion-import":
            session = self.require_permission("ai.manage", "当前账号没有导入外部AI建议权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(import_external_ai_suggestion(payload, session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "导入外部AI建议至建议池", payload.get("package_id", "") if "payload" in locals() else "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/price-adjustment-import":
            session = self.require_permission("ai.manage", "当前账号没有导入回测规则权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self.send_json(import_price_adjustment_rules(payload, session, self.client_address[0]))
            except Exception as exc:
                actor, role = session_actor(session)
                append_audit_log(actor, role, "导入回测规则至建议池", payload.get("route", "") if "payload" in locals() else "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/inventory":
            session = self.require_permission("operation.write", "当前账号没有保存库存准备权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                rows = load_inventory()
                row = {
                    "航线": normalize_route(str(payload.get("航线", ""))),
                    "航司": str(payload.get("航司", "")).strip(),
                    "航班日期": str(payload.get("航班日期", "")).strip(),
                    "锁定位": int(number_value(payload.get("锁定位"))),
                    "已售": int(number_value(payload.get("已售"))),
                    "成本价": payload.get("成本价", ""),
                    "销售价": payload.get("销售价", ""),
                    "当前窗口": payload.get("当前窗口", ""),
                    "预计投放": str(payload.get("预计投放", "")).strip(),
                    "备注": payload.get("备注", ""),
                }
                if not row["航线"] or row["航线"] == "-":
                    raise ValueError("请填写航线")
                rows.append(row)
                save_inventory(rows)
                self.send_json({"ok": True, "inventory": rows})
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if is_execution_task_action_api(self.path):
            session = self.require_permission("execution.manage", "当前账号没有策略执行任务操作权限。")
            if not session:
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                result = update_execution_task(
                    str(payload.get("taskId", "")),
                    str(payload.get("action", "")),
                    str(payload.get("operator", "人工确认")),
                    str(payload.get("platform", "")),
                )
                actor, role = session_actor(session)
                append_audit_log(actor, role, "策略执行任务操作", str(payload.get("taskId", "")), "成功", str(payload.get("action", "")), self.client_address[0])
                self.send_json(result)
            except Exception as exc:
                actor, role = session_actor(self.is_authenticated())
                append_audit_log(actor, role, "策略执行任务操作", "", "失败", str(exc), self.client_address[0])
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/sales-cycle-plan-file":
            tmp_path = None
            try:
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
                file_item = form["file"] if "file" in form else None
                if file_item is None or not getattr(file_item, "filename", ""):
                    raise ValueError("请先选择本次模型使用的本地Excel。")
                suffix = Path(file_item.filename).suffix or ".xlsx"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file_item.file.read())
                    tmp_path = Path(tmp.name)
                parsed = parse_workbook(tmp_path, getattr(file_item, "filename", "") or "")
                self.send_json(sales_cycle_plan(
                    route=form.getfirst("route", "BKK-KUL"),
                    seats=form.getfirst("seats", "40"),
                    departure_date=form.getfirst("departure", ""),
                    cost=form.getfirst("cost", "0"),
                    departure_end=form.getfirst("departureEnd", ""),
                    flights_per_day=form.getfirst("flightsPerDay", "1"),
                    seats_per_flight=form.getfirst("seatsPerFlight", "0"),
                    airline=form.getfirst("airline", ""),
                    flight_no=form.getfirst("flightNo", ""),
                    horizon_days=form.getfirst("horizonDays", "0"),
                    model_source_mode="localExcel",
                    decision_date=form.getfirst("decisionDate", ""),
                    strategy_rows_override=parsed.get("strategy", []),
                    calc_records_override=parsed.get("calc", []),
                    model_source_label_override=f"指定本地Excel：{Path(file_item.filename).name}",
                    actual_inventory=form.getfirst("actualInventory", "0"),
                ))
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
            return
        if self.path == "/api/actual-result-model-file":
            tmp_path = None
            try:
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
                file_item = form["file"] if "file" in form else None
                if file_item is None or not getattr(file_item, "filename", ""):
                    raise ValueError("请先选择真实结果使用的本地Excel。")
                suffix = Path(file_item.filename).suffix or ".xlsx"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file_item.file.read())
                    tmp_path = Path(tmp.name)
                parsed = parse_workbook(tmp_path, getattr(file_item, "filename", "") or "")
                actual_data = actual_model_from_real_data(
                    normalize_route(form.getfirst("route", "")),
                    "localActualExcel",
                    parsed.get("strategy", []),
                    parsed.get("calc", []),
                    f"指定真实Excel：{Path(file_item.filename).name}",
                )
                self.send_json({
                    "route": normalize_route(form.getfirst("route", "")),
                    "actual": actual_data["summary"],
                    "bucketRows": actual_data["bucketRows"],
                    "basis": [
                        f"真实结果取数位置：{actual_data['summary']['数据来源']}。",
                        "该结果模型来自本次选择的真实已发生销售Excel，只用于本次校准。",
                    ],
                })
            except Exception as exc:
                self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
            return
        if self.path != "/api/analyze":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
        file_item = form["file"] if "file" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            self.send_json({"error": "没有收到 Excel 文件"}, HTTPStatus.BAD_REQUEST)
            return
        suffix = Path(file_item.filename).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_item.file.read())
            tmp_path = Path(tmp.name)
        try:
            self.send_json(parse_workbook(tmp_path, getattr(file_item, "filename", "") or ""))
        except Exception as exc:
            self.send_json({"error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer((AIRLINE_LOCAL_HOST, AIRLINE_LOCAL_PORT), Handler)
    print(f"航空航线收益优化智能执行平台已启动：http://{AIRLINE_LOCAL_HOST}:{AIRLINE_LOCAL_PORT}")
    server.serve_forever()
