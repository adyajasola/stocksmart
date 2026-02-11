from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import pandas as pd
from pathlib import Path
import uuid

from sqlalchemy.dialects.postgresql import insert
from app.db.session import SessionLocal
from app.db.models import Product, Inventory, Sale

router = APIRouter()

REQUIRED_PRODUCTS = {"sku", "name", "category", "cost", "price", "supplier"}
REQUIRED_INVENTORY = {"sku", "on_hand", "reorder_point", "lead_time_days"}
REQUIRED_SALES = {"sku", "ts", "units", "unit_price"}

ERROR_DIR = Path("tmp/error_reports")
ERROR_DIR.mkdir(parents=True, exist_ok=True)

def read_csv(upload: UploadFile) -> pd.DataFrame:
    if not upload.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail=f"{upload.filename} must be a CSV")
    try:
        return pd.read_csv(upload.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{upload.filename}: could not read CSV: {e}")

def missing_cols(df: pd.DataFrame, required: set[str]) -> list[str]:
    return sorted(list(required - set(df.columns)))

def add_error(
    errors: list,
    *,
    file: str,
    row: int | None,
    field: str,
    code: str,
    message: str,
    value: str = "",
    suggestion: str = "",
):
    errors.append({
        "file": file,
        "row": row,
        "field": field,
        "code": code,
        "message": message,
        "value": value,
        "suggestion": suggestion,
    })

@router.get("/error-report/{report_id}")
def download_error_report(report_id: str):
    path = ERROR_DIR / f"{report_id}.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Error report not found")
    return FileResponse(path, media_type="text/csv", filename="import_error_report.csv")

@router.post("/validate")
async def validate_all(
    products: UploadFile = File(...),
    inventory: UploadFile = File(...),
    sales: UploadFile = File(...),
):
    df_p = read_csv(products)
    df_i = read_csv(inventory)
    df_s = read_csv(sales)

    errors: list[dict] = []

    # 1) Required columns
    mp = missing_cols(df_p, REQUIRED_PRODUCTS)
    mi = missing_cols(df_i, REQUIRED_INVENTORY)
    ms = missing_cols(df_s, REQUIRED_SALES)

    if mp:
        add_error(errors, file=products.filename, row=None, field="*", code="MISSING_COLUMNS",
                  message="Missing required columns", value=",".join(mp), suggestion="Add these columns to header.")
    if mi:
        add_error(errors, file=inventory.filename, row=None, field="*", code="MISSING_COLUMNS",
                  message="Missing required columns", value=",".join(mi), suggestion="Add these columns to header.")
    if ms:
        add_error(errors, file=sales.filename, row=None, field="*", code="MISSING_COLUMNS",
                  message="Missing required columns", value=",".join(ms), suggestion="Add these columns to header.")

    # Stop early if missing columns
    if errors:
        report_id = uuid.uuid4().hex
        (ERROR_DIR / f"{report_id}.csv").write_text(pd.DataFrame(errors).to_csv(index=False))
        return {
            "ok": False,
            "summary": {"products_rows": int(len(df_p)), "inventory_rows": int(len(df_i)), "sales_rows": int(len(df_s))},
            "errors_count": len(errors),
            "error_report_id": report_id,
            "error_report_url": f"/import/error-report/{report_id}",
            "errors_preview": errors[:25],
        }

    # 2) Row-level checks (basic)
    for idx, row in df_p.iterrows():
        csv_row = int(idx) + 2
        sku = str(row.get("sku", "")).strip()
        if not sku:
            add_error(errors, file=products.filename, row=csv_row, field="sku", code="REQUIRED",
                      message="sku is required", suggestion="Provide a non-empty sku.")

        try:
            cost = float(row["cost"])
        except Exception:
            add_error(errors, file=products.filename, row=csv_row, field="cost", code="BAD_NUMBER",
                      message="cost must be a number", value=str(row.get("cost", "")))
            cost = None

        try:
            price = float(row["price"])
        except Exception:
            add_error(errors, file=products.filename, row=csv_row, field="price", code="BAD_NUMBER",
                      message="price must be a number", value=str(row.get("price", "")))
            price = None

        if cost is not None and price is not None and price < cost:
            add_error(errors, file=products.filename, row=csv_row, field="price", code="PRICE_LT_COST",
                      message="price must be >= cost", value=f"{price} < {cost}",
                      suggestion="Raise price or correct cost.")

    for idx, row in df_i.iterrows():
        csv_row = int(idx) + 2
        try:
            on_hand = int(row["on_hand"])
            if on_hand < 0:
                raise ValueError()
        except Exception:
            add_error(errors, file=inventory.filename, row=csv_row, field="on_hand", code="BAD_INT",
                      message="on_hand must be an integer >= 0", value=str(row.get("on_hand", "")))

        try:
            rp = int(row["reorder_point"])
            if rp < 0:
                raise ValueError()
        except Exception:
            add_error(errors, file=inventory.filename, row=csv_row, field="reorder_point", code="BAD_INT",
                      message="reorder_point must be an integer >= 0", value=str(row.get("reorder_point", "")))

        try:
            lt = int(row["lead_time_days"])
            if lt < 1 or lt > 90:
                raise ValueError()
        except Exception:
            add_error(errors, file=inventory.filename, row=csv_row, field="lead_time_days", code="OUT_OF_RANGE",
                      message="lead_time_days must be between 1 and 90",
                      value=str(row.get("lead_time_days", "")), suggestion="Use a value 1–90.")

    for idx, row in df_s.iterrows():
        csv_row = int(idx) + 2
        ts = str(row.get("ts", "")).strip()
        parsed = pd.to_datetime(ts, errors="coerce", format="%Y-%m-%d")
        if pd.isna(parsed):
            add_error(errors, file=sales.filename, row=csv_row, field="ts", code="BAD_DATE",
                      message="ts must be YYYY-MM-DD", value=ts, suggestion="Use ISO like 2026-01-31.")

        try:
            units = int(row["units"])
            if units < 0:
                raise ValueError()
        except Exception:
            add_error(errors, file=sales.filename, row=csv_row, field="units", code="BAD_INT",
                      message="units must be an integer >= 0", value=str(row.get("units", "")))

        try:
            float(row["unit_price"])
        except Exception:
            add_error(errors, file=sales.filename, row=csv_row, field="unit_price", code="BAD_NUMBER",
                      message="unit_price must be a number", value=str(row.get("unit_price", "")))

    # 3) Cross-file sku checks
    product_skus = set(df_p["sku"].astype(str).str.strip())
    for idx, row in df_i.iterrows():
        csv_row = int(idx) + 2
        sku = str(row.get("sku", "")).strip()
        if sku and sku not in product_skus:
            add_error(errors, file=inventory.filename, row=csv_row, field="sku", code="UNKNOWN_SKU",
                      message="sku not found in products.csv", value=sku, suggestion="Fix sku to match products.csv.")

    for idx, row in df_s.iterrows():
        csv_row = int(idx) + 2
        sku = str(row.get("sku", "")).strip()
        if sku and sku not in product_skus:
            add_error(errors, file=sales.filename, row=csv_row, field="sku", code="UNKNOWN_SKU",
                      message="sku not found in products.csv", value=sku, suggestion="Fix sku to match products.csv.")

    if errors:
        report_id = uuid.uuid4().hex
        pd.DataFrame(errors).to_csv(ERROR_DIR / f"{report_id}.csv", index=False)
        return {
            "ok": False,
            "summary": {"products_rows": int(len(df_p)), "inventory_rows": int(len(df_i)), "sales_rows": int(len(df_s))},
            "errors_count": len(errors),
            "error_report_id": report_id,
            "error_report_url": f"/import/error-report/{report_id}",
            "errors_preview": errors[:25],
        }

    return {
        "ok": True,
        "summary": {"products_rows": int(len(df_p)), "inventory_rows": int(len(df_i)), "sales_rows": int(len(df_s))},
        "errors_count": 0,
        "errors_preview": [],
    }

