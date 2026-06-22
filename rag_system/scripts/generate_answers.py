"""
Generate dev_answers.json by running all 10 dev questions through the agent.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent import RAGAgent
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAG_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(RAG_ROOT / ".env")


def main():
    parser = argparse.ArgumentParser(description="Generate dev_answers.json")
    parser.add_argument(
        "--skip-pdf-index",
        action="store_true",
        help="Skip PDF indexing and use the existing ChromaDB cache only",
    )
    args = parser.parse_args()

    data_dir = Path(os.getenv("DATA_DIR", RAG_ROOT / "data"))
    questions_file = RAG_ROOT / "questions" / "dev_questions.json"
    output_file = RAG_ROOT / "questions" / "dev_answers.json"

    if not questions_file.exists():
        print(f"Error: {questions_file} not found")
        sys.exit(1)

    questions = json.loads(questions_file.read_text())
    print(f"Loaded {len(questions)} questions")

    ensure_pdf_index = not args.skip_pdf_index
    if ensure_pdf_index:
        print("Indexing PDFs if needed before answering...")
    else:
        print("Skipping PDF indexing; using existing ChromaDB cache only.")

    agent = RAGAgent(data_dir=data_dir, ensure_pdf_index=ensure_pdf_index)
    answers = {}

    for q in questions:
        qid = q["id"]
        question = q["question"]
        tier = q["tier"]
        modalities = q["required_modalities"]

        print(f"\n[{qid}] Tier {tier} ({', '.join(modalities)})")
        print(f"  Q: {question[:80]}...")

        try:
            result = agent.answer(question, required_modalities=modalities)
            answer = result["answer"]
            tool_calls = result.get("tool_calls", [])
            sql_sources = [s for s in result.get("sources", []) if s.get("type") == "sql"]
            pdf_sources = [s for s in result.get("sources", []) if s.get("type") == "pdf"]
            sql_queries = [s.get("sql", "") for s in sql_sources if s.get("sql")]

            answer_record = {
                "answer": answer,
                "sql": sql_queries,
                "tool_calls": tool_calls,
            }
            if pdf_sources:
                answer_record["pdf_chunks"] = pdf_sources

            answers[qid] = answer_record
            print(f"  A: {answer[:100]}...")
            print(f"  Tool calls: {tool_calls}")

            if sql_queries:
                for index, sql_query in enumerate(sql_queries, start=1):
                    print(f"  SQL query {index}: {sql_query}")
        except Exception as e:
            print(f"  ERROR: {e}")
            answers[qid] = {"error": str(e)}

    payload = json.dumps(answers, indent=2)
    output_file.write_text(payload)

    submission_file = REPO_ROOT / "questions" / "dev_answers.json"
    submission_file.write_text(payload)
    print(f"\nSaved answers to {output_file}")
    print(f"Copied answers to {submission_file}")

    try:
        agent.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
