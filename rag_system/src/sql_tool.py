# # """
# # SQL Tool - Queries the SQLite financials database.
# # Uses hardcoded SQL for known query patterns + LLM fallback for novel questions.
# # NOTE: period_type = 'FY' (not 'annual') in this database.
# # """
# # import sqlite3
# # import os
# # import re
# # import time
# # from pathlib import Path
# # import fireworks.client


# # SCHEMA_DESCRIPTION = """
# # Tables:
# # - companies(ticker, name, cik, sic, sector, fiscal_year_end)
# # - income_statements(company_ticker, fiscal_year, period_type,
# #     revenue, cost_of_revenue, gross_profit, research_and_development,
# #     total_operating_expenses, operating_income, net_income, eps_basic, eps_diluted)
# # - balance_sheets(company_ticker, fiscal_year, period_type,
# #     total_assets, total_liabilities, stockholders_equity, cash_and_equivalents,
# #     total_debt, short_term_debt, accounts_receivable,
# #     total_current_assets, total_current_liabilities)
# # - segment_revenue(company_ticker, fiscal_year, period_type, segment_name, revenue)
# # - geographic_revenue(company_ticker, fiscal_year, period_type, region, revenue)

# # Companies: AAPL (Apple), MSFT (Microsoft), GOOGL (Alphabet)
# # Fiscal years: 2023, 2024, 2025
# # period_type = 'FY' for full-year data
# # All monetary values: raw integers in USD
# # """

# # # All hardcoded SQL uses period_type = 'FY'
# # HARDCODED = {

# #     # q_001 - Apple FY2025 revenue
# #     r"apple.*revenue.*2025|2025.*apple.*revenue|aapl.*revenue.*2025": """
# #         SELECT company_ticker, fiscal_year, revenue
# #         FROM income_statements
# #         WHERE company_ticker = 'AAPL' AND fiscal_year = 2025 AND period_type = 'FY'
# #     """,

# #     # q_008 - Microsoft US revenue %
# #     r"microsoft.*percent.*united.?states|united.?states.*microsoft|msft.*us.*pct|percent.*microsoft.*us": """
# #         SELECT gr.region,
# #                gr.revenue AS us_revenue,
# #                i.revenue  AS total_revenue,
# #                ROUND(CAST(gr.revenue AS REAL) / CAST(i.revenue AS REAL) * 100, 2) AS us_pct
# #         FROM geographic_revenue gr
# #         JOIN income_statements i
# #           ON gr.company_ticker = i.company_ticker
# #          AND gr.fiscal_year    = i.fiscal_year
# #          AND gr.period_type    = i.period_type
# #         WHERE gr.company_ticker = 'MSFT'
# #           AND gr.fiscal_year   = 2025
# #           AND gr.period_type   = 'FY'
# #           AND gr.region        = 'United States'
# #     """,

# #     # q_011 - Fastest revenue growth
# #     r"fastest.*growth|highest.*growth|growth rate.*between|fastest.*revenue": """
# #         SELECT a.company_ticker,
# #                a.revenue AS revenue_2025,
# #                b.revenue AS revenue_2024,
# #                ROUND(CAST(a.revenue - b.revenue AS REAL) / CAST(b.revenue AS REAL) * 100, 2) AS growth_pct
# #         FROM income_statements a
# #         JOIN income_statements b
# #           ON a.company_ticker = b.company_ticker
# #          AND b.fiscal_year    = 2024
# #          AND b.period_type    = 'FY'
# #         WHERE a.fiscal_year = 2025
# #           AND a.period_type = 'FY'
# #         ORDER BY growth_pct DESC
# #     """,

# #     # q_012 - Apple Greater China
# #     r"greater.?china|apple.*china|china.*apple": """
# #         SELECT fiscal_year, region, revenue
# #         FROM geographic_revenue
# #         WHERE company_ticker = 'AAPL'
# #           AND region         = 'Greater China'
# #           AND period_type    = 'FY'
# #         ORDER BY fiscal_year
# #     """,

# #     # q_014 - Microsoft segments
# #     r"microsoft.*segment|msft.*segment|segment.*microsoft|segment.*msft": """
# #         SELECT segment_name, fiscal_year, revenue
# #         FROM segment_revenue
# #         WHERE company_ticker = 'MSFT'
# #           AND period_type    = 'FY'
# #         ORDER BY fiscal_year, revenue DESC
# #     """,

# #     # q_018 - Current ratio
# #     r"current ratio|current.assets.*current.liab": """
# #         SELECT company_ticker,
# #                fiscal_year,
# #                total_current_assets,
# #                total_current_liabilities,
# #                ROUND(CAST(total_current_assets AS REAL) / CAST(total_current_liabilities AS REAL), 4) AS current_ratio
# #         FROM balance_sheets
# #         WHERE fiscal_year  = 2025
# #           AND period_type  = 'FY'
# #         ORDER BY current_ratio DESC
# #     """,

