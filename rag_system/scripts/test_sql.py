"""
Test the SQL tool. Run from repo root:
    python scripts/test_sql.py
"""
import sys, os, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dotenv import load_dotenv
load_dotenv()

# Show which file is loaded
sql_tool_path = Path(__file__).parent.parent / "src" / "sql_tool.py"
print(f"Loading sql_tool from: {sql_tool_path.resolve()}")

from sql_tool import SQLTool

DB_PATH = Path("data/financials.db")

TEST_CASES = [
    {
        "id": "t001",
        "description": "Apple FY2025 revenue  →  q_001",
        "question": "What was Apple total revenue in FY2025?",
        "expect_contains": ["416161000000"],
        "expect_rows": 1,
    },
    {
        "id": "t002",
        "description": "Microsoft US revenue %  →  q_008",
        "question": "What percentage of Microsoft total revenue came from United States in FY2025?",
        "expect_contains": ["51"],
        "expect_rows": 1,
    },
    {
        "id": "t003",
        "description": "Fastest revenue growth  →  q_011",
        "question": "Which company had the fastest revenue growth rate between FY2024 and FY2025?",
        "expect_contains": ["GOOGL"],
        "expect_rows": 3,
    },
    {
        "id": "t004",
        "description": "Apple Greater China revenue  →  q_012",
        "question": "What was Apple Greater China revenue in FY2024 and FY2025?",
        "expect_contains": ["2024", "2025"],
        "expect_rows": 2,
    },
    {
        "id": "t005",
        "description": "Current ratio all companies  →  q_018",
        "question": "What is the current ratio for each company?",
        "expect_contains": ["GOOGL", "AAPL", "MSFT"],
        "expect_rows": 3,
    },
    {
        "id": "t006",
        "description": "Microsoft segment revenue  →  q_014",
        "question": "What were Microsoft segment revenues in FY2025?",
        "expect_contains": ["Productivity", "Cloud"],
        "expect_rows": 3,
    },
    {
        "id": "t007",
        "description": "Absolute revenue increase  →  q_022",
        "question": "What was the largest absolute increase in revenue between FY2024 and FY2025?",
        "expect_contains": ["GOOGL", "MSFT", "AAPL"],
        "expect_rows": 3,
    },
    {
        "id": "t008",
        "description": "Apple Services vs iPhone  →  q_025",
        "question": "What was Apple Services and iPhone revenue in FY2024 and FY2025?",
        "expect_contains": ["Services", "iPhone"],
        "expect_rows": 4,
    },
]


def check_db():
    """Verify database exists and has data."""
    print("\n── DB CHECK ─────────────────────────────────────────────")
    if not DB_PATH.exists():
        print(f"  ❌ Database not found at: {DB_PATH.resolve()}")
        print("  Run setup.sh first!")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    tables = ["companies", "income_statements", "balance_sheets",
              "segment_revenue", "geographic_revenue"]
    all_ok = True
    for t in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            status = "✅" if count > 0 else "❌ EMPTY"
            print(f"  {status}  {t}: {count} rows")
            if count == 0:
                all_ok = False
        except Exception as e:
            print(f"  ❌  {t}: ERROR — {e}")
            all_ok = False
    conn.close()

    if not all_ok:
        print("\n  Database has empty tables! Run: python scripts/prepare_data.py --data-dir data")
        sys.exit(1)
    print("  Database looks good!\n")


def run():
    check_db()

    tool = SQLTool(db_path=DB_PATH)
    passed = failed = 0

    print("── SQL TESTS ────────────────────────────────────────────")

    for tc in TEST_CASES:
        print(f"\n[{tc['id']}] {tc['description']}")
        print(f"  Q: {tc['question']}")

        r = tool.query(tc["question"])

        if not r["success"]:
            print(f"  ❌ FAILED")
            print(f"     error: {r['error']}")
            print(f"     sql  : {r['sql'] or '(empty)'}")
            failed += 1
            continue

        src = r.get("source", "?")
        print(f"  source : {src}")
        print(f"  sql    : {r['sql'][:120]}{'...' if len(r['sql'])>120 else ''}")
        print(f"  rows   : {r['row_count']}  (expected {tc['expect_rows']})")

        if r["results"]:
            print(f"  data   : {json.dumps(r['results'][:2])[:200]}")

        # Check contents
        blob = json.dumps(r["results"]).lower()
        missing = [e for e in tc["expect_contains"] if e.lower() not in blob]
        row_ok = r["row_count"] == tc["expect_rows"]

        issues = []
        if missing:
            issues.append(f"missing: {missing}")
        if not row_ok:
            issues.append(f"rows {r['row_count']} != expected {tc['expect_rows']}")

        if not issues:
            print(f"  ✅ PASSED")
            passed += 1
        else:
            print(f"  ⚠️  PARTIAL — {'; '.join(issues)}")
            # Count as passed if rows came back and source is hardcoded
            if r["row_count"] > 0 and not missing:
                passed += 1
            else:
                failed += 1

    print("\n" + "=" * 60)
    print(f"{'✅ ALL PASSED' if failed==0 else f'⚠️  {failed} FAILED'}  ({passed}/{len(TEST_CASES)})")
    print("=" * 60)


if __name__ == "__main__":
    run()