@router.post("/commit")
async def commit_import(
    products: UploadFile = File(...),
    inventory: UploadFile = File(...),
    sales: UploadFile = File(...),
):
    df_p = read_csv(products)
    df_i = read_csv(inventory)
    df_s = read_csv(sales)

    mp = missing_cols(df_p, REQUIRED_PRODUCTS)
    mi = missing_cols(df_i, REQUIRED_INVENTORY)
    ms = missing_cols(df_s, REQUIRED_SALES)
    if mp or mi or ms:
        raise HTTPException(status_code=400, detail="Missing required columns. Run /import/validate first.")

    db = SessionLocal()
    try:
        prod_rows = df_p.to_dict(orient="records")
        stmt = insert(Product).values(prod_rows).on_conflict_do_update(
            index_elements=[Product.sku],
            set_={
                "name": insert(Product).excluded.name,
                "category": insert(Product).excluded.category,
                "cost": insert(Product).excluded.cost,
                "price": insert(Product).excluded.price,
                "supplier": insert(Product).excluded.supplier,
            },
        )
        db.execute(stmt)

        inv_rows = df_i.to_dict(orient="records")
        stmt2 = insert(Inventory).values(inv_rows).on_conflict_do_update(
            index_elements=[Inventory.sku],
            set_={
                "on_hand": insert(Inventory).excluded.on_hand,
                "reorder_point": insert(Inventory).excluded.reorder_point,
                "lead_time_days": insert(Inventory).excluded.lead_time_days,
            },
        )
        db.execute(stmt2)

        sales_rows = df_s.to_dict(orient="records")
        stmt3 = insert(Sale).values(sales_rows).on_conflict_do_nothing(
            index_elements=[Sale.sku, Sale.ts]
        )
        db.execute(stmt3)

        db.commit()
        return {
            "ok": True,
            "saved": {
                "products_upserted": len(prod_rows),
                "inventory_upserted": len(inv_rows),
                "sales_attempted": len(sales_rows),
            },
            "note": "Sales duplicates (same sku+ts) are skipped.",
        }
    finally:
        db.close()
