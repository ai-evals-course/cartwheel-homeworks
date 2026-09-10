"""SQLite schema access layer. Instructor-provided and complete.

Typed, read-mostly access to the seeded world. Tools go through this module
instead of writing SQL inline, so permission checks and data access stay
separable and testable. The schema itself is created by seed/generate.py.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from agent.config import db_path


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the world database. Caller must close it; prefer connection()."""
    target = path or db_path()
    if not target.exists():
        raise FileNotFoundError(
            f"{target} does not exist. Run: uv run python -m seed.generate"
        )
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def connection(path: Path | None = None) -> closing[sqlite3.Connection]:
    """Open a connection that closes on block exit, without committing on exit."""
    return closing(connect(path))


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass(frozen=True)
class Store:
    id: int
    name: str
    slug: str
    category: str
    return_window_days_override: int | None
    restocking_fee_opt_in: bool


@dataclass(frozen=True)
class User:
    id: int
    name: str
    role: str
    store_id: int | None


@dataclass(frozen=True)
class Product:
    id: int
    store_id: int
    title: str
    description: str
    category: str
    price_cents: int

    @property
    def price_usd(self) -> float:
        return self.price_cents / 100


@dataclass(frozen=True)
class Order:
    id: int
    user_id: int
    store_id: int
    product_id: int
    quantity: int
    total_cents: int
    status: str
    ordered_at: date
    shipped_at: date | None
    delivered_at: date | None
    refund_eligible: bool

    @property
    def total_usd(self) -> float:
        return self.total_cents / 100

    def to_public_dict(self) -> dict[str, Any]:
        """The fields a tool may return to the model for an in-scope order."""
        return {
            "order_id": self.id,
            "store_id": self.store_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "total_usd": self.total_usd,
            "status": self.status,
            "ordered_at": self.ordered_at.isoformat(),
            "shipped_at": self.shipped_at.isoformat() if self.shipped_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "refund_eligible": self.refund_eligible,
        }


def _order_from_row(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        user_id=row["user_id"],
        store_id=row["store_id"],
        product_id=row["product_id"],
        quantity=row["quantity"],
        total_cents=row["total_cents"],
        status=row["status"],
        ordered_at=date.fromisoformat(row["ordered_at"]),
        shipped_at=_parse_date(row["shipped_at"]),
        delivered_at=_parse_date(row["delivered_at"]),
        refund_eligible=bool(row["refund_eligible"]),
    )


def get_order(conn: sqlite3.Connection, order_id: int) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return _order_from_row(row) if row else None


def get_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return User(id=row["id"], name=row["name"], role=row["role"], store_id=row["store_id"])


def get_store(conn: sqlite3.Connection, store_id: int) -> Store | None:
    row = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    return _store_from_row(row) if row else None


def get_store_by_name(conn: sqlite3.Connection, name: str) -> Store | None:
    """Case-insensitive exact match on store name, then slug."""
    row = conn.execute(
        "SELECT * FROM stores WHERE lower(name) = lower(?) OR slug = lower(?)",
        (name, name),
    ).fetchone()
    return _store_from_row(row) if row else None


def _store_from_row(row: sqlite3.Row) -> Store:
    return Store(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        category=row["category"],
        return_window_days_override=row["return_window_days_override"],
        restocking_fee_opt_in=bool(row["restocking_fee_opt_in"]),
    )


def list_orders_for_user(
    conn: sqlite3.Connection, user_id: int, limit: int = 20
) -> list[Order]:
    rows = conn.execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY ordered_at DESC, id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_order_from_row(row) for row in rows]


def list_orders_for_store(
    conn: sqlite3.Connection, store_id: int, limit: int = 20
) -> list[Order]:
    rows = conn.execute(
        "SELECT * FROM orders WHERE store_id = ? ORDER BY ordered_at DESC, id DESC LIMIT ?",
        (store_id, limit),
    ).fetchall()
    return [_order_from_row(row) for row in rows]


def list_order_search_candidates(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    store_id: int | None = None,
    all_orders: bool = False,
) -> list[Order]:
    """Return the complete search scope, newest first (order ID breaks ties).

    Select exactly one scope. The tool must derive user/store IDs from its
    authenticated context and allow all_orders=True only for support staff.
    There is deliberately no limit: product matching must precede truncation.
    Use list_products to map product IDs to titles for student-owned matching.
    """
    if sum((user_id is not None, store_id is not None, all_orders)) != 1:
        raise ValueError("select exactly one order search scope")
    if user_id is not None:
        where, params = " WHERE user_id = ?", (user_id,)
    elif store_id is not None:
        where, params = " WHERE store_id = ?", (store_id,)
    else:
        where, params = "", ()
    rows = conn.execute(
        "SELECT * FROM orders" + where + " ORDER BY ordered_at DESC, id DESC", params
    ).fetchall()
    return [_order_from_row(row) for row in rows]


def list_products(
    conn: sqlite3.Connection, store_id: int | None = None
) -> list[Product]:
    if store_id is None:
        rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE store_id = ? ORDER BY id", (store_id,)
        ).fetchall()
    return [
        Product(
            id=row["id"],
            store_id=row["store_id"],
            title=row["title"],
            description=row["description"],
            category=row["category"],
            price_cents=row["price_cents"],
        )
        for row in rows
    ]


def set_order_status(conn: sqlite3.Connection, order_id: int, status: str) -> None:
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()


def insert_refund(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    amount_cents: int,
    reason: str,
    status: str,
    created_at: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO refunds (order_id, amount_cents, reason, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (order_id, amount_cents, reason, status, created_at),
    )
    conn.commit()
    return int(cursor.lastrowid)


def insert_escalation(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    store_id: int | None,
    order_id: int | None,
    summary: str,
    context: str,
    created_at: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO escalations (user_id, store_id, order_id, summary, context, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, store_id, order_id, summary, context, created_at),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def world_asof(conn: sqlite3.Connection) -> date:
    """The world's fixed 'today'. All date arithmetic uses this, never now()."""
    value = get_meta(conn, "world_asof")
    if value is None:
        raise RuntimeError("meta.world_asof missing; re-run seed.generate")
    return date.fromisoformat(value)
