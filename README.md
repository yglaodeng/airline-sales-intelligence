# 航空销售智能执行平台

**Airline Sales Intelligence Platform**

一个由真实航空销售经验驱动、与 AI 协作开发的本地决策与执行原型：把航线经营数据转化为销售节奏、价格窗口、库存预警和需要人工确认的执行任务。

**English:** A local-first airline sales and revenue-management prototype for sales planning, inventory alerts, approval-gated execution, and Mock OTA validation.

[在线查看项目介绍](https://yglaodeng.github.io/airline-sales-intelligence/) · [查看源码](https://github.com/yglaodeng/airline-sales-intelligence)

![航空销售智能执行平台运营驾驶舱](./docs/dashboard.jpg)

## 30 秒了解项目

- **面向谁：** 航空销售、航线运营、库存与收益管理从业者，以及关注 AI 如何承接真实业务经验的人
- **解决什么：** 从销售数据中识别主卖、高价和放量窗口，跟踪锁座、成本、售价与库存风险
- **如何执行：** 策略先进入人工确认，再通过运营台账和 Mock OTA 沙箱验证流程
- **当前状态：** 可在本地运行的系统初型，公开版使用合成演示数据完成隔离验证

当前公开版本聚焦航线策略、销售节奏、库存预警、运营台账、权限管理和 Mock OTA 模拟闭环。它不是生产 OTA，也不会自动连接真实渠道、支付或出票系统。

仓库自带一组明确标注的合成演示数据，用于首次运行和自动化验收，不包含任何真实业务记录。

> 如果你也在关注航空销售数字化、收益管理或 AI 与真实业务的结合，欢迎给项目一个 Star；问题和建议可以通过 [GitHub Issue](https://github.com/yglaodeng/airline-sales-intelligence/issues) 交流。

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

公开版本 `v0.1.0` 发布前使用隔离数据完成完整自测，142/142 项通过；项目介绍页的 Lighthouse 四项评分均为 100。详见 [发布说明](https://github.com/yglaodeng/airline-sales-intelligence/releases/tag/v0.1.0)。

## 许可

当前仓库用于公开展示和学习参考，暂未附加开源许可证。
