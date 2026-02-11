# StockSmart (v0)

Lean inventory + revenue optimization SaaS (MVP).

## What works right now (Module 1: Input)
- Upload `products.csv`, `inventory.csv`, `sales.csv`
- Validate data + generate downloadable error report
- Commit valid rows to PostgreSQL (upsert products/inventory, dedupe sales)

## Tech Stack
- FastAPI + Uvicorn
- PostgreSQL
- SQLAlchemy
- Pandas

## Setup (Ubuntu/WSL)
### 1) Create and activate venv
```bash
python3 -m venv venv
source venv/bin/activate


