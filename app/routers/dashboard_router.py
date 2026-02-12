from fastapi import APIRouter, Query
from sqlalchemy import select, func, case, cast, Float
from sqlalchemy.sql import text
from app.db.session import SessionLocal
from app.db.models import Inventory, Sale, Product

router = APIRouter()

def sale_date_expr():
    # sales.ts is stored as string 'YYYY-MM-DD'
    return func.to_date(Sale.ts, text("'YYYY-MM-DD'"))

@router.get("/kpis")
def get_kpis(days: int = Query(default=30, ge=1, le=365)):
    db = SessionLocal()
    try:
        cutoff = func.current_date() - days

        # Revenue + units in window
        sales_stmt = select(
            func.coalesce(func.sum(Sale.units), 0).label("units"),
            func.coalesce(func.sum(Sale.units * Sale.unit_price), 0.0).label("revenue"),
        ).where(sale_date_expr() >= cutoff)
        s = db.execute(sales_stmt).one()

        # Gross margin (approx):
        # margin dollars = sum( units * (unit_price - cost) )
        margin_stmt = select(
            func.coalesce(func.sum(Sale.units * (Sale.unit_price - Product.cost)), 0.0).label("gross_profit"),
            func.coalesce(func.sum(Sale.units * Sale.unit_price), 0.0).label("revenue"),
        ).join(Product, Product.sku == Sale.sku).where(sale_date_expr() >= cutoff)
        m = db.execute(margin_stmt).one()
        gross_margin_pct = 0.0
        if float(m.revenue) > 0:
            gross_margin_pct = float(m.gross_profit) / float(m.revenue) * 100.0

        # Low stock count
        low_stock_count = db.execute(
            select(func.count()).select_from(Inventory).where(Inventory.on_hand <= Inventory.reorder_point)
        ).scalar_one()

        # Stockout risk (simple):
        # avg_daily_sales = units_last_days / days
        # stockout_days = on_hand / avg_daily_sales
        # risk if stockout_days <= lead_time_days
        units_by_sku = (
            select(
                Sale.sku.label("sku"),
                (func.coalesce(func.sum(Sale.units), 0) / cast(days, Float)).label("avg_daily_units"),
            )
            .where(sale_date_expr() >= cutoff)
            .group_by(Sale.sku)
            .subquery()
        )

        # Avoid division by zero: only consider avg_daily_units > 0
        stockout_risk_stmt = (
            select(func.count())
            .select_from(Inventory)
            .join(units_by_sku, units_by_sku.c.sku == Inventory.sku)
            .where(units_by_sku.c.avg_daily_units > 0)
            .where((Inventory.on_hand / units_by_sku.c.avg_daily_units) <= Inventory.lead_time_days)
        )
        stockout_risk_count = db.execute(stockout_risk_stmt).scalar_one()

        return {
            "window_days": days,
            "revenue": float(s.revenue),
            "units": int(s.units),
            "gross_margin_pct": round(gross_margin_pct, 2),
            "low_stock_skus": int(low_stock_count),
            "stockout_risk_skus": int(stockout_risk_count),
        }
    finally:
        db.close()


@router.get("/alerts")
def get_alerts(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=25, ge=1, le=200),
):
    db = SessionLocal()
    try:
        cutoff = func.current_date() - days

        units_by_sku = (
            select(
                Sale.sku.label("sku"),
                func.coalesce(func.sum(Sale.units), 0).label("units_window"),
                (func.coalesce(func.sum(Sale.units), 0) / cast(days, Float)).label("avg_daily_units"),
            )
            .where(sale_date_expr() >= cutoff)
            .group_by(Sale.sku)
            .subquery()
        )

        # Stockout in X days = on_hand / avg_daily_units
        # Only if avg_daily_units > 0
        stmt = (
            select(
                Product.sku,
                Product.name,
                Inventory.on_hand,
                Inventory.reorder_point,
                Inventory.lead_time_days,
                units_by_sku.c.avg_daily_units,
                (Inventory.on_hand / units_by_sku.c.avg_daily_units).label("stockout_days"),
            )
            .join(Inventory, Inventory.sku == Product.sku)
            .join(units_by_sku, units_by_sku.c.sku == Product.sku)
            .where(units_by_sku.c.avg_daily_units > 0)
            .order_by((Inventory.on_hand / units_by_sku.c.avg_daily_units).asc())
            .limit(limit)
        )

        rows = db.execute(stmt).all()

        alerts = []
        for r in rows:
            stockout_days = float(r.stockout_days)
            issue = None
            if stockout_days <= float(r.lead_time_days):
                issue = f"Stockout risk in ~{stockout_days:.1f} days (lead {r.lead_time_days}d)"
            elif int(r.on_hand) <= int(r.reorder_point):
                issue = "Low stock (below reorder point)"

            if issue:
                alerts.append({
                    "sku": r.sku,
                    "name": r.name,
                    "issue": issue,
                    "on_hand": int(r.on_hand),
                    "reorder_point": int(r.reorder_point),
                    "lead_time_days": int(r.lead_time_days),
                    "avg_daily_units": float(r.avg_daily_units),
                    "stockout_days": round(stockout_days, 1),
                    "action": "Create PO",
                })

        return {"window_days": days, "alerts": alerts}
    finally:
        db.close()
