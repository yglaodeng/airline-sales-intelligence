from __future__ import annotations

import json
import os
import secrets
import time
import traceback
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
POLICY_FILE = DATA_DIR / "policies.json"
ORDER_FILE = DATA_DIR / "orders.json"
LOG_FILE = DATA_DIR / "logs.json"
FLIGHT_STATUS_FILE = DATA_DIR / "flight_status.json"

TOKEN = os.environ.get("MOCK_OTA_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("请先设置 MOCK_OTA_TOKEN 环境变量。")
MAIN_SYSTEM_BASE_URL = os.environ.get("MAIN_SYSTEM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PORT = int(os.environ.get("MOCK_OTA_PORT", "8010"))


def now_ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def write_json(path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def append_log(action, result="成功", detail="", trace_id=""):
    rows = load_json(LOG_FILE, [])
    row = {
        "id": f"LOG-{int(time.time())}-{secrets.token_hex(3)}",
        "time": now_ts(),
        "trace_id": trace_id or f"trace-{secrets.token_hex(6)}",
        "action": action,
        "result": result,
        "detail": detail,
    }
    rows.insert(0, row)
    write_json(LOG_FILE, rows[:500])
    return row


def public_policy(row):
    safe = dict(row)
    safe["inventory"] = int(safe.get("inventory") or 0)
    safe["sold"] = int(safe.get("sold") or 0)
    safe["available"] = max(0, safe["inventory"] - safe["sold"])
    return safe


def active_policies():
    rows = load_json(POLICY_FILE, [])
    now_day = time.strftime("%Y-%m-%d")
    result = []
    for row in rows:
        if str(row.get("status", "")).strip() not in {"上架", "销售中", "启用", "active"}:
            continue
        valid_to = str(row.get("valid_to", "")).strip()
        if valid_to and valid_to < now_day:
            continue
        item = public_policy(row)
        if item["available"] > 0:
            result.append(item)
    return result


def flight_key(row):
    return "|".join([
        str(row.get("policy_id") or ""),
        str(row.get("flight_no") or ""),
        str(row.get("departure_date") or ""),
    ])


def flight_status_rows():
    policies = active_policies()
    saved = load_json(FLIGHT_STATUS_FILE, {})
    rows = []
    for index, policy in enumerate(policies):
        key = flight_key(policy)
        current = saved.get(key, {}) if isinstance(saved, dict) else {}
        rows.append({
            "key": key,
            "policy_id": policy.get("policy_id", ""),
            "route": policy.get("route", ""),
            "airline": policy.get("airline", ""),
            "flight_no": policy.get("flight_no", ""),
            "departure_date": policy.get("departure_date", ""),
            "cabin": policy.get("cabin", ""),
            "status": current.get("status") or "计划",
            "gate": current.get("gate") or f"G{20 + index}",
            "delay_minutes": int(current.get("delay_minutes") or 0),
            "reason": current.get("reason") or "",
            "updated_at": current.get("updated_at") or "",
        })
    return rows


def special_fare_rows():
    rows = active_policies()
    prices = [float(row.get("sale_price") or 0) for row in rows if float(row.get("sale_price") or 0) > 0]
    if not prices:
        return []
    threshold = sum(prices) / len(prices)
    specials = []
    for row in rows:
        price = float(row.get("sale_price") or 0)
        available = int(row.get("available") or 0)
        if price <= threshold or available <= 3:
            item = dict(row)
            item["special_reason"] = "低于均价" if price <= threshold else "余位紧张"
            item["special_threshold"] = round(threshold, 2)
            specials.append(item)
    return sorted(specials, key=lambda item: float(item.get("sale_price") or 0))


def callback_to_main_system(order, action, trace_id):
    payload = {
        "trace_id": trace_id,
        "action": action,
        "source": "Mock OTA",
        "order": order,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{MAIN_SYSTEM_BASE_URL}/api/mock-ota/order-callback",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Mock-OTA-Token": TOKEN,
            "X-Trace-Id": trace_id,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Mock-OTA-Token, X-Trace-Id")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def require_token(self):
        token = self.headers.get("X-Mock-OTA-Token") or ""
        if token == TOKEN:
            return True
        self.send_json({"ok": False, "error": "Mock OTA token 校验失败"}, HTTPStatus.UNAUTHORIZED)
        return False

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Mock-OTA-Token, X-Trace-Id")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = (ROOT / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/policies":
            qs = parse_qs(parsed.query)
            include_all = qs.get("all", ["0"])[0] == "1"
            rows = load_json(POLICY_FILE, []) if include_all else active_policies()
            self.send_json({"ok": True, "rows": [public_policy(row) for row in rows], "count": len(rows)})
            return
        if parsed.path == "/api/orders":
            rows = load_json(ORDER_FILE, [])
            self.send_json({"ok": True, "rows": rows, "count": len(rows)})
            return
        if parsed.path == "/api/flight-status":
            rows = flight_status_rows()
            self.send_json({"ok": True, "rows": rows, "count": len(rows)})
            return
        if parsed.path == "/api/special-fares":
            rows = special_fare_rows()
            self.send_json({"ok": True, "rows": rows, "count": len(rows)})
            return
        if parsed.path == "/api/logs":
            rows = load_json(LOG_FILE, [])
            self.send_json({"ok": True, "rows": rows[:120], "count": len(rows)})
            return
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "mock-ota", "time": now_ts()})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        trace_id = self.headers.get("X-Trace-Id") or f"trace-{secrets.token_hex(6)}"
        if parsed.path == "/api/policies/upsert":
            if not self.require_token():
                return
            try:
                payload = self.read_payload()
                incoming = payload.get("policies", payload.get("policy", []))
                if isinstance(incoming, dict):
                    incoming = [incoming]
                if not isinstance(incoming, list):
                    raise ValueError("policies 必须是数组或对象")
                rows = load_json(POLICY_FILE, [])
                by_id = {str(row.get("policy_id")): row for row in rows if row.get("policy_id")}
                for item in incoming:
                    if not isinstance(item, dict) or not item.get("policy_id"):
                        continue
                    current = by_id.get(str(item["policy_id"]), {})
                    merged = {**current, **item, "updated_at": now_ts()}
                    by_id[str(item["policy_id"])] = merged
                saved = list(by_id.values())
                write_json(POLICY_FILE, saved)
                append_log("接收主系统政策发布", "成功", f"upsert={len(incoming)} total={len(saved)}", trace_id)
                self.send_json({"ok": True, "count": len(incoming), "total": len(saved), "trace_id": trace_id})
            except Exception as exc:
                append_log("接收主系统政策发布", "失败", str(exc), trace_id)
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/orders/create":
            try:
                payload = self.read_payload()
                policy_id = str(payload.get("policy_id", "")).strip()
                passenger = str(payload.get("passenger", "测试旅客")).strip() or "测试旅客"
                quantity = max(1, int(payload.get("quantity") or 1))
                policies = load_json(POLICY_FILE, [])
                policy = next((row for row in policies if str(row.get("policy_id")) == policy_id), None)
                if not policy:
                    raise ValueError("政策不存在")
                item = public_policy(policy)
                if str(item.get("status")) not in {"上架", "销售中", "启用", "active"}:
                    raise ValueError("政策未上架")
                if item["available"] < quantity:
                    raise ValueError("库存不足，禁止超卖")
                policy["sold"] = int(policy.get("sold") or 0) + quantity
                policy["updated_at"] = now_ts()
                order = {
                    "order_id": f"MOTA-{time.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
                    "policy_id": policy_id,
                    "source_inventory_id": policy.get("source_inventory_id", ""),
                    "channel": "Mock OTA",
                    "route": policy.get("route", ""),
                    "airline": policy.get("airline", ""),
                    "flight_no": policy.get("flight_no", ""),
                    "departure_date": policy.get("departure_date", ""),
                    "cabin": policy.get("cabin", ""),
                    "passenger": passenger,
                    "quantity": quantity,
                    "sale_price": policy.get("sale_price", ""),
                    "amount": float(policy.get("sale_price") or 0) * quantity,
                    "status": "已下单",
                    "created_at": now_ts(),
                    "trace_id": trace_id,
                }
                orders = load_json(ORDER_FILE, [])
                orders.insert(0, order)
                write_json(POLICY_FILE, policies)
                write_json(ORDER_FILE, orders)
                callback = callback_to_main_system(order, "create", trace_id)
                append_log("模拟下单并回调主系统", "成功", f"{order['order_id']} callback={callback.get('ok')}", trace_id)
                self.send_json({"ok": True, "order": order, "callback": callback, "trace_id": trace_id})
            except Exception as exc:
                append_log("模拟下单并回调主系统", "失败", str(exc), trace_id)
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/orders/cancel":
            try:
                payload = self.read_payload()
                order_id = str(payload.get("order_id", "")).strip()
                orders = load_json(ORDER_FILE, [])
                order = next((row for row in orders if str(row.get("order_id")) == order_id), None)
                if not order:
                    raise ValueError("订单不存在")
                if order.get("status") == "已取消":
                    raise ValueError("订单已取消，不能重复取消")
                order["status"] = "已取消"
                order["cancelled_at"] = now_ts()
                policies = load_json(POLICY_FILE, [])
                policy = next((row for row in policies if str(row.get("policy_id")) == str(order.get("policy_id"))), None)
                if policy:
                    policy["sold"] = max(0, int(policy.get("sold") or 0) - int(order.get("quantity") or 1))
                    policy["updated_at"] = now_ts()
                write_json(POLICY_FILE, policies)
                write_json(ORDER_FILE, orders)
                callback = callback_to_main_system(order, "cancel", trace_id)
                append_log("取消订单并回调主系统", "成功", f"{order_id} callback={callback.get('ok')}", trace_id)
                self.send_json({"ok": True, "order": order, "callback": callback, "trace_id": trace_id})
            except Exception as exc:
                append_log("取消订单并回调主系统", "失败", str(exc), trace_id)
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/flight-status/update":
            try:
                payload = self.read_payload()
                key = str(payload.get("key", "")).strip()
                status = str(payload.get("status", "")).strip()
                if not key or not status:
                    raise ValueError("航班状态 key 和 status 不能为空")
                allowed = {"计划", "准点", "延误", "取消", "恢复"}
                if status not in allowed:
                    raise ValueError(f"状态必须是：{'、'.join(sorted(allowed))}")
                saved = load_json(FLIGHT_STATUS_FILE, {})
                if not isinstance(saved, dict):
                    saved = {}
                delay = max(0, int(payload.get("delay_minutes") or (30 if status == "延误" else 0)))
                saved[key] = {
                    "status": status,
                    "gate": str(payload.get("gate") or saved.get(key, {}).get("gate") or "G20"),
                    "delay_minutes": delay,
                    "reason": str(payload.get("reason") or ("联调模拟延误" if status == "延误" else "")),
                    "updated_at": now_ts(),
                }
                if status == "恢复":
                    saved[key]["status"] = "准点"
                    saved[key]["delay_minutes"] = 0
                    saved[key]["reason"] = "已恢复正常"
                write_json(FLIGHT_STATUS_FILE, saved)
                append_log("更新航班动态", "成功", f"{key} status={saved[key]['status']}", trace_id)
                self.send_json({"ok": True, "row": {"key": key, **saved[key]}, "trace_id": trace_id})
            except Exception as exc:
                append_log("更新航班动态", "失败", str(exc), trace_id)
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/orders/status":
            if not self.require_token():
                return
            try:
                payload = self.read_payload()
                order_id = str(payload.get("order_id", "")).strip()
                if not order_id:
                    raise ValueError("订单号不能为空")
                orders = load_json(ORDER_FILE, [])
                order = next((row for row in orders if str(row.get("order_id")) == order_id), None)
                if not order:
                    raise ValueError("订单不存在")
                order["status"] = str(payload.get("status") or order.get("status") or "").strip() or "已出票"
                order["pnr"] = str(payload.get("pnr") or order.get("pnr") or "").strip()
                order["ticket_no"] = str(payload.get("ticket_no") or order.get("ticket_no") or "").strip()
                order["ticket_account"] = str(payload.get("ticket_account") or order.get("ticket_account") or "").strip()
                order["ticketed_at"] = now_ts()
                order["updated_at"] = now_ts()
                write_json(ORDER_FILE, orders)
                append_log("接收主系统出票状态回填", "成功", f"{order_id} status={order['status']} ticket={order.get('ticket_no', '')}", trace_id)
                self.send_json({"ok": True, "order": order, "trace_id": trace_id})
            except Exception as exc:
                append_log("接收主系统出票状态回填", "失败", str(exc), trace_id)
                self.send_json({"ok": False, "error": str(exc), "detail": traceback.format_exc()}, HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Mock OTA running at http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
