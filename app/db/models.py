from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Date, ForeignKey, UniqueConstraint

class Base(DeclarativeBase):
    pass

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    cost: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    supplier: Mapped[str] = mapped_column(String(120))

class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    on_hand: Mapped[int] = mapped_column(Integer)
    reorder_point: Mapped[int] = mapped_column(Integer)
    lead_time_days: Mapped[int] = mapped_column(Integer)

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD for MVP
    units: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("sku", "ts", name="uq_sales_sku_ts"),
    )
