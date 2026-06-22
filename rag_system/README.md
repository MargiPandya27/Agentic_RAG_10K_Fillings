# Agentic RAG for 10-K Analysis

A local agentic RAG system that answers financial research questions over structured data and 10-K PDF filings for Apple, Microsoft, and Alphabet (FY2024–2025).

## System Overview

The agent routes each question to the right source:
- **SQL tool**: structured financial data (revenue, income, balance sheets, segments, geography)
- **PDF tool**: narrative 10-K content (risk factors, strategy, segment definitions, MD&A)
- **Both**: questions requiring numbers + explanations

Questions are processed in a plan → retrieve → synthesize pipeline using Fireworks LLMs.

## Requirements

- Python 3.11+
- `uv` package manager (or pip)
- Fireworks API key (`FIREWORKS_API_KEY`)
- Assignment data set up via `setup.sh` (or copied into `rag_system/data/`)

## Setup

### 1. Bootstrap data and starter environment

```bash
# Repo root — Git Bash or WSL on Windows
./setup.sh
```

This creates `data/financials.db` and `data/pdfs/` with 6 10-K filings.

If you keep data under `rag_system/data/` instead, set `DATA_DIR` accordingly in `.env`.

### 2. Install RAG dependencies

**Windows PowerShell (repo root):**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r rag_system/requirements.txt
```

**Linux / Mac / Git Bash:**

```bash
source .venv/bin/activate
pip install -r rag_system/requirements.txt
```

### 3. Build the PDF index (first time only)

```powershell
python rag_system/scripts/build_pdf_index.py
```

This indexes PDFs into `rag_system/data/chroma_db/` (~3–5 minutes).

### 4. Environment variables

Create `rag_system/.env`:

```
FIREWORKS_API_KEY=your_key_here
DATA_DIR=rag_system/data
```

## Running the Server

**Windows PowerShell:**

```powershell
cd rag_system/src
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Linux / Mac:**

```bash
cd rag_system/src
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server will:
1. Start at `http://localhost:8000`
2. Serve the chat UI at `http://localhost:8000`
3. Expose the API at `http://localhost:8000/api/chat`

## API Usage

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What was Apple total revenue in FY2025?"}'
```

Response:

```json
{
  "answer": "AAPL fiscal year 2025; revenue $416.2B (per SQL data)",
  "sources": [{"type": "sql", "sql": "SELECT ...", "content": "..."}]
}
```

## Generating dev_answers.json

From the **repo root** with venv activated:

```powershell
python rag_system/scripts/generate_answers.py --skip-pdf-index
```

This runs all 10 dev questions and saves to:
- `rag_system/questions/dev_answers.json`
- `questions/dev_answers.json` (submission copy)

Use without `--skip-pdf-index` only if you need to rebuild the ChromaDB cache.

## Running Evaluation

```powershell
python rag_system/scripts/evaluate.py
```

Scores answers against `questions/dev_questions_with_answers.json` using:
- **fuzzy_numeric**: ±2% tolerance for numeric answers
- **entity_match**: checks if the correct company/entity is named
- **llm_judge**: Fireworks LLM scores qualitative answers 0–1

Results are written to `eval_results.json`.

## Project Structure

```
rag_system/
  src/
    main.py          # FastAPI server
    agent.py         # Core agent with routing logic
    sql_tool.py      # Text-to-SQL + preset queries for fragile patterns
    pdf_tool1.py     # PDF chunking, embedding, retrieval via ChromaDB
  static/
    index.html       # Chat UI
  scripts/
    build_pdf_index.py  # Build/refresh ChromaDB index
    generate_answers.py # Run dev questions and save dev_answers.json
    evaluate.py         # Score against public answer key
  data/
    financials.db    # SQLite database
    pdfs/            # Six 10-K PDFs
    chroma_db/       # Cached PDF embeddings
  questions/
    dev_questions.json
    dev_answers.json
  requirements.txt
```

## Models Used

| Purpose | Model |
|---------|-------|
| Routing, SQL generation, synthesis | `accounts/fireworks/models/deepseek-v4-pro` |
| Embeddings | `nomic-ai/nomic-embed-text-v1.5` |