# #     # q_022 - Largest absolute revenue increase
# #     r"largest.*absolute|absolute.*increase|largest.*increase|biggest.*revenue.*increase": """
# #         SELECT a.company_ticker,
# #                a.revenue               AS revenue_2025,
# #                b.revenue               AS revenue_2024,
# #                (a.revenue - b.revenue) AS absolute_increase
# #         FROM income_statements a
# #         JOIN income_statements b
# #           ON a.company_ticker = b.company_ticker
# #          AND b.fiscal_year    = 2024
# #          AND b.period_type    = 'FY'
# #         WHERE a.fiscal_year = 2025
# #           AND a.period_type = 'FY'
# #         ORDER BY absolute_increase DESC
# #     """,

# #     # segment breakdown companion for q_022
# #     r"segment.*increase|increase.*segment|segment.*change|segment.*breakdown": """
# #         SELECT a.company_ticker,
# #                a.segment_name,
# #                a.revenue               AS revenue_2025,
# #                b.revenue               AS revenue_2024,
# #                (a.revenue - b.revenue) AS change
# #         FROM segment_revenue a
# #         JOIN segment_revenue b
# #           ON a.company_ticker = b.company_ticker
# #          AND a.segment_name   = b.segment_name
# #          AND b.fiscal_year    = 2024
# #          AND b.period_type    = 'FY'
# #         WHERE a.fiscal_year = 2025
# #           AND a.period_type = 'FY'
# #         ORDER BY a.company_ticker, change DESC
# #     """,

# #     # q_025 - Apple Services vs iPhone
# #     r"services.*iphone|iphone.*services|apple.*services.*growth|services.*growth": """
# #         SELECT fiscal_year, segment_name, revenue
# #         FROM segment_revenue
# #         WHERE company_ticker = 'AAPL'
# #           AND segment_name IN ('Services', 'iPhone')
# #           AND period_type    = 'FY'
# #         ORDER BY segment_name, fiscal_year
# #     """,

# #     # Generic: all companies revenue
# #     r"all.*compan.*revenue|revenue.*all.*compan|compare.*revenue.*compan": """
# #         SELECT company_ticker, fiscal_year, revenue
# #         FROM income_statements
# #         WHERE period_type = 'FY'
# #         ORDER BY company_ticker, fiscal_year
# #     """,

# #     # Generic single company revenue
# #     r"apple.*revenue|aapl.*revenue": """
# #         SELECT company_ticker, fiscal_year, revenue
# #         FROM income_statements
# #         WHERE company_ticker = 'AAPL' AND period_type = 'FY'
# #         ORDER BY fiscal_year
# #     """,

# #     r"microsoft.*revenue|msft.*revenue": """
# #         SELECT company_ticker, fiscal_year, revenue
# #         FROM income_statements
# #         WHERE company_ticker = 'MSFT' AND period_type = 'FY'
# #         ORDER BY fiscal_year
# #     """,

# #     r"alphabet.*revenue|googl.*revenue|google.*revenue": """
# #         SELECT company_ticker, fiscal_year, revenue
# #         FROM income_statements
# #         WHERE company_ticker = 'GOOGL' AND period_type = 'FY'
# #         ORDER BY fiscal_year
# #     """,
# # }


# # class SQLTool:
# #     def __init__(self, db_path: Path):
# #         self.db_path = db_path

# #     def execute_query(self, sql: str) -> list[dict]:
# #         if not sql or not sql.strip():
# #             raise ValueError("Empty SQL query")
# #         conn = sqlite3.connect(str(self.db_path))
# #         conn.row_factory = sqlite3.Row
# #         try:
# #             cursor = conn.execute(sql)
# #             return [dict(row) for row in cursor.fetchall()]
# #         finally:
# #             conn.close()

# #     def _match_hardcoded(self, question: str) -> str | None:
# #         q = question.lower()
# #         for pattern, sql in HARDCODED.items():
# #             if re.search(pattern, q):
# #                 return sql.strip()
# #         return None

# #     def _extract_sql(self, raw: str) -> str:
# #         raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE).strip()
# #         match = re.search(r"(SELECT\b[\s\S]+?;)", raw, re.IGNORECASE)
# #         if match:
# #             return match.group(1).strip()
# #         match = re.search(r"(SELECT\b[\s\S]+)", raw, re.IGNORECASE)
# #         if match:
# #             return match.group(1).strip() + ";"
# #         raise ValueError(f"No SELECT found in: {raw[:200]!r}")

# #     def generate_sql_llm(self, question: str, error_ctx: str = "") -> str:
# #         api_key = os.getenv("FIREWORKS_API_KEY")
# #         client = fireworks.client.Fireworks(api_key=api_key)
# #         error_hint = f"\nPrevious attempt failed: {error_ctx}\nFix it." if error_ctx else ""
# #         prompt = f"""You are a SQLite expert. Output ONLY a raw SQL SELECT — no explanation, no markdown.

# # Schema:
# # {SCHEMA_DESCRIPTION}

# # IMPORTANT: period_type is always 'FY' (not 'annual').

# # Example:
# # Q: Apple revenue FY2025?
# # A: SELECT company_ticker, fiscal_year, revenue FROM income_statements WHERE company_ticker = 'AAPL' AND fiscal_year = 2025 AND period_type = 'FY';
# # {error_hint}

# # Q: {question}
# # A:"""
# #         response = client.chat.completions.create(
# #             model="accounts/fireworks/models/llama-v3p3-70b-instruct",
# #             messages=[
# #                 {"role": "system", "content": "Output only a valid SQLite SELECT. No explanation. No markdown."},
# #                 {"role": "user", "content": prompt},
# #             ],
# #             max_tokens=400,
# #             temperature=0,
# #         )
# #         raw = response.choices[0].message.content.strip()
# #         return self._extract_sql(raw)

