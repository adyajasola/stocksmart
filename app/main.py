from fastapi import FastAPI
from app.routers.import_router import router as import_router

app = FastAPI(title="StockSmart API v0")

@app.get("/")
def root():
    return {"ok": True, "service": "stocksmart", "module": "input"}

app.include_router(import_router, prefix="/import", tags=["import"])

