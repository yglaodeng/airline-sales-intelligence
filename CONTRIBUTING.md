# Contributing

感谢你关注 Airline Sales Intelligence Platform。

## 开始之前

- 请先搜索现有 Issues，避免重复提交。
- 功能建议应说明航空销售或收益管理场景、预期结果和数据边界。
- Bug 报告应包含复现步骤、实际结果、预期结果和运行环境。
- 不要提交真实订单、库存、客户资料、账号、Token、密钥或业务 Excel。

## Pull Request

1. 每个 PR 只解决一个明确问题。
2. 从 `main` 创建分支，并保持改动最小。
3. 运行 `python3 tests/airline_full_selftest.py`；若使用自定义服务端口，请在 PR 中说明。
4. 在 PR 中写明测试对象、步骤、通过标准和实际结果。
5. Mock OTA 只能作为隔离沙箱，不得描述为真实渠道能力。

English issues and pull requests are welcome. Please keep production credentials and real airline data out of the repository.