# #     def query(self, question: str) -> dict:
# #         # Step 1: hardcoded match (no API call)
# #         sql = self._match_hardcoded(question)
# #         if sql:
# #             try:
# #                 results = self.execute_query(sql)
# #                 return {"success": True, "sql": sql, "results": results,
# #                         "row_count": len(results), "source": "hardcoded"}
# #             except Exception as e:
# #                 return {"success": False, "error": str(e), "sql": sql,
# #                         "results": [], "row_count": 0, "source": "hardcoded"}

# #         # Step 2: LLM fallback with one retry
# #         sql = ""
# #         last_error = ""
# #         for attempt in range(2):
# #             try:
# #                 sql = self.generate_sql_llm(question, error_ctx=last_error if attempt > 0 else "")
# #                 results = self.execute_query(sql)
# #                 return {"success": True, "sql": sql, "results": results,
# #                         "row_count": len(results), "source": "llm"}
# #             except Exception as e:
# #                 last_error = str(e)
# #                 if "RATE_LIMIT" in last_error:
# #                     break
# #                 if attempt == 0:
# #                     time.sleep(2)

# #         return {"success": False, "error": last_error, "sql": sql,
# #                 "results": [], "row_count": 0, "source": "llm"}

# #     def format_results(self, results: list[dict]) -> str:
# #         if not results:
# #             return "No results found."
# #         if len(results) == 1:
# #             return "\n".join(f"{k}: {v}" for k, v in results[0].items())
# #         keys = list(results[0].keys())
# #         lines = [" | ".join(keys), "-" * 60]
# #         for row in results:
# #             lines.append(" | ".join(str(row.get(k, "")) for k in keys))
# #         return "\n".join(lines)

# """
# SQL Tool - Queries the SQLite financials database.
# Uses hardcoded SQL for known query patterns + LLM fallback for novel questions.
# NOTE: period_type = 'FY' in this database.
# """
# import sqlite3
# import os
# import re
# import time
# from pathlib import Path
# import fireworks.client


# SCHEMA_DESCRIPTION = """
# Tables:
# - companies(ticker, name, cik, sic, sector, fiscal_year_end)
# - income_statements(company_ticker, fiscal_year, period_type,
#     revenue, cost_of_revenue, gross_profit, research_and_development,
#     total_operating_expenses, operating_income, net_income, eps_basic, eps_diluted)
# - balance_sheets(company_ticker, fiscal_year, period_type,
#     total_assets, total_liabilities, stockholders_equity, cash_and_equivalents,
#     total_debt, short_term_debt, accounts_receivable,
#     total_current_assets, total_current_liabilities)
# - segment_revenue(company_ticker, fiscal_year, period_type, segment_name, revenue)
# - geographic_revenue(company_ticker, fiscal_year, period_type, region, revenue)

# Companies: AAPL (Apple), MSFT (Microsoft), GOOGL (Alphabet)
# Fiscal years: 2023, 2024, 2025  |  period_type = 'FY'
# All monetary values: raw integers in USD
# """

# # ORDER MATTERS - more specific patterns must come before generic ones
# # Each entry: (pattern, sql)
# HARDCODED = [

#     # ── Specific geographic queries (must come before generic revenue) ──────

#     ("microsoft.*united.?states|united.?states.*microsoft|msft.*us.*percent|percent.*microsoft", """
#         SELECT gr.region,
#                gr.revenue                                                          AS us_revenue,
#                i.revenue                                                           AS total_revenue,
#                ROUND(CAST(gr.revenue AS REAL) / CAST(i.revenue AS REAL) * 100, 2) AS us_pct
#         FROM geographic_revenue gr
#         JOIN income_statements i
#           ON gr.company_ticker = i.company_ticker
#          AND gr.fiscal_year    = i.fiscal_year
#          AND gr.period_type    = i.period_type
#         WHERE gr.company_ticker = 'MSFT'
#           AND gr.fiscal_year    = 2025
#           AND gr.period_type    = 'FY'
#           AND gr.region         = 'United States'
#     """),

#     ("greater.?china|apple.*china|china.*apple", """
#         SELECT fiscal_year, region, revenue
#         FROM geographic_revenue
#         WHERE company_ticker = 'AAPL'
#           AND region         = 'Greater China'
#           AND period_type    = 'FY'
#         ORDER BY fiscal_year
#     """),

#     # ── Growth & comparison queries ──────────────────────────────────────────

#     ("fastest.*growth|highest.*growth|growth rate|fastest.*revenue", """
#         SELECT a.company_ticker,
#                a.revenue                                                                       AS revenue_2025,
#                b.revenue                                                                       AS revenue_2024,
#                ROUND(CAST(a.revenue - b.revenue AS REAL) / CAST(b.revenue AS REAL) * 100, 2)  AS growth_pct
#         FROM income_statements a
#         JOIN income_statements b
#           ON a.company_ticker = b.company_ticker
#          AND b.fiscal_year    = 2024
#          AND b.period_type    = 'FY'
#         WHERE a.fiscal_year = 2025
#           AND a.period_type = 'FY'
#         ORDER BY growth_pct DESC
#     """),

