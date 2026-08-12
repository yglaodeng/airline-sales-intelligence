#!/usr/bin/env python3
"""Destructive end-to-end smoke test for an isolated airline + Mock OTA sandbox."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from datetime import date, timedelta


AIR = os.environ.get("AIRLINE_TEST_URL", "http://127.0.0.1:18000")
MOCK = os.environ.get("MOCK_OTA_TEST_URL", "http://127.0.0.1:18010")
PASSWORD = os.environ.get("AIR_SKILL_ADMIN_PASSWORD", "")
TODAY = date.today()
DEPARTURE = (TODAY + timedelta(days=8)).isoformat()
DEPARTURE_END = (TODAY + timedelta(days=10)).isoformat()

COLLECTIONS = [
    "stores", "storePullRules", "storeLogs", "channels", "airlineData",
    "policyAccounts", "banRules", "crawlRules", "priceAdjustRules",
    "directConnectRules", "priceCompareTasks", "fareQueries", "ticketAccounts",
    "ticketSettings", "ticketChannels", "contacts", "policyRules", "cutInventory",
    "orders", "ticketTasks", "ticketOrdersView", "pendingTicketsView",
    "exceptionTicketsView", "completedTicketsView", "unclaimedTicketsView",
    "claimPendingView", "flightChanges", "ticketConsole", "inventoryStatsView",
    "teamInventory", "refundChangeOrders", "ticketChecks", "afterSalesCases",
    "paymentReturns", "interfaceMonitor", "interfaceTests", "interfaceOnboarding",
]
VIRTUAL = {
    "ticketOrdersView", "pendingTicketsView", "exceptionTicketsView",
    "completedTicketsView", "unclaimedTicketsView", "claimPendingView",
    "inventoryStatsView",
}

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
checks: list[dict] = []


def request(method: str, url: str, payload=None, headers=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json; charset=utf-8", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            data = json.loads(raw.decode("utf-8")) if "json" in content_type else raw
            return resp.status, data
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = raw.decode("utf-8", errors="replace")
        return exc.code, data


def check(name: str, condition: bool, detail=""):
    checks.append({"name": name, "passed": bool(condition), "detail": detail})
    if not condition:
        raise AssertionError(f"{name}: {detail}")


def get(path: str):
    return request("GET", AIR + path)


def post(path: str, payload=None):
    return request("POST", AIR + path, payload or {})


def main():
    check("管理员测试密码已设置", bool(PASSWORD), "AIR_SKILL_ADMIN_PASSWORD")
    code, _ = get("/api/data-status")
    check("未登录保护", code == 401, code)
    code, login = post("/api/auth/admin-login", {"password": PASSWORD})
    check("管理员登录", code == 200 and login.get("ok"), login)

    for path in [
        "/api/auth/status", "/api/permission-catalog", "/api/accounts",
        "/api/audit-logs?limit=20", "/api/automation-jobs", "/api/data-status",
        "/api/integration-blueprint", "/api/strategy-execution-task-store",
    ]:
        code, data = get(path)
        check(f"GET {path}", code == 200 and isinstance(data, dict), {"code": code, "data": data})

    analytics = [
        "/api/full-sales-strategy",
        "/api/route-plan?route=PKX-CJU",
        f"/api/sales-cycle-plan?route=PKX-CJU&seats=20&departure={DEPARTURE}&departureEnd={DEPARTURE_END}&cost=600&decisionDate={TODAY.isoformat()}",
        f"/api/nightly-sales-review?route=PKX-CJU&seats=20&departure={DEPARTURE}&departureEnd={DEPARTURE_END}&cost=600&reviewDate={TODAY.isoformat()}",
        f"/api/price-adjustment-backtest?route=PKX-CJU&seats=20&departure={DEPARTURE}&departureEnd={DEPARTURE_END}&cost=600&decisionDate={TODAY.isoformat()}&costFloor=650",
        "/api/actual-result-model?route=PKX-CJU&actualSourceMode=manualInput&actualVolumeWindow=D-8~14&actualHighWindow=D-0~1&actualSales=8&actualRevenue=8800&actualProfit=1600",
        f"/api/model-calibration?route=PKX-CJU&actualSourceMode=manualInput&actualVolumeWindow=D-8~14&actualHighWindow=D-0~1&actualSales=8&actualRevenue=8800&actualProfit=1600&departure={DEPARTURE}&departureEnd={DEPARTURE_END}",
        "/api/ai-analysis-package?route=PKX-CJU&limit=3",
    ]
    for path in analytics:
        code, data = get(path)
        check(f"分析功能 {path.split('?')[0]}", code == 200 and isinstance(data, dict), {"code": code, "error": data.get("error") if isinstance(data, dict) else data})

    for collection in COLLECTIONS:
        code, data = get("/api/operation-center?" + urllib.parse.urlencode({"collection": collection}))
        check(f"运营读取 {collection}", code == 200 and data.get("collection") == collection and isinstance(data.get("fields"), list), {"code": code, "data": data})

    created = {}
    for collection in [item for item in COLLECTIONS if item not in VIRTUAL]:
        _, schema = get("/api/operation-center?" + urllib.parse.urlencode({"collection": collection}))
        record = {field: "SELFTEST" for field in schema["fields"]}
        for field in ("状态", "账号状态", "任务状态", "查询状态", "库存状态", "订单状态"):
            if field in record:
                record[field] = "启用"
        if collection == "cutInventory":
            record.update({"航线": "PKX-CJU", "航司": "9C", "航班号": "ST9001", "出发日期": DEPARTURE, "舱位": "Y", "锁座数": "5", "已售数": "0", "剩余数": "5", "成本价": "600", "计划售价": "980", "库存状态": "上架"})
        if collection == "orders":
            record.update({"订单号": "SELFTEST-ORDER-CRUD", "航线": "PKX-CJU", "订单状态": "待处理"})
        code, data = post("/api/operation-center", {"collection": collection, "record": record})
        row = data.get("record", {}) if isinstance(data, dict) else {}
        check(f"运营新增 {collection}", code == 200 and row.get("id"), {"code": code, "data": data})
        created[collection] = row["id"]
        code, data = post("/api/operation-center", {"collection": collection, "action": "delete", "id": row["id"]})
        check(f"运营删除 {collection}", code == 200 and all(x.get("id") != row["id"] for x in data.get("rows", [])), {"code": code, "data": data})

    code, account = post("/api/accounts", {"employeeId": "SELFTEST01", "name": "全链路测试", "password": "Selftest@2026", "role": "operation", "status": "active"})
    check("员工账号新增", code == 200 and account.get("account", {}).get("employeeId") == "SELFTEST01", account)
    code, employee_login = post("/api/auth/employee-login", {"employeeId": "SELFTEST01", "password": "Selftest@2026"})
    check("员工账号登录", code == 200 and employee_login.get("ok"), employee_login)
    code, login = post("/api/auth/admin-login", {"password": PASSWORD})
    check("恢复管理员会话", code == 200 and login.get("ok"), login)
    code, status = post("/api/accounts/status", {"employeeId": "SELFTEST01", "status": "disabled"})
    check("员工账号停用", code == 200 and status.get("account", {}).get("status") == "disabled", status)
    code, deleted = post("/api/accounts/delete", {"employeeId": "SELFTEST01"})
    check("员工账号删除", code == 200, deleted)

    code, auto = post("/api/automation-jobs", {"任务名称": "SELFTEST", "平台": "Mock OTA", "航线": "PKX-CJU", "自动运行": "关闭"})
    check("自动化预留配置", code == 200 and auto.get("enabled") is False, auto)
    code, run_now = post("/api/automation-run-now", {"id": auto.get("record", {}).get("id")})
    check("自动化禁用边界", code == 202 and run_now.get("enabled") is False, {"code": code, "data": run_now})

    code, channel = post("/api/operation-center", {"collection": "channels", "record": {"渠道名称": "SELFTEST-CHANNEL", "渠道类型": "OTA", "状态": "启用"}})
    channel_id = channel.get("record", {}).get("id")
    code, store = post("/api/operation-center", {"collection": "stores", "record": {"店铺名称": "SELFTEST-STORE", "平台": "SELFTEST-CHANNEL", "渠道": "SELFTEST-CHANNEL", "状态": "启用"}})
    store_id = store.get("record", {}).get("id")
    code, cascade = post("/api/operation-center", {"collection": "channels", "action": "set-status", "id": channel_id, "field": "状态", "enabled": False})
    check("渠道停用联动", code == 200 and cascade.get("cascaded", 0) >= 1, cascade)
    code, bulk = post("/api/operation-center-bulk", {"collection": "channels", "action": "copy", "ids": [channel_id]})
    check("批量复制", code == 200 and bulk.get("changed", 0) >= 1, bulk)
    code, mock_channel = post("/api/operation-center", {"collection": "channels", "record": {"渠道名称": "Mock OTA", "渠道类型": "OTA", "状态": "启用"}})
    check("Mock OTA 渠道启用", code == 200 and mock_channel.get("record", {}).get("id"), mock_channel)

    code, policy = post("/api/operation-center", {"collection": "policyRules", "record": {"规则名称": "SELFTEST-RULE", "航司": "9C", "航线": "PKX-CJU", "规则类型": "测试", "状态": "启用"}})
    code, inventory = post("/api/operation-center", {"collection": "cutInventory", "record": {"航线": "PKX-CJU", "航司": "9C", "航班号": "ST9001", "出发日期": DEPARTURE, "舱位": "Y", "锁座数": "5", "已售数": "0", "剩余数": "5", "成本价": "600", "计划售价": "980", "库存状态": "上架", "采购渠道": "SELFTEST"}})
    inventory_row = inventory.get("record", {})
    check("政策提示关联", "SELFTEST-RULE" in inventory_row.get("政策提示", ""), inventory_row)
    inventory_id = inventory_row["id"]

    code, publish = post("/api/mock-ota/publish", {"channels": ["mock_ota"]})
    check("主系统发布到 Mock OTA", code == 200 and publish.get("published", 0) >= 1, {"code": code, "data": publish})
    code, policies = request("GET", MOCK + "/api/policies")
    mock_policy = next((x for x in policies.get("rows", []) if x.get("source_inventory_id") == inventory_id), None)
    check("Mock OTA 接收政策", code == 200 and mock_policy, policies)

    code, order = request("POST", MOCK + "/api/orders/create", {"policy_id": mock_policy["policy_id"], "passenger": "SELFTEST", "quantity": 1})
    order_row = order.get("order", {}) if isinstance(order, dict) else {}
    check("Mock OTA 下单回流", code == 200 and order.get("callback", {}).get("ok"), {"code": code, "data": order})
    _, after_create = get("/api/operation-center?collection=cutInventory")
    current = next(x for x in after_create["rows"] if x["id"] == inventory_id)
    check("下单扣减库存", current.get("已售数") == "1" and current.get("剩余数") == "4", current)
    code, cancelled = request("POST", MOCK + "/api/orders/cancel", {"order_id": order_row["order_id"]})
    check("Mock OTA 取消回流", code == 200 and cancelled.get("callback", {}).get("ok"), {"code": code, "data": cancelled})
    _, after_cancel = get("/api/operation-center?collection=cutInventory")
    current = next(x for x in after_cancel["rows"] if x["id"] == inventory_id)
    check("取消释放库存", current.get("已售数") == "0" and current.get("剩余数") == "5", current)

    for path in [
        "/api/operation-center-sync-inventory", "/api/operation-center-sync-platforms",
        "/api/operation-center-sync-ticket-tasks", "/api/operation-center-sync-ticket-checks",
        "/api/operation-center-sync-after-sales", "/api/operation-center-sync-payment-returns",
        "/api/operation-center-statistics",
    ]:
        code, data = post(path)
        check(f"关联动作 {path}", code == 200 and isinstance(data, dict), {"code": code, "data": data})

    code, exported = post("/api/table-export", {"title": "SELFTEST", "fields": ["id", "name"], "rows": [{"id": 1, "name": "ok"}]})
    check("通用表格导出", code == 200 and isinstance(exported, (bytes, bytearray)) and bytes(exported).startswith(b"PK"), {"code": code, "type": type(exported).__name__})
    code, exported = get("/api/operation-center-export?collection=cutInventory")
    check("运营表格导出", code == 200 and isinstance(exported, (bytes, bytearray)) and bytes(exported).startswith(b"PK"), {"code": code, "type": type(exported).__name__})

    failed = [item for item in checks if not item["passed"]]
    print(json.dumps({"ok": not failed, "passed": len(checks) - len(failed), "failed": failed, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "passed": len([x for x in checks if x["passed"]]), "error": str(exc), "checks": checks}, ensure_ascii=False, indent=2))
        raise
