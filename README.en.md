# Airline Sales Intelligence Platform

A local-first airline revenue-management and sales-intelligence prototype built from real airline sales experience. It turns route data into sales timing, pricing windows, seat-inventory alerts, and approval-gated execution tasks.

[Project page](https://yglaodeng.github.io/airline-sales-intelligence/) · [中文说明](./README.md) · [Roadmap](./ROADMAP.md) · [Report an issue](https://github.com/yglaodeng/airline-sales-intelligence/issues)

![Airline sales intelligence operations dashboard](./docs/dashboard.jpg)

## Why this project exists

Airline sales teams need more than a dashboard. They need to connect route performance, blocked-seat cost, selling price, remaining inventory, and timing into decisions that can be reviewed before execution. This project demonstrates that workflow without connecting to a production OTA, payment system, or ticketing channel.

## What it does

- Reads route-operation data and produces sales-strategy analysis.
- Identifies primary-sale, premium-price, and volume windows.
- Tracks blocked seats, cost, selling price, and inventory risk.
- Requires human approval before strategy execution.
- Records orders, ticketing, after-sales, and payment operations.
- Provides administrator, staff, and visitor access modes.
- Includes a Mock OTA sandbox for policy, order, and cancellation callbacks.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
AIR_SKILL_ADMIN_PASSWORD='set-a-strong-password' .venv/bin/python app.py
```

Open `http://127.0.0.1:8000/`.

To start the Mock OTA sandbox in another terminal:

```bash
MOCK_OTA_TOKEN='set-a-random-test-token' MOCK_OTA_PORT=8010 python3 mock_ota/app.py
```

## Verification

The public `v0.1.0` release passed 142 of 142 isolated checks using synthetic fixtures. The project page received 100 in all four Lighthouse categories at release time. See the [release notes](https://github.com/yglaodeng/airline-sales-intelligence/releases/tag/v0.1.0).

## Data and security boundaries

- The repository contains no real orders, inventory, credentials, audit logs, or business workbooks.
- Files under `outputs/sales_strategy_all/` are explicitly synthetic demo fixtures.
- Runtime data is generated locally and excluded by `.gitignore`.
- Mock OTA validates an interface contract only; it does not represent a live external platform.
- Production deployment requires a separate review of authentication, secrets, network boundaries, and data protection.

## Contributing

Read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening an issue or pull request. Planned work and known boundaries are listed in [ROADMAP.md](./ROADMAP.md).

## License

[MIT](./LICENSE)