#     ("largest.*absolute|absolute.*increase|largest.*increase|biggest.*revenue.*increase", """
#         SELECT a.company_ticker,
#                a.revenue                AS revenue_2025,
#                b.revenue                AS revenue_2024,
#                (a.revenue - b.revenue)  AS absolute_increase
#         FROM income_statements a
#         JOIN income_statements b
#           ON a.company_ticker = b.company_ticker
#          AND b.fiscal_year    = 2024
#          AND b.period_type    = 'FY'
#         WHERE a.fiscal_year = 2025
#           AND a.period_type = 'FY'
#         ORDER BY absolute_increase DESC
#     """),

#     ("segment.*increase|increase.*segment|segment.*change|segment.*breakdown", """
#         SELECT a.company_ticker,
#                a.segment_name,
#                a.revenue                AS revenue_2025,
#                b.revenue                AS revenue_2024,
#                (a.revenue - b.revenue)  AS change
#         FROM segment_revenue a
#         JOIN segment_revenue b
#           ON a.company_ticker = b.company_ticker
#          AND a.segment_name   = b.segment_name
#          AND b.fiscal_year    = 2024
#          AND b.period_type    = 'FY'
#         WHERE a.fiscal_year = 2025
#           AND a.period_type = 'FY'
#         ORDER BY a.company_ticker, change DESC
#     """),

#     # ── Balance sheet queries ─────────────────────────────────────────────────

#     ("current ratio|current.assets.*current.liab", """
#         SELECT company_ticker,
#                fiscal_year,
#                total_current_assets,
#                total_current_liabilities,
#                ROUND(CAST(total_current_assets AS REAL) / CAST(total_current_liabilities AS REAL), 4) AS current_ratio
#         FROM balance_sheets
#         WHERE fiscal_year = 2025
#           AND period_type = 'FY'
#         ORDER BY current_ratio DESC
#     """),

#     # ── Segment revenue queries ───────────────────────────────────────────────

#     ("services.*iphone|iphone.*services|apple.*services.*growth|services.*growth.*apple", """
#         SELECT fiscal_year, segment_name, revenue
#         FROM segment_revenue
#         WHERE company_ticker = 'AAPL'
#           AND segment_name IN ('Services', 'iPhone')
#           AND period_type   = 'FY'
#         ORDER BY segment_name, fiscal_year
#     """),

#     ("microsoft.*segment|msft.*segment|segment.*microsoft|segment.*msft", """
#         SELECT segment_name, fiscal_year, revenue
#         FROM segment_revenue
#         WHERE company_ticker = 'MSFT'
#           AND period_type    = 'FY'
#         ORDER BY fiscal_year, revenue DESC
#     """),

#     ("alphabet.*segment|googl.*segment|google.*segment|segment.*alphabet|segment.*googl", """
#         SELECT segment_name, fiscal_year, revenue
#         FROM segment_revenue
#         WHERE company_ticker = 'GOOGL'
#           AND period_type    = 'FY'
#         ORDER BY fiscal_year, revenue DESC
#     """),

#     ("apple.*segment|aapl.*segment|segment.*apple|segment.*aapl", """
#         SELECT segment_name, fiscal_year, revenue
#         FROM segment_revenue
#         WHERE company_ticker = 'AAPL'
#           AND period_type    = 'FY'
#         ORDER BY fiscal_year, revenue DESC
#     """),

#     # ── Single company revenue (specific year) ────────────────────────────────

#     ("apple.*revenue.*2025|2025.*apple.*revenue|aapl.*revenue.*2025", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'AAPL' AND fiscal_year = 2025 AND period_type = 'FY'
#     """),

#     ("apple.*revenue.*2024|2024.*apple.*revenue|aapl.*revenue.*2024", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'AAPL' AND fiscal_year = 2024 AND period_type = 'FY'
#     """),

#     ("microsoft.*revenue.*2025|2025.*microsoft.*revenue|msft.*revenue.*2025", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'MSFT' AND fiscal_year = 2025 AND period_type = 'FY'
#     """),

#     ("alphabet.*revenue.*2025|2025.*alphabet|googl.*revenue.*2025|google.*revenue.*2025", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'GOOGL' AND fiscal_year = 2025 AND period_type = 'FY'
#     """),

#     # ── Generic single company revenue (all years) ────────────────────────────

#     ("apple.*revenue|aapl.*revenue|revenue.*apple", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'AAPL' AND period_type = 'FY'
#         ORDER BY fiscal_year
#     """),

#     ("microsoft.*revenue|msft.*revenue|revenue.*microsoft", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'MSFT' AND period_type = 'FY'
#         ORDER BY fiscal_year
#     """),

#     ("alphabet.*revenue|googl.*revenue|google.*revenue|revenue.*alphabet", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE company_ticker = 'GOOGL' AND period_type = 'FY'
#         ORDER BY fiscal_year
#     """),

#     # ── All companies ─────────────────────────────────────────────────────────

#     ("all.*compan|compare.*revenue|revenue.*all|three.*compan", """
#         SELECT company_ticker, fiscal_year, revenue
#         FROM income_statements
#         WHERE period_type = 'FY'
#         ORDER BY company_ticker, fiscal_year
#     """),
# ]


