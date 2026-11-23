"""Query Agent: natural language -> verified read-only SQL -> answer.

Defence in depth:
  1. intent screen: write requests and prompt-injection phrasing are refused before any SQL exists
  2. parser allow-list (sqlglot AST): exactly one SELECT statement, no write/DDL nodes anywhere,
     only allow-listed tables
  3. read-only database role: mode=ro connection + PRAGMA query_only + an SQLite authorizer that
     denies every non-read action and hides users/audit/gate_ops
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from .agents import Env
from .data import HIDDEN_TABLES, ro_connect

ALLOWED_TABLES = {"items", "stock", "batches", "sales", "suppliers", "prices", "pos", "po_lines", "promotions",
                  "stockouts"}
WRITE_INTENT = re.compile(r"\b(delete|remove|drop|update|change|set|insert|add|modify|erase|wipe|truncate|"
                          r"alter|create|grant|approve|cancel|reset)\b", re.I)
INJECTION_INTENT = re.compile(r"ignore (all |any |previous |prior |the )*(instructions|rules)|system prompt|"
                              r"you are now|jailbreak|developer mode|disregard|pretend|act as", re.I)
SCHEMA_HINT = ("Tables: items(sku,name,category,unit_cost,shelf_life_days,reorder_point), stock(sku,on_hand), "
               "batches(sku,qty,expiry_day), sales(sku,day,qty), promotions(sku,day), "
               "suppliers(id,name,reliability,note), prices(supplier_id,sku,unit_price,moq,lead_time_days,in_stock), "
               "pos(po_id,status,supplier_id,total), po_lines(po_id,sku,qty,unit_price). Days are integers.")
_WRITE_NODES = tuple(getattr(exp, n) for n in ("Insert", "Update", "Delete", "Drop", "Create", "Alter", "Merge",
                                               "Command", "Pragma", "Attach", "Detach", "TruncateTable")
                     if hasattr(exp, n))


class UnsafeQuery(Exception):
    pass


def check_sql(sql: str) -> str:
    """Parse with sqlglot and allow only a single read-only SELECT over allow-listed tables."""
    s = (sql or "").strip()
    s = re.sub(r"^```(?:sql)?|```$", "", s, flags=re.I).strip()
    try:
        stmts = [x for x in sqlglot.parse(s, read="sqlite") if x is not None]
    except Exception as e:
        raise UnsafeQuery(f"unparseable SQL: {str(e)[:80]}")
    if len(stmts) != 1:
        raise UnsafeQuery("multiple statements" if len(stmts) > 1 else "empty query")
    tree = stmts[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeQuery("only SELECT allowed")
    if any(isinstance(n, _WRITE_NODES) for n in tree.walk()):
        raise UnsafeQuery("write or DDL operation inside query")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = {t.name.lower() for t in tree.find_all(exp.Table)} - ctes
    if not tables <= ALLOWED_TABLES:
        raise UnsafeQuery(f"table not allowed: {sorted(tables - ALLOWED_TABLES)}")
    return tree.sql(dialect="sqlite")


def offline_translate(env: Env, q: str) -> str | None:
    """Deterministic template translator used when no LLM is configured."""
    ql = q.lower().strip().rstrip("?.")
    t = env.today
    sku = re.search(r"sku-\d+", ql)
    n = re.search(r"(\d+)\s*(day|days)", ql)
    top = re.search(r"top\s+(\d+)", ql)
    S = sku.group().upper() if sku else None
    if sku and re.search(r"cheapest", ql):
        return (f"SELECT s.name FROM prices p JOIN suppliers s ON s.id=p.supplier_id WHERE p.sku='{S}' "
                "AND p.in_stock=1 ORDER BY p.unit_price LIMIT 1")
    if sku and re.search(r"sold|sales", ql):
        d = int(n.group(1)) if n else 30
        return f"SELECT COALESCE(SUM(qty),0) FROM sales WHERE sku='{S}' AND day>={t - d}"
    if sku and re.search(r"(stock|on hand|many units|have of)", ql):
        return f"SELECT on_hand FROM stock WHERE sku='{S}'"
    if sku and re.search(r"unit cost|cost of", ql):
        return f"SELECT unit_cost FROM items WHERE sku='{S}'"
    if sku and re.search(r"supplier", ql):
        return (f"SELECT s.name FROM prices p JOIN suppliers s ON s.id=p.supplier_id WHERE p.sku='{S}' "
                "ORDER BY s.name")
    if re.search(r"expir", ql):
        d = int(n.group(1)) if n else 30 if "month" in ql else 7 if "week" in ql else 14
        return f"SELECT DISTINCT sku FROM batches WHERE expiry_day IS NOT NULL AND expiry_day<={t + d} ORDER BY sku"
    if re.search(r"below (the )?reorder|low on stock|running low", ql):
        return "SELECT i.sku FROM items i JOIN stock s USING(sku) WHERE s.on_hand<=i.reorder_point ORDER BY i.sku"
    if re.search(r"total (stock|inventory) value", ql):
        return "SELECT ROUND(SUM(s.on_hand*i.unit_cost),2) FROM stock s JOIN items i USING(sku)"
    if re.search(r"most reliable supplier", ql):
        return "SELECT name FROM suppliers ORDER BY reliability DESC LIMIT 1"
    if re.search(r"least reliable supplier", ql):
        return "SELECT name FROM suppliers ORDER BY reliability ASC LIMIT 1"
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
    if re.search(r"promotion", ql) and n:
        return f"SELECT DISTINCT sku FROM promotions WHERE day>={t} AND day<{t + int(n.group(1))} ORDER BY sku"
    return None


def ask(env: Env, question: str) -> dict:
    """Natural-language question -> {status: ok|blocked|unanswerable, sql, rows, columns, mode}. Never writes."""
    mode = env.llm.mode
    if INJECTION_INTENT.search(question):
        return {"status": "blocked", "reason": "prompt-injection pattern in question", "sql": None, "rows": [],
                "columns": [], "mode": mode}
    if WRITE_INTENT.search(question) and not re.search(r"\b(set|add|change)\b.*\b(reorder|alert)", question, re.I):
        return {"status": "blocked", "reason": "write intent: the Query Agent is read-only", "sql": None, "rows": [],
                "columns": [], "mode": mode}
    sql, source = None, "offline-template"
    if env.llm.available:
        sql = env.llm.complete("Translate the question to a single SQLite SELECT. Output only SQL, no prose. "
                               + SCHEMA_HINT + f" Today is day {env.today}.", question, 250)
        source = "llm"
    if not sql:
        sql, source = offline_translate(env, question), "offline-template"
    if not sql:
        return {"status": "unanswerable", "sql": None, "rows": [], "columns": [], "mode": mode,
                "reason": "no template matches this question (offline mode)" if not env.llm.available else "no SQL"}
    try:
        sql = check_sql(sql)
        conn = ro_connect(env.db_path, hide=HIDDEN_TABLES)  # read-only role, second layer
        try:
            cur = conn.execute(sql)
            rows = [tuple(r) for r in cur.fetchmany(200)]
            cols = [d[0] for d in cur.description or []]
        finally:
            conn.close()
    except Exception as e:
        return {"status": "blocked", "reason": str(e), "sql": sql, "rows": [], "columns": [], "mode": mode,
                "source": source}
    return {"status": "ok", "sql": sql, "rows": rows, "columns": cols, "mode": mode, "source": source}
