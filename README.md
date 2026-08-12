# 航空销售智能执行平台

一个由航空从业经验出发，与 AI 协作开发的本地航空销售系统初型。

![航空销售智能执行平台运营驾驶舱](./docs/dashboard.jpg)

当前公开版本聚焦航线策略、销售节奏、库存预警、运营台账、权限管理和 Mock OTA 模拟闭环。它不是生产 OTA，也不会自动连接真实渠道、支付或出票系统。

仓库自带一组明确标注的合成演示数据，用于首次运行和自动化验收，不包含任何真实业务记录。

## 当前能力

- 航线经营数据读取与策略分析
- 主卖、高价、放量窗口识别
- 锁座、成本、售价和库存预警
- 策略执行任务的人工确认门禁
- 订单、出票、售后、支付等运营台账
- 管理员、员工和访客权限入口
- Mock OTA 政策、订单与取消回调模拟

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
AIR_SKILL_ADMIN_PASSWORD='请设置自己的强密码' .venv/bin/python app.py
```

打开 `http://127.0.0.1:8000/`。

可通过 `AIRLINE_DEFAULT_FILE` 指定默认 Excel 文件，通过 `AIRLINE_LOCAL_PORT` 修改本地端口。

### 启动 Mock OTA 沙箱

另开一个终端，主系统和沙箱使用同一个自定义 Token：

```bash
MOCK_OTA_TOKEN='请设置随机测试Token' MOCK_OTA_PORT=8010 python3 mock_ota/app.py
```

若要运行仓库中的隔离全链路测试，可分别在 `18000` 和 `18010` 启动主系统与沙箱，再执行：

```bash
AIR_SKILL_ADMIN_PASSWORD='测试密码' \
MOCK_OTA_TOKEN='与两个测试服务相同的Token' \
python3 tests/airline_full_selftest.py
```

## 数据边界

- 仓库不包含真实订单、库存、账号、审计日志和业务 Excel。
- `outputs/sales_strategy_all/` 中仅包含人工编写的合成演示样例。
- 运行数据只在本机生成，并已由 `.gitignore` 排除。
- Mock OTA 只用于接口和流程模拟，不代表真实平台能力。
- 对外部署前必须重新设计认证、密钥管理、网络边界和数据保护。

## 验证状态

公开副本发布前使用隔离数据完成后端回归和页面操作核查。具体测试结果以仓库最新提交和发布说明为准。

## 许可

当前仓库用于公开展示和学习参考，暂未附加开源许可证。