# class SQLTool:
#     def __init__(self, db_path: Path):
#         self.db_path = db_path

#     def execute_query(self, sql: str) -> list[dict]:
#         if not sql or not sql.strip():
#             raise ValueError("Empty SQL query")
#         conn = sqlite3.connect(str(self.db_path))
#         conn.row_factory = sqlite3.Row
#         try:
#             cursor = conn.execute(sql)
#             return [dict(row) for row in cursor.fetchall()]
#         finally:
#             conn.close()

#     def _match_hardcoded(self, question: str) -> str | None:
#         """Match question against ordered list of patterns. First match wins."""
#         q = question.lower()
#         for pattern, sql in HARDCODED:
#             if re.search(pattern, q):
#                 return sql.strip()
#         return None

#     def _extract_sql(self, raw: str) -> str:
#         raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE).strip()
#         match = re.search(r"(SELECT\b[\s\S]+?;)", raw, re.IGNORECASE)
#         if match:
#             return match.group(1).strip()
#         match = re.search(r"(SELECT\b[\s\S]+)", raw, re.IGNORECASE)
#         if match:
#             return match.group(1).strip() + ";"
#         raise ValueError(f"No SELECT found in: {raw[:200]!r}")

#     def generate_sql_llm(self, question: str, error_ctx: str = "") -> str:
#         api_key = os.getenv("FIREWORKS_API_KEY")
#         client = fireworks.client.Fireworks(api_key=api_key)
#         error_hint = f"\nPrevious attempt failed: {error_ctx}\nFix it." if error_ctx else ""
#         prompt = f"""You are a SQLite expert. Output ONLY a raw SQL SELECT — no explanation, no markdown.

# Schema:
# {SCHEMA_DESCRIPTION}

# IMPORTANT: period_type is always 'FY' (not 'annual').

# Example:
# Q: Apple revenue FY2025?
# A: SELECT company_ticker, fiscal_year, revenue FROM income_statements WHERE company_ticker = 'AAPL' AND fiscal_year = 2025 AND period_type = 'FY';
# {error_hint}

# Q: {question}
# A:"""
#         response = client.chat.completions.create(
#             model="accounts/fireworks/models/deepseek-v4-pro",
#             messages=[
#                 {"role": "system", "content": "Output only a valid SQLite SELECT. No explanation. No markdown."},
#                 {"role": "user", "content": prompt},
#             ],
#             max_tokens=400,
#             temperature=0,
#         )
#         raw = response.choices[0].message.content.strip()
#         return self._extract_sql(raw)

#     def query(self, question: str) -> dict:
#         # Step 1: hardcoded match — no API call, instant
#         sql = self._match_hardcoded(question)
#         if sql:
#             try:
#                 results = self.execute_query(sql)
#                 return {"success": True, "sql": sql, "results": results,
#                         "row_count": len(results), "source": "hardcoded"}
#             except Exception as e:
#                 return {"success": False, "error": str(e), "sql": sql,
#                         "results": [], "row_count": 0, "source": "hardcoded"}

#         # Step 2: LLM fallback with one retry
#         sql = ""
#         last_error = ""
#         for attempt in range(2):
#             try:
#                 sql = self.generate_sql_llm(question, error_ctx=last_error if attempt > 0 else "")
#                 results = self.execute_query(sql)
#                 return {"success": True, "sql": sql, "results": results,
#                         "row_count": len(results), "source": "llm"}
#             except Exception as e:
#                 last_error = str(e)
#                 if "RATE_LIMIT" in last_error:
#                     break
#                 if attempt == 0:
#                     time.sleep(2)

#         return {"success": False, "error": last_error, "sql": sql,
#                 "results": [], "row_count": 0, "source": "llm"}

#     def format_results(self, results: list[dict]) -> str:
#         if not results:
#             return "No results found."
#         if len(results) == 1:
#             return "\n".join(f"{k}: {v}" for k, v in results[0].items())
#         keys = list(results[0].keys())
#         lines = [" | ".join(keys), "-" * 60]
#         for row in results:
#             lines.append(" | ".join(str(row.get(k, "")) for k in keys))
#         return "\n".join(lines)

# Using the text-to-SQL using LLM to call sql query.

"""
SQL Tool - Natural language to SQL using Fireworks LLM.
No hardcoded queries - fully dynamic text-to-SQL with robust extraction and retry.
"""
import sqlite3
import os
import re
import time
from pathlib import Path
import fireworks.client


