"""Query Agent: natural language -> verified read-only SQL -> answer."""
from __future__ import annotations

import re

from .agents import Env

ALLOWED_TABLES = {"items", "stock", "batches", "sales", "suppliers", "prices", "pos", "po_lines"}
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum|reindex|truncate)\b", re.I)
WRITE_INTENT = re.compile(r"\b(delete|remove|drop|update|change|set|insert|add|modify|erase|wipe|truncate)\b", re.I)
SCHEMA_HINT = ("Tables: items(sku,name,category,unit_cost,shelf_life_days,reorder_point), stock(sku,on_hand), "
               "batches(sku,qty,expiry_day), sales(sku,day,qty), suppliers(id,name,reliability,note), "
               "prices(supplier_id,sku,unit_price,moq,lead_time_days,in_stock), pos(po_id,status,supplier_id,total), "
               "po_lines(po_id,sku,qty,unit_price). Day numbers are integers; 'today' is meta today_day.")


class UnsafeQuery(Exception):
    pass


def check_sql(sql: str) -> str:
    s = re.sub(r"--.*?$|/\*.*?\*/", " ", sql, flags=re.S | re.M).strip().rstrip(";").strip()
    if ";" in s:
        raise UnsafeQuery("multiple statements")
    if not re.match(r"(select|with)\b", s, re.I):
        raise UnsafeQuery("only SELECT allowed")
    if FORBIDDEN.search(s):
        raise UnsafeQuery("forbidden keyword")
    tables = {t.lower() for t in re.findall(r"\b(?:from|join)\s+([A-Za-z_]\w*)", s, re.I)}
    if not tables <= ALLOWED_TABLES:
        raise UnsafeQuery(f"table not allowed: {sorted(tables - ALLOWED_TABLES)}")
    return s


def offline_translate(env: Env, q: str) -> str | None:
    ql = q.lower().strip().rstrip("?.")
    t = env.today
    sku = re.search(r"sku-\d+", ql)
    n = re.search(r"(\d+)\s*(day|days)", ql)
    top = re.search(r"top\s+(\d+)", ql)
    if sku and re.search(r"cheapest", ql):
        return f"SELECT s.name FROM prices p JOIN suppliers s ON s.id=p.supplier_id WHERE p.sku='{sku.group().upper()}' AND p.in_stock=1 ORDER BY p.unit_price LIMIT 1"
    if sku and re.search(r"sold|sales", ql):
        d = int(n.group(1)) if n else 30
        return f"SELECT COALESCE(SUM(qty),0) FROM sales WHERE sku='{sku.group().upper()}' AND day>={t - d}"
    if sku and re.search(r"(stock|on hand|many units)", ql):
        return f"SELECT on_hand FROM stock WHERE sku='{sku.group().upper()}'"
    if sku and re.search(r"unit cost|cost of", ql):
        return f"SELECT unit_cost FROM items WHERE sku='{sku.group().upper()}'"
    if re.search(r"expir", ql):
        d = int(n.group(1)) if n else 30 if "month" in ql else 7 if "week" in ql else 14
        return f"SELECT DISTINCT sku FROM batches WHERE expiry_day IS NOT NULL AND expiry_day<={t + d} ORDER BY sku"
    if re.search(r"below (the )?reorder", ql):
        return "SELECT i.sku FROM items i JOIN stock s USING(sku) WHERE s.on_hand<=i.reorder_point ORDER BY i.sku"
    if re.search(r"total (stock|inventory) value", ql):
        return "SELECT ROUND(SUM(s.on_hand*i.unit_cost),2) FROM stock s JOIN items i USING(sku)"
    if re.search(r"most reliable supplier", ql):
        return "SELECT name FROM suppliers ORDER BY reliability DESC LIMIT 1"
    if top and re.search(r"sell|sold|selling", ql):
        d = int(n.group(1)) if n else 30
        return f"SELECT sku FROM sales WHERE day>={t - d} GROUP BY sku ORDER BY SUM(qty) DESC, sku LIMIT {top.group(1)}"
    if re.search(r"how many (items|skus|products)", ql):
        return "SELECT COUNT(*) FROM items"
    if re.search(r"how many suppliers", ql):
        return "SELECT COUNT(*) FROM suppliers"
    if re.search(r"perishable", ql):
        return "SELECT sku FROM items WHERE shelf_life_days IS NOT NULL ORDER BY sku"
    cat = re.search(r"category\s+([a-z ]+)$", ql)
    if cat and "average" in ql:
        return f"SELECT ROUND(AVG(unit_cost),4) FROM items WHERE lower(category)='{cat.group(1).strip()}'"
    if re.search(r"(open|pending) (purchase orders|pos)", ql):
        return "SELECT COUNT(*) FROM pos WHERE status='PENDING_APPROVAL'"
    return None


def ask(env: Env, question: str) -> dict:
    """Returns {status: ok|blocked|unanswerable, sql, rows}. Never writes."""
    if WRITE_INTENT.search(question) and not re.search(r"\b(set|add|change)\b.*\b(reorder|alert)", question, re.I):
        return {"status": "blocked", "reason": "write intent", "sql": None, "rows": []}
    sql = None
    if env.llm.available:
        sql = env.llm.complete("Translate the question to a single SQLite SELECT. Output only SQL. " + SCHEMA_HINT,
                               question, 200)
    sql = sql or offline_translate(env, question)
    if not sql:
        return {"status": "unanswerable", "sql": None, "rows": []}
    try:
        sql = check_sql(sql)
        rows = [tuple(r) for r in env.db.execute(sql).fetchmany(200)]  # read-only connection as second layer
    except Exception as e:
        return {"status": "blocked", "reason": str(e), "sql": sql, "rows": []}
    return {"status": "ok", "sql": sql, "rows": rows}
