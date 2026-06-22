"""
Build or refresh the ChromaDB PDF index under rag_system/data/chroma_db.

Usage (from repo root, venv activated):
    python rag_system/scripts/build_pdf_index.py
    python rag_system/scripts/build_pdf_index.py --force
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

RAG_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(RAG_ROOT / ".env")

from pdf_tool1 import PDFTool


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ChromaDB PDF index")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete the existing index and rebuild from scratch",
    )
    args = parser.parse_args()

    data_dir = Path(os.getenv("DATA_DIR", RAG_ROOT / "data"))
    pdf_dir = data_dir / "pdfs"
    persist_dir = data_dir / "chroma_db"

    if not pdf_dir.exists() or not list(pdf_dir.glob("*.pdf")):
        print(f"Error: no PDFs found in {pdf_dir}")
        print("Run setup.sh from the repo root first, or copy PDFs into rag_system/data/pdfs/")
        sys.exit(1)

    if not os.getenv("FIREWORKS_API_KEY"):
        print("Error: FIREWORKS_API_KEY is not set (add it to rag_system/.env)")
        sys.exit(1)

    pdf_count = len(list(pdf_dir.glob("*.pdf")))
    print(f"Indexing {pdf_count} PDFs from {pdf_dir}")
    print(f"ChromaDB output: {persist_dir}")

    tool = PDFTool(pdf_dir=pdf_dir, persist_dir=persist_dir, ensure_indexed=False)
    if args.force:
        print("Force rebuild: deleting existing index...")
        tool.reindex_all()
    else:
        tool._ensure_indexed()
    chunk_count = tool.collection.count()
    tool.close()

    print(f"Done. Indexed {chunk_count} chunks in {persist_dir}")


if __name__ == "__main__":
    main()