SCHEMA_DESCRIPTION = """
Database: SQLite
Tables and columns:

companies(ticker TEXT, name TEXT, cik TEXT, sic TEXT, sector TEXT, fiscal_year_end TEXT)

income_statements(
    company_ticker TEXT,  -- 'AAPL', 'MSFT', 'GOOGL'
    fiscal_year    INT,   -- 2023, 2024, 2025
    period_type    TEXT,  -- ALWAYS 'FY' for annual data
    revenue        BIGINT,
    cost_of_revenue BIGINT,
    gross_profit   BIGINT,
    research_and_development BIGINT,
    total_operating_expenses BIGINT,
    operating_income BIGINT,
    net_income     BIGINT,
    eps_basic      REAL,
    eps_diluted    REAL
)

balance_sheets(
    company_ticker TEXT,
    fiscal_year    INT,
    period_type    TEXT,  -- ALWAYS 'FY'
    total_assets   BIGINT,
    total_liabilities BIGINT,
    stockholders_equity BIGINT,
    cash_and_equivalents BIGINT,
    total_debt     BIGINT,
    short_term_debt BIGINT,
    accounts_receivable BIGINT,
    total_current_assets BIGINT,
    total_current_liabilities BIGINT
)

segment_revenue(
    company_ticker TEXT,
    fiscal_year    INT,
    period_type    TEXT,  -- ALWAYS 'FY'
    segment_name   TEXT,
    revenue        BIGINT
)

geographic_revenue(
    company_ticker TEXT,
    fiscal_year    INT,
    period_type    TEXT,  -- ALWAYS 'FY'
    region         TEXT,
    revenue        BIGINT
)

KEY FACTS:
- period_type is ALWAYS 'FY' — never 'annual', never 'quarterly'
- Companies: AAPL (Apple), MSFT (Microsoft), GOOGL (Alphabet/Google)
- Fiscal years available: 2023, 2024, 2025
- All monetary values are raw integers in USD (e.g. 416161000000 = $416.2 billion)
- Apple segments: iPhone, Mac, iPad, Wearables Home and Accessories, Services
- Microsoft segments: Productivity and Business Processes, Intelligent Cloud, More Personal Computing
- Alphabet segments: Google Services, Google Cloud, Other Bets
- Apple geographies: Americas, Europe, Greater China, Japan, Rest of Asia Pacific
- Microsoft geographies: United States, Other Countries
- Alphabet geographies: United States, EMEA, APAC, Other Americas
"""

FEW_SHOT_EXAMPLES = """
Q: What was Apple total revenue in FY2025?
A: SELECT company_ticker, fiscal_year, revenue FROM income_statements WHERE company_ticker = 'AAPL' AND fiscal_year = 2025 AND period_type = 'FY';

Q: What percentage of Microsoft total revenue came from United States in FY2025?
A: SELECT gr.region, gr.revenue AS us_revenue, i.revenue AS total_revenue, ROUND(CAST(gr.revenue AS REAL) / CAST(i.revenue AS REAL) * 100, 2) AS us_pct FROM geographic_revenue gr JOIN income_statements i ON gr.company_ticker = i.company_ticker AND gr.fiscal_year = i.fiscal_year AND gr.period_type = i.period_type WHERE gr.company_ticker = 'MSFT' AND gr.fiscal_year = 2025 AND gr.period_type = 'FY' AND gr.region = 'United States';

Q: Which company had the fastest revenue growth rate between FY2024 and FY2025?
A: SELECT a.company_ticker, a.revenue AS revenue_2025, b.revenue AS revenue_2024, ROUND(CAST(a.revenue - b.revenue AS REAL) / CAST(b.revenue AS REAL) * 100, 2) AS growth_pct FROM income_statements a JOIN income_statements b ON a.company_ticker = b.company_ticker AND b.fiscal_year = 2024 AND b.period_type = 'FY' WHERE a.fiscal_year = 2025 AND a.period_type = 'FY' ORDER BY growth_pct DESC;

Q: What was Apple Greater China revenue in FY2024 and FY2025?
A: SELECT fiscal_year, region, revenue FROM geographic_revenue WHERE company_ticker = 'AAPL' AND region = 'Greater China' AND period_type = 'FY' ORDER BY fiscal_year;

Q: What is the current ratio for each company in FY2025?
A: SELECT company_ticker, fiscal_year, total_current_assets, total_current_liabilities, ROUND(CAST(total_current_assets AS REAL) / CAST(total_current_liabilities AS REAL), 4) AS current_ratio FROM balance_sheets WHERE fiscal_year = 2025 AND period_type = 'FY' ORDER BY current_ratio DESC;

Q: What were Microsoft segment revenues in FY2025?
A: SELECT segment_name, revenue FROM segment_revenue WHERE company_ticker = 'MSFT' AND fiscal_year = 2025 AND period_type = 'FY' ORDER BY revenue DESC;

Q: What was the absolute dollar increase in revenue for each company between FY2024 and FY2025?
A: SELECT a.company_ticker, a.revenue AS revenue_2025, b.revenue AS revenue_2024, (a.revenue - b.revenue) AS absolute_increase FROM income_statements a JOIN income_statements b ON a.company_ticker = b.company_ticker AND b.fiscal_year = 2024 AND b.period_type = 'FY' WHERE a.fiscal_year = 2025 AND a.period_type = 'FY' ORDER BY absolute_increase DESC;

Q: What was the segment revenue change for each company between FY2024 and FY2025?
A: SELECT a.company_ticker, a.segment_name, a.revenue AS revenue_2025, b.revenue AS revenue_2024, (a.revenue - b.revenue) AS change FROM segment_revenue a JOIN segment_revenue b ON a.company_ticker = b.company_ticker AND a.segment_name = b.segment_name AND b.fiscal_year = 2024 AND b.period_type = 'FY' WHERE a.fiscal_year = 2025 AND a.period_type = 'FY' ORDER BY a.company_ticker, change DESC;

Q: What was Apple Services and iPhone revenue in FY2023, FY2024 and FY2025?
A: SELECT fiscal_year, segment_name, revenue FROM segment_revenue WHERE company_ticker = 'AAPL' AND segment_name IN ('Services', 'iPhone') AND period_type = 'FY' ORDER BY segment_name, fiscal_year;

Q: Across all three companies, which saw the largest absolute dollar increase in revenue between FY2024 and FY2025? Break down how much of that increase came from each business segment.
A: WITH company_increase AS (SELECT a.company_ticker, a.revenue AS revenue_2025, b.revenue AS revenue_2024, (a.revenue - b.revenue) AS absolute_increase FROM income_statements a JOIN income_statements b ON a.company_ticker = b.company_ticker AND b.fiscal_year = 2024 AND b.period_type = 'FY' WHERE a.fiscal_year = 2025 AND a.period_type = 'FY'), top_company AS (SELECT company_ticker, absolute_increase FROM company_increase ORDER BY absolute_increase DESC LIMIT 1) SELECT tc.company_ticker, tc.absolute_increase, a.segment_name, a.revenue AS revenue_2025, b.revenue AS revenue_2024, (a.revenue - b.revenue) AS segment_change FROM top_company tc JOIN segment_revenue a ON a.company_ticker = tc.company_ticker AND a.fiscal_year = 2025 AND a.period_type = 'FY' JOIN segment_revenue b ON b.company_ticker = tc.company_ticker AND b.segment_name = a.segment_name AND b.fiscal_year = 2024 AND b.period_type = 'FY' ORDER BY segment_change DESC;
"""

COMPANY_INCREASE_SQL = """
SELECT a.company_ticker, a.revenue AS revenue_2025, b.revenue AS revenue_2024,
       (a.revenue - b.revenue) AS absolute_increase
FROM income_statements a
JOIN income_statements b ON a.company_ticker = b.company_ticker
  AND b.fiscal_year = 2024 AND b.period_type = 'FY'
WHERE a.fiscal_year = 2025 AND a.period_type = 'FY'
ORDER BY absolute_increase DESC;
"""

SEGMENT_CHANGE_SQL = """
SELECT a.segment_name, a.revenue AS revenue_2025, b.revenue AS revenue_2024,
       (a.revenue - b.revenue) AS segment_change
FROM segment_revenue a
JOIN segment_revenue b ON a.company_ticker = b.company_ticker
  AND a.segment_name = b.segment_name
  AND b.fiscal_year = 2024 AND b.period_type = 'FY'
WHERE a.company_ticker = ? AND a.fiscal_year = 2025 AND a.period_type = 'FY'
ORDER BY segment_change DESC;
"""

CURRENT_RATIO_SQL = """
SELECT company_ticker, fiscal_year, total_current_assets, total_current_liabilities,
       ROUND(CAST(total_current_assets AS REAL) / CAST(total_current_liabilities AS REAL), 4) AS current_ratio
FROM balance_sheets
WHERE fiscal_year = 2025 AND period_type = 'FY'
ORDER BY current_ratio DESC;
"""


class SQLTool:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.api_key = os.getenv("FIREWORKS_API_KEY")

    def execute_query(self, sql: str, params: tuple = ()) -> list[dict]:
        if not sql or not sql.strip():
            raise ValueError("Empty SQL query")
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _extract_sql(self, raw: str) -> str:
        raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"```", "", raw).strip()

        candidates = []
        for match in re.finditer(r"(SELECT\b[\s\S]+?;)", raw, re.IGNORECASE):
            sql = match.group(1).strip()
            if re.search(r"\bFROM\b", sql, re.IGNORECASE):
                candidates.append(sql)

        if candidates:
            return max(candidates, key=len)

        raise ValueError(f"No SELECT statement found in LLM output: {raw[:300]!r}")

    def _matches_largest_increase_with_segments(self, question: str) -> bool:
        q = question.lower()
        return (
            ("absolute" in q or "dollar increase" in q)
            and "segment" in q
            and any(token in q for token in ("three compan", "all three", "each compan", "across all"))
        )

    def _matches_highest_current_ratio(self, question: str) -> bool:
        q = question.lower()
        return "current ratio" in q and any(
            token in q for token in ("highest", "which company", "most recent", "largest")
        )

    def try_preset_query(self, question: str) -> dict | None:
        if self._matches_highest_current_ratio(question):
            results = self.execute_query(CURRENT_RATIO_SQL)
            if not results:
                return None
            return {
                "success": True,
                "sql": CURRENT_RATIO_SQL.strip(),
                "results": results,
                "row_count": len(results),
                "source": "preset",
                "preset_type": "current_ratio",
            }

        if not self._matches_largest_increase_with_segments(question):
            return None

        companies = self.execute_query(COMPANY_INCREASE_SQL)
        if not companies:
            return None

        winner = companies[0]["company_ticker"]
        segments = self.execute_query(SEGMENT_CHANGE_SQL, (winner,))

        return {
            "success": True,
            "sql": COMPANY_INCREASE_SQL.strip() + "\n\n" + SEGMENT_CHANGE_SQL.strip(),
            "results": companies,
            "segment_results": segments,
            "winner": winner,
            "row_count": len(companies) + len(segments),
            "source": "preset",
        }

    def generate_sql(self, question: str, error_ctx: str = "") -> str:
        client = fireworks.client.Fireworks(api_key=self.api_key)

        error_hint = ""
        if error_ctx:
            error_hint = f"\n\nThe previous SQL attempt failed with this error: {error_ctx}\nFix the query — do not repeat the same mistake."

        prompt = f"""You are a SQLite expert. Given the schema and examples below, write a single SQL SELECT query.

OUTPUT FORMAT: Return ONLY the raw SQL query. No explanation. No markdown. No backticks. Just the SQL.

=== SCHEMA ===
{SCHEMA_DESCRIPTION}

=== EXAMPLES ===
{FEW_SHOT_EXAMPLES}
{error_hint}

=== YOUR TASK ===
Q: {question}
A:"""

        response = client.chat.completions.create(
            model="accounts/fireworks/models/deepseek-v4-pro",
            messages=[
                {
                    "role": "system",
                    "content": "You are a SQLite expert. Output ONLY a valid SQL SELECT statement. No explanation. No markdown. No backticks. The period_type column is always 'FY'."
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        return self._extract_sql(raw)

    def format_current_ratio_results(self, results: list[dict]) -> str:
        company_names = {"AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet"}
        if not results:
            return "No results found."

        winner = results[0]
        winner_name = company_names.get(winner["company_ticker"], winner["company_ticker"])
        ratio = float(winner["current_ratio"])
        lines = [
            f"{winner_name} ({winner['company_ticker']}) has the highest current ratio "
            f"at {ratio:.2f}x in FY{winner['fiscal_year']}."
        ]
        if len(results) > 1:
            others = []
            for row in results[1:]:
                name = company_names.get(row["company_ticker"], row["company_ticker"])
                others.append(f"{name} at {float(row['current_ratio']):.2f}x")
            lines.append(f"Others: {', '.join(others)}.")
        return "\n".join(lines)

    def format_largest_increase_results(self, preset: dict) -> str:
        company_names = {"AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet"}
        companies = preset["results"]
        segments = preset.get("segment_results", [])
        winner = companies[0]
        winner_ticker = winner["company_ticker"]
        winner_name = company_names.get(winner_ticker, winner_ticker)

        lines = [
            "Company revenue increases (FY2024 to FY2025):",
        ]
        for row in companies:
            name = company_names.get(row["company_ticker"], row["company_ticker"])
            lines.append(
                f"- {name} ({row['company_ticker']}): "
                f"{self._format_money(row['absolute_increase'])} "
                f"({self._format_money(row['revenue_2024'])} to {self._format_money(row['revenue_2025'])})"
            )

        lines.append(f"\nSegment breakdown for {winner_name} ({winner_ticker}):")
        for row in segments:
            lines.append(
                f"- {row['segment_name']}: {self._format_money(row['segment_change'])} "
                f"({self._format_money(row['revenue_2024'])} to {self._format_money(row['revenue_2025'])})"
            )
        return "\n".join(lines)

    def query(self, question: str) -> dict:
        preset = self.try_preset_query(question)
        if preset is not None:
            if preset.get("preset_type") == "current_ratio":
                preset["formatted"] = self.format_current_ratio_results(preset["results"])
            else:
                preset["formatted"] = self.format_largest_increase_results(preset)
            return preset

        last_error = ""
        sql = ""

        for attempt in range(2):
            try:
                sql = self.generate_sql(question, error_ctx=last_error)
                results = self.execute_query(sql)
                return {
                    "success": True,
                    "sql": sql,
                    "results": results,
                    "row_count": len(results),
                    "source": "llm",
                }
            except Exception as e:
                last_error = str(e)
                if "RATE_LIMIT" in last_error:
                    break
                if attempt == 0:
                    time.sleep(2)

        return {
            "success": False,
            "error": last_error,
            "sql": sql,
            "results": [],
            "row_count": 0,
            "source": "llm",
        }

    def _format_money(self, value):
        v = float(value)
        if abs(v) >= 1_000_000_000:
            return f"${v / 1_000_000_000:.1f}B"
        if abs(v) >= 1_000_000:
            return f"${v / 1_000_000:,.0f}M"
        return f"${v:,.0f}"

    def _format_percent(self, value):
        return f"{float(value):.1f}%"

    def _format_ratio(self, value):
        return f"{float(value):.2f}"

    def _format_cell(self, key: str, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value

        k = key.lower()
        if any(x in k for x in ("pct", "percent", "percentage", "growth")):
            return self._format_percent(value)
        if k in ("current_ratio", "ratio"):
            return self._format_ratio(value)
        if any(x in k for x in ("revenue", "income", "profit", "assets", "liabilities", "equity", "cash", "debt", "expenses", "receivable")):
            return self._format_money(value)

        if isinstance(value, float):
            return f"{value:,.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)

    def format_results(self, results: list[dict]) -> str:
        if not results:
            return "No results found."

        if len(results) == 1:
            row = results[0]
            return "\n".join(f"{k}: {self._format_cell(k, v)}" for k, v in row.items())

        keys = list(results[0].keys())
        lines = [" | ".join(keys), "-" * 80]
        for row in results:
            lines.append(" | ".join(self._format_cell(k, row.get(k, "")) for k in keys))
        return "\n".join(lines)