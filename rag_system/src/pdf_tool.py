# # # """
# # # PDF RAG Tool - Embeds and retrieves from 10-K PDF filings using ChromaDB.
# # # """
# # # import os
# # # import re
# # # import json
# # # import hashlib
# # # from pathlib import Path
# # # from typing import Optional
# # # import fireworks.client
# # # import chromadb
# # # from chromadb.config import Settings
# # # import pdfplumber


# # # CHUNK_SIZE = 800       # characters per chunk
# # # CHUNK_OVERLAP = 200    # overlap between chunks
# # # TOP_K = 5              # number of chunks to retrieve


# # # def extract_text_from_pdf(pdf_path: Path) -> str:
# # #     """Extract text from a PDF using pdfplumber."""
# # #     text_parts = []
# # #     with pdfplumber.open(str(pdf_path)) as pdf:
# # #         for page in pdf.pages:
# # #             text = page.extract_text()
# # #             if text:
# # #                 text_parts.append(text)
# # #     return "\n\n".join(text_parts)


# # # def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
# # #     """Split text into overlapping chunks."""
# # #     chunks = []
# # #     start = 0
# # #     while start < len(text):
# # #         end = start + chunk_size
# # #         chunk = text[start:end]
# # #         if chunk.strip():
# # #             chunks.append(chunk.strip())
# # #         start += chunk_size - overlap
# # #     return chunks


# # # class PDFTool:
# # #     def __init__(self, pdf_dir: Path, persist_dir: Path, ensure_indexed: bool = True):
# # #         self.pdf_dir = pdf_dir
# # #         self.persist_dir = persist_dir
# # #         self.api_key = os.getenv("FIREWORKS_API_KEY")
# # #         self.persist_dir.mkdir(parents=True, exist_ok=True)

# # #         # Initialize Fireworks API client and ChromaDB
# # #         self.client = fireworks.client.Fireworks(api_key=self.api_key)
# # #         self.chroma_client = chromadb.PersistentClient(
# # #             path=str(self.persist_dir),
# # #             settings=Settings(anonymized_telemetry=False),
# # #         )
# # #         self.collection = self.chroma_client.get_or_create_collection(
# # #             name="tenk_filings",
# # #             metadata={"hnsw:space": "cosine"},
# # #         )

# # #         # Index PDFs if not already done
# # #         if ensure_indexed:
# # #             self._ensure_indexed()

# # #     def close(self) -> None:
# # #         """Close the Fireworks client to release HTTP resources."""
# # #         try:
# # #             self.client.close()
# # #         except Exception:
# # #             pass

# # #     def get_embedding(self, texts: list[str]) -> list[list[float]]:
# # #         """Get embeddings from Fireworks API."""
# # #         response = self.client.embeddings.create(
# # #             model="nomic-ai/nomic-embed-text-v1.5",
# # #             input=texts,
# # #         )
# # #         return [item.embedding for item in response.data]

# # #     def _get_pdf_metadata(self, filename: str) -> dict:
# # #         """Parse ticker and fiscal year from filename like AAPL_FY2024_10-K.pdf"""
# # #         match = re.match(r"([A-Z]+)_FY(\d{4})_10-K\.pdf", filename)
# # #         if match:
# # #             return {"ticker": match.group(1), "fiscal_year": match.group(2)}
# # #         return {"ticker": "UNKNOWN", "fiscal_year": "UNKNOWN"}

# # #     def _ensure_indexed(self):
# # #         """Index all PDFs if not already in ChromaDB."""
# # #         pdf_files = list(self.pdf_dir.glob("*.pdf"))
# # #         if not pdf_files:
# # #             print("Warning: No PDFs found in", self.pdf_dir)
# # #             return

# # #         # Check which PDFs are already indexed
# # #         existing = set()
# # #         try:
# # #             results = self.collection.get(include=["metadatas"])
# # #             for meta in results["metadatas"]:
# # #                 if meta and "source_file" in meta:
# # #                     existing.add(meta["source_file"])
# # #         except Exception:
# # #             pass

# # #         for pdf_path in pdf_files:
# # #             if pdf_path.name in existing:
# # #                 continue
# # #             print(f"Indexing {pdf_path.name}...")
# # #             self._index_pdf(pdf_path)

# # #     def _index_pdf(self, pdf_path: Path):
# # #         """Extract, chunk, embed, and store a PDF."""
# # #         meta = self._get_pdf_metadata(pdf_path.name)
# # #         text = extract_text_from_pdf(pdf_path)
# # #         chunks = chunk_text(text)

# # #         # Batch embed (Fireworks has limits)
# # #         batch_size = 20
# # #         all_embeddings = []
# # #         for i in range(0, len(chunks), batch_size):
# # #             batch = chunks[i : i + batch_size]
# # #             embeddings = self.get_embedding(batch)
# # #             all_embeddings.extend(embeddings)

# # #         # Store in ChromaDB
# # #         ids = []
# # #         metadatas = []
# # #         for i, chunk in enumerate(chunks):
# # #             chunk_id = hashlib.md5(f"{pdf_path.name}_{i}".encode()).hexdigest()
# # #             ids.append(chunk_id)
# # #             metadatas.append({
# # #                 "source_file": pdf_path.name,
# # #                 "ticker": meta["ticker"],
# # #                 "fiscal_year": meta["fiscal_year"],
# # #                 "chunk_index": i,
# # #             })

# # #         self.collection.add(
# # #             ids=ids,
# # #             embeddings=all_embeddings,
# # #             documents=chunks,
# # #             metadatas=metadatas,
# # #         )
# # #         print(f"  Indexed {len(chunks)} chunks from {pdf_path.name}")

# # #     def query(self, question: str, ticker: Optional[str] = None, fiscal_year: Optional[str] = None) -> dict:
# # #         """Retrieve relevant chunks for a question."""
# # #         # Get query embedding
# # #         query_embedding = self.get_embedding([question])[0]

# # #         # Build filter
# # #         where = None
# # #         if ticker and fiscal_year:
# # #             where = {"$and": [{"ticker": ticker}, {"fiscal_year": fiscal_year}]}
# # #         elif ticker:
# # #             where = {"ticker": ticker}
# # #         elif fiscal_year:
# # #             where = {"fiscal_year": fiscal_year}

# # #         # Query ChromaDB
# # #         kwargs = {
# # #             "query_embeddings": [query_embedding],
# # #             "n_results": TOP_K,
# # #             "include": ["documents", "metadatas", "distances"],
# # #         }
# # #         if where:
# # #             kwargs["where"] = where

# # #         results = self.collection.query(**kwargs)

# # #         chunks = []
# # #         for i in range(len(results["documents"][0])):
# # #             chunks.append({
# # #                 "text": results["documents"][0][i],
# # #                 "metadata": results["metadatas"][0][i],
# # #                 "score": 1 - results["distances"][0][i],  # cosine similarity
# # #             })

# # #         return {
# # #             "success": True,
# # #             "chunks": chunks,
# # #             "count": len(chunks),
# # #         }

# # #     def format_results(self, chunks: list[dict]) -> str:
# # #         """Format retrieved chunks as readable context."""
# # #         if not chunks:
# # #             return "No relevant passages found."
# # #         parts = []
# # #         for i, chunk in enumerate(chunks, 1):
# # #             meta = chunk["metadata"]
# # #             source = f"{meta.get('ticker','?')} FY{meta.get('fiscal_year','?')} 10-K"
# # #             parts.append(f"[Source {i}: {source}]\n{chunk['text']}")
# # #         return "\n\n---\n\n".join(parts)

# # """
# # PDF RAG Tool - Embeds and retrieves from 10-K PDF filings using ChromaDB.
# # Supports section-aware chunking and filtering by 10-K section (Item).
# # """
# # import os
# # import re
# # import json
# # import hashlib
# # from pathlib import Path
# # from typing import Optional
# # import fireworks.client
# # import chromadb
# # from chromadb.config import Settings
# # import pdfplumber


# # CHUNK_SIZE = 1200      # characters per chunk (increased from 800)
# # CHUNK_OVERLAP = 300    # overlap between chunks (increased from 200)
# # TOP_K = 8              # number of chunks to retrieve (increased from 5)

# # # 10-K section header patterns — matches "Item 1.", "ITEM 1A.", "Item 7A", etc.
# # # Captures the canonical item label and a short title for metadata.
# # SECTION_PATTERNS = [
# #     (r"(?i)item\s+1(?:\.|\b)(?!\s*a\b)\s*(?:business)?", "Item 1 - Business"),
# #     (r"(?i)item\s+1a[\.\s]", "Item 1A - Risk Factors"),
# #     (r"(?i)item\s+1b[\.\s]", "Item 1B - Unresolved Staff Comments"),
# #     (r"(?i)item\s+1c[\.\s]", "Item 1C - Cybersecurity"),
# #     (r"(?i)item\s+2[\.\s]", "Item 2 - Properties"),
# #     (r"(?i)item\s+3[\.\s]", "Item 3 - Legal Proceedings"),
# #     (r"(?i)item\s+4[\.\s]", "Item 4 - Mine Safety"),
# #     (r"(?i)item\s+5[\.\s]", "Item 5 - Market for Registrant Equity"),
# #     (r"(?i)item\s+6[\.\s]", "Item 6 - Reserved"),
# #     (r"(?i)item\s+7(?:\.|\b)(?!\s*a\b)\s*", "Item 7 - MD&A"),
# #     (r"(?i)item\s+7a[\.\s]", "Item 7A - Quantitative Disclosures"),
# #     (r"(?i)item\s+8[\.\s]", "Item 8 - Financial Statements"),
# #     (r"(?i)item\s+9(?:\.|\b)(?!\s*a\b|b\b)\s*", "Item 9 - Disagreements with Accountants"),
# #     (r"(?i)item\s+9a[\.\s]", "Item 9A - Controls and Procedures"),
# #     (r"(?i)item\s+9b[\.\s]", "Item 9B - Other Information"),
# #     (r"(?i)item\s+10[\.\s]", "Item 10 - Directors and Officers"),
# #     (r"(?i)item\s+11[\.\s]", "Item 11 - Executive Compensation"),
# #     (r"(?i)item\s+12[\.\s]", "Item 12 - Security Ownership"),
# #     (r"(?i)item\s+13[\.\s]", "Item 13 - Certain Relationships"),
# #     (r"(?i)item\s+14[\.\s]", "Item 14 - Principal Accountant Fees"),
# #     (r"(?i)item\s+15[\.\s]", "Item 15 - Exhibits"),
# # ]

# # # Compiled once at module load for efficiency
# # _COMPILED_SECTION_PATTERNS = [
# #     (re.compile(pattern), label) for pattern, label in SECTION_PATTERNS
# # ]


# # def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
# #     """
# #     Extract text from a PDF page-by-page, including tables as structured text.
# #     Returns a list of dicts: {"page": int, "text": str}
# #     """
# #     pages = []
# #     with pdfplumber.open(str(pdf_path)) as pdf:
# #         for i, page in enumerate(pdf.pages, start=1):
# #             text = page.extract_text() or ""

# #             # Extract tables separately so financial figures aren't lost
# #             table_text = ""
# #             try:
# #                 tables = page.extract_tables()
# #                 for table in tables:
# #                     if not table:
# #                         continue
# #                     for row in table:
# #                         if not row:
# #                             continue
# #                         cleaned = [cell.strip() if cell else "" for cell in row]
# #                         # Skip rows that are entirely empty
# #                         if any(cleaned):
# #                             table_text += " | ".join(cleaned) + "\n"
# #             except Exception:
# #                 pass  # pdfplumber occasionally fails on malformed tables

# #             combined = text
# #             if table_text.strip():
# #                 combined += "\n[TABLE]\n" + table_text

# #             if combined.strip():
# #                 pages.append({"page": i, "text": combined.strip()})
# #     return pages


# # def detect_section(text: str) -> Optional[str]:
# #     """
# #     Return the 10-K section label if the text starts with a known Item header,
# #     otherwise None. Checks the first 120 characters to avoid false positives
# #     deep inside a paragraph.
# #     """
# #     header_zone = text[:120]
# #     for pattern, label in _COMPILED_SECTION_PATTERNS:
# #         if pattern.search(header_zone):
# #             return label
# #     return None


# # def chunk_text_with_sections(
# #     pages: list[dict],
# #     chunk_size: int = CHUNK_SIZE,
# #     overlap: int = CHUNK_OVERLAP,
# # ) -> list[dict]:
# #     """
# #     Split page-level text into overlapping chunks, tracking which 10-K
# #     section each chunk belongs to.

# #     Returns a list of dicts:
# #         {
# #             "text": str,
# #             "section": str,   # e.g. "Item 1A - Risk Factors"
# #             "start_page": int,
# #         }
# #     """
# #     # Concatenate pages, inserting a lightweight page boundary marker so we
# #     # can recover start_page for each chunk.
# #     PAGE_SEP = "\n\n"
# #     current_section = "Preamble"
# #     chunks = []

# #     # Build a flat list of (page_number, line) pairs for boundary-aware splitting
# #     lines: list[tuple[int, str]] = []
# #     for page_info in pages:
# #         for line in page_info["text"].splitlines():
# #             lines.append((page_info["page"], line))

# #     # Slide a character-count window over the lines
# #     buffer_text = ""
# #     buffer_page = lines[0][0] if lines else 1
# #     pending_section = current_section

# #     def flush_buffer(buf_text: str, buf_page: int, section: str) -> list[dict]:
# #         """Chunk a buffer string into fixed-size overlapping pieces."""
# #         result = []
# #         start = 0
# #         while start < len(buf_text):
# #             end = start + chunk_size
# #             piece = buf_text[start:end].strip()
# #             if piece:
# #                 result.append({
# #                     "text": piece,
# #                     "section": section,
# #                     "start_page": buf_page,
# #                 })
# #             start += chunk_size - overlap
# #         return result

# #     for page_num, line in lines:
# #         # Detect section transitions on any line
# #         detected = detect_section(line)
# #         if detected and detected != current_section:
# #             # Flush everything accumulated so far under the old section
# #             if buffer_text.strip():
# #                 chunks.extend(flush_buffer(buffer_text, buffer_page, current_section))
# #             # Start fresh for the new section
# #             current_section = detected
# #             buffer_text = line + "\n"
# #             buffer_page = page_num
# #         else:
# #             if not buffer_text:
# #                 buffer_page = page_num
# #             buffer_text += line + "\n"

# #     # Flush the final buffer
# #     if buffer_text.strip():
# #         chunks.extend(flush_buffer(buffer_text, buffer_page, current_section))

# #     return chunks


# # class PDFTool:
# #     def __init__(self, pdf_dir: Path, persist_dir: Path, ensure_indexed: bool = True):
# #         self.pdf_dir = pdf_dir
# #         self.persist_dir = persist_dir
# #         self.api_key = os.getenv("FIREWORKS_API_KEY")
# #         self.persist_dir.mkdir(parents=True, exist_ok=True)

# #         # Initialize Fireworks API client and ChromaDB
# #         self.client = fireworks.client.Fireworks(api_key=self.api_key)
# #         self.chroma_client = chromadb.PersistentClient(
# #             path=str(self.persist_dir),
# #             settings=Settings(anonymized_telemetry=False),
# #         )
# #         self.collection = self.chroma_client.get_or_create_collection(
# #             name="tenk_filings",
# #             metadata={"hnsw:space": "cosine"},
# #         )

# #         if ensure_indexed:
# #             self._ensure_indexed()

# #     def close(self) -> None:
# #         """Close the Fireworks client to release HTTP resources."""
# #         try:
# #             self.client.close()
# #         except Exception:
# #             pass

# #     def get_embedding(self, texts: list[str]) -> list[list[float]]:
# #         """Get embeddings from Fireworks API."""
# #         response = self.client.embeddings.create(
# #             model="nomic-ai/nomic-embed-text-v1.5",
# #             input=texts,
# #         )
# #         return [item.embedding for item in response.data]

# #     def _get_pdf_metadata(self, filename: str) -> dict:
# #         """Parse ticker and fiscal year from filename like AAPL_FY2024_10-K.pdf"""
# #         match = re.match(r"([A-Z]+)_FY(\d{4})_10-K\.pdf", filename)
# #         if match:
# #             return {"ticker": match.group(1), "fiscal_year": match.group(2)}
# #         return {"ticker": "UNKNOWN", "fiscal_year": "UNKNOWN"}

# #     def _file_hash(self, pdf_path: Path) -> str:
# #         """MD5 of the PDF file — used to detect re-indexing needs."""
# #         h = hashlib.md5()
# #         with open(pdf_path, "rb") as f:
# #             for block in iter(lambda: f.read(65536), b""):
# #                 h.update(block)
# #         return h.hexdigest()

# #     def _ensure_indexed(self):
# #         """Index all PDFs not yet present (or changed) in ChromaDB."""
# #         pdf_files = list(self.pdf_dir.glob("*.pdf"))
# #         if not pdf_files:
# #             print("Warning: No PDFs found in", self.pdf_dir)
# #             return

# #         # Build a map of filename -> file_hash for already-indexed chunks
# #         existing: dict[str, str] = {}  # filename -> stored file_hash
# #         try:
# #             results = self.collection.get(include=["metadatas"])
# #             for meta in results["metadatas"]:
# #                 if meta and "source_file" in meta:
# #                     fname = meta["source_file"]
# #                     fhash = meta.get("file_hash", "")
# #                     existing[fname] = fhash
# #         except Exception:
# #             pass

# #         for pdf_path in pdf_files:
# #             current_hash = self._file_hash(pdf_path)
# #             if existing.get(pdf_path.name) == current_hash:
# #                 continue  # already indexed and unchanged
# #             if pdf_path.name in existing:
# #                 print(f"Re-indexing changed file {pdf_path.name}...")
# #                 self._delete_pdf_chunks(pdf_path.name)
# #             else:
# #                 print(f"Indexing {pdf_path.name}...")
# #             self._index_pdf(pdf_path, current_hash)

# #     def _delete_pdf_chunks(self, filename: str):
# #         """Remove all chunks belonging to a given source file."""
# #         self.collection.delete(where={"source_file": filename})

# #     def reindex_all(self):
# #         """
# #         Drop and rebuild the entire collection from scratch.
# #         Call this once after any change to extraction or chunking logic,
# #         since the content-hash check won't detect code-level changes.
# #         """
# #         self.chroma_client.delete_collection("tenk_filings")
# #         self.collection = self.chroma_client.get_or_create_collection(
# #             name="tenk_filings",
# #             metadata={"hnsw:space": "cosine"},
# #         )
# #         self._ensure_indexed()

# #     def _index_pdf(self, pdf_path: Path, file_hash: str):
# #         """Extract, chunk (section-aware), embed, and store a PDF."""
# #         meta = self._get_pdf_metadata(pdf_path.name)
# #         pages = extract_text_from_pdf(pdf_path)
# #         chunks = chunk_text_with_sections(pages)

# #         batch_size = 20
# #         texts = [c["text"] for c in chunks]
# #         all_embeddings = []
# #         for i in range(0, len(texts), batch_size):
# #             batch = texts[i: i + batch_size]
# #             embeddings = self.get_embedding(batch)
# #             all_embeddings.extend(embeddings)

# #         ids = []
# #         metadatas = []
# #         for i, chunk in enumerate(chunks):
# #             chunk_id = hashlib.md5(f"{pdf_path.name}_{i}".encode()).hexdigest()
# #             ids.append(chunk_id)
# #             metadatas.append({
# #                 "source_file": pdf_path.name,
# #                 "ticker": meta["ticker"],
# #                 "fiscal_year": meta["fiscal_year"],
# #                 "file_hash": file_hash,
# #                 "section": chunk["section"],       # NEW: e.g. "Item 1A - Risk Factors"
# #                 "start_page": chunk["start_page"], # NEW: page number in PDF
# #                 "chunk_index": i,
# #             })

# #         self.collection.add(
# #             ids=ids,
# #             embeddings=all_embeddings,
# #             documents=texts,
# #             metadatas=metadatas,
# #         )
# #         section_counts = {}
# #         for c in chunks:
# #             section_counts[c["section"]] = section_counts.get(c["section"], 0) + 1
# #         print(f"  Indexed {len(chunks)} chunks from {pdf_path.name}")
# #         for sec, count in sorted(section_counts.items()):
# #             print(f"    {sec}: {count} chunks")

# #     def query(
# #         self,
# #         question: str,
# #         ticker: Optional[str] = None,
# #         fiscal_year: Optional[str] = None,
# #         section: Optional[str] = None,  # NEW: e.g. "Item 1A - Risk Factors"
# #     ) -> dict:
# #         """
# #         Retrieve relevant chunks for a question.

# #         Args:
# #             question:     Natural-language query.
# #             ticker:       Filter to a specific company, e.g. "AAPL".
# #             fiscal_year:  Filter to a specific year, e.g. "2024".
# #             section:      Filter to a specific 10-K section label.
# #                           Pass the exact label or a substring — matching
# #                           is done with a $contains filter.
# #         """
# #         query_embedding = self.get_embedding([question])[0]

# #         # Build a ChromaDB $and filter from whichever dimensions are specified
# #         conditions = []
# #         if ticker:
# #             conditions.append({"ticker": ticker})
# #         if fiscal_year:
# #             conditions.append({"fiscal_year": fiscal_year})
# #         if section:
# #             # Allow partial match, e.g. "Risk Factors" matches "Item 1A - Risk Factors"
# #             conditions.append({"section": {"$contains": section}})

# #         where = None
# #         if len(conditions) == 1:
# #             where = conditions[0]
# #         elif len(conditions) > 1:
# #             where = {"$and": conditions}

# #         kwargs = {
# #             "query_embeddings": [query_embedding],
# #             "n_results": TOP_K,
# #             "include": ["documents", "metadatas", "distances"],
# #         }
# #         if where:
# #             kwargs["where"] = where

# #         results = self.collection.query(**kwargs)

# #         chunks = []
# #         for i in range(len(results["documents"][0])):
# #             chunks.append({
# #                 "text": results["documents"][0][i],
# #                 "metadata": results["metadatas"][0][i],
# #                 "score": 1 - results["distances"][0][i],
# #             })

# #         return {
# #             "success": True,
# #             "chunks": chunks,
# #             "count": len(chunks),
# #         }

# #     def format_results(self, chunks: list[dict]) -> str:
# #         """Format retrieved chunks as readable context, including section info."""
# #         if not chunks:
# #             return "No relevant passages found."
# #         parts = []
# #         for i, chunk in enumerate(chunks, 1):
# #             meta = chunk["metadata"]
# #             source = (
# #                 f"{meta.get('ticker','?')} FY{meta.get('fiscal_year','?')} 10-K"
# #                 f" | {meta.get('section', 'Unknown Section')}"
# #                 f" | p.{meta.get('start_page', '?')}"
# #             )
# #             parts.append(f"[Source {i}: {source}]\n{chunk['text']}")
# #         return "\n\n---\n\n".join(parts)

# #     def list_sections(self, ticker: Optional[str] = None, fiscal_year: Optional[str] = None) -> list[str]:
# #         """
# #         Return all unique section labels present in the collection,
# #         optionally filtered by ticker and/or fiscal year.
# #         Useful for discovering what's indexed before querying.
# #         """
# #         where = None
# #         conditions = []
# #         if ticker:
# #             conditions.append({"ticker": ticker})
# #         if fiscal_year:
# #             conditions.append({"fiscal_year": fiscal_year})
# #         if len(conditions) == 1:
# #             where = conditions[0]
# #         elif len(conditions) > 1:
# #             where = {"$and": conditions}

# #         kwargs = {"include": ["metadatas"]}
# #         if where:
# #             kwargs["where"] = where

# #         results = self.collection.get(**kwargs)
# #         sections = sorted({
# #             meta.get("section", "Unknown")
# #             for meta in results["metadatas"]
# #             if meta
# #         })
# #         return sections


# # import os
# # import re
# # import hashlib
# # from pathlib import Path
# # from typing import Optional
# # import fireworks.client
# # import chromadb
# # from chromadb.config import Settings
# # import pdfplumber

# # CHUNK_SIZE = 1200
# # CHUNK_OVERLAP = 200
# # TOP_K = 8

# # SECTION_PATTERNS = [
# #     (r"(?i)item\s+1(?:\.|\b)(?!\s*a\b)\s*(?:business)?", ("1", "Business")),
# #     (r"(?i)item\s+1a[\.\s]", ("1A", "Risk Factors")),
# #     (r"(?i)item\s+1b[\.\s]", ("1B", "Unresolved Staff Comments")),
# #     (r"(?i)item\s+1c[\.\s]", ("1C", "Cybersecurity")),
# #     (r"(?i)item\s+2[\.\s]", ("2", "Properties")),
# #     (r"(?i)item\s+3[\.\s]", ("3", "Legal Proceedings")),
# #     (r"(?i)item\s+4[\.\s]", ("4", "Mine Safety")),
# #     (r"(?i)item\s+5[\.\s]", ("5", "Market for Registrant Equity")),
# #     (r"(?i)item\s+6[\.\s]", ("6", "Reserved")),
# #     (r"(?i)item\s+7(?:\.|\b)(?!\s*a\b)\s*", ("7", "MD&A")),
# #     (r"(?i)item\s+7a[\.\s]", ("7A", "Quantitative Disclosures")),
# #     (r"(?i)item\s+8[\.\s]", ("8", "Financial Statements")),
# #     (r"(?i)item\s+9(?:\.|\b)(?!\s*a\b|b\b)\s*", ("9", "Disagreements with Accountants")),
# #     (r"(?i)item\s+9a[\.\s]", ("9A", "Controls and Procedures")),
# #     (r"(?i)item\s+9b[\.\s]", ("9B", "Other Information")),
# #     (r"(?i)item\s+10[\.\s]", ("10", "Directors and Officers")),
# #     (r"(?i)item\s+11[\.\s]", ("11", "Executive Compensation")),
# #     (r"(?i)item\s+12[\.\s]", ("12", "Security Ownership")),
# #     (r"(?i)item\s+13[\.\s]", ("13", "Certain Relationships")),
# #     (r"(?i)item\s+14[\.\s]", ("14", "Principal Accountant Fees")),
# #     (r"(?i)item\s+15[\.\s]", ("15", "Exhibits")),
# # ]

# # _COMPILED_SECTION_PATTERNS = [(re.compile(p), code, title) for p, (code, title) in SECTION_PATTERNS]


# # def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
# #     pages = []
# #     with pdfplumber.open(str(pdf_path)) as pdf:
# #         for i, page in enumerate(pdf.pages, start=1):
# #             text = page.extract_text() or ""
# #             tables = []
# #             try:
# #                 tables = page.extract_tables() or []
# #             except Exception:
# #                 tables = []
# #             pages.append({"page": i, "text": text.strip(), "tables": tables})
# #     return pages


# # def detect_section(text: str) -> Optional[dict]:
# #     header_zone = text[:140]
# #     for pattern, code, title in _COMPILED_SECTION_PATTERNS:
# #         if pattern.search(header_zone):
# #             return {"section_code": code, "section_title": title}
# #     return None


# # def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
# #     chunks = []
# #     start = 0
# #     while start < len(text):
# #         piece = text[start:start + chunk_size].strip()
# #         if piece:
# #             chunks.append(piece)
# #         start += max(1, chunk_size - overlap)
# #     return chunks


# # def table_to_text(table: list[list[str]]) -> str:
# #     rows = []
# #     for row in table:
# #         if not row:
# #             continue
# #         cleaned = [cell.strip() if cell else "" for cell in row]
# #         if any(cleaned):
# #             rows.append(" | ".join(cleaned))
# #     return "\n".join(rows).strip()


# # class PDFTool:
# #     def __init__(self, pdf_dir: Path, persist_dir: Path, ensure_indexed: bool = True):
# #         self.pdf_dir = pdf_dir
# #         self.persist_dir = persist_dir
# #         self.api_key = os.getenv("FIREWORKS_API_KEY")
# #         self.persist_dir.mkdir(parents=True, exist_ok=True)

# #         self.client = fireworks.client.Fireworks(api_key=self.api_key)
# #         self.chroma_client = chromadb.PersistentClient(
# #             path=str(self.persist_dir),
# #             settings=Settings(anonymized_telemetry=False),
# #         )
# #         self.collection = self.chroma_client.get_or_create_collection(
# #             name="tenk_filings",
# #             metadata={"hnsw:space": "cosine"},
# #         )

# #         if ensure_indexed:
# #             self._ensure_indexed()

# #     def close(self) -> None:
# #         try:
# #             self.client.close()
# #         except Exception:
# #             pass

# #     def get_embedding(self, texts: list[str]) -> list[list[float]]:
# #         response = self.client.embeddings.create(
# #             model="nomic-ai/nomic-embed-text-v1.5",
# #             input=texts,
# #         )
# #         return [item.embedding for item in response.data]

# #     def _get_pdf_metadata(self, filename: str) -> dict:
# #         match = re.match(r"([A-Z]+)_FY(\d{4})_10-K\.pdf", filename)
# #         if match:
# #             return {"ticker": match.group(1), "fiscal_year": match.group(2)}
# #         return {"ticker": "UNKNOWN", "fiscal_year": "UNKNOWN"}

# #     def _file_hash(self, pdf_path: Path) -> str:
# #         h = hashlib.md5()
# #         with open(pdf_path, "rb") as f:
# #             for block in iter(lambda: f.read(65536), b""):
# #                 h.update(block)
# #         return h.hexdigest()

# #     def _ensure_indexed(self):
# #         pdf_files = list(self.pdf_dir.glob("*.pdf"))
# #         if not pdf_files:
# #             print("Warning: No PDFs found in", self.pdf_dir)
# #             return

# #         existing = {}
# #         try:
# #             results = self.collection.get(include=["metadatas"])
# #             for meta in results["metadatas"]:
# #                 if meta and "source_file" in meta:
# #                     existing[meta["source_file"]] = meta.get("file_hash", "")
# #         except Exception:
# #             pass

# #         for pdf_path in pdf_files:
# #             current_hash = self._file_hash(pdf_path)
# #             if existing.get(pdf_path.name) == current_hash:
# #                 continue
# #             if pdf_path.name in existing:
# #                 self._delete_pdf_chunks(pdf_path.name)
# #             self._index_pdf(pdf_path, current_hash)

# #     def _delete_pdf_chunks(self, filename: str):
# #         self.collection.delete(where={"source_file": filename})

# #     def reindex_all(self):
# #         self.chroma_client.delete_collection("tenk_filings")
# #         self.collection = self.chroma_client.get_or_create_collection(
# #             name="tenk_filings",
# #             metadata={"hnsw:space": "cosine"},
# #         )
# #         self._ensure_indexed()

# #     def _index_pdf(self, pdf_path: Path, file_hash: str):
# #         meta = self._get_pdf_metadata(pdf_path.name)
# #         pages = extract_text_from_pdf(pdf_path)

# #         texts = []
# #         metadatas = []
# #         ids = []

# #         current_section = {"section_code": "Preamble", "section_title": "Preamble"}

# #         for page in pages:
# #             if page["text"]:
# #                 lines = page["text"].splitlines()
# #                 page_section = current_section
# #                 for line in lines[:5]:
# #                     detected = detect_section(line)
# #                     if detected:
# #                         page_section = detected
# #                         current_section = detected
# #                         break

# #                 narrative_chunks = chunk_text(page["text"])
# #                 for j, chunk in enumerate(narrative_chunks):
# #                     texts.append(chunk)
# #                     ids.append(hashlib.md5(f"{pdf_path.name}_p{page['page']}_n{j}".encode()).hexdigest())
# #                     metadatas.append({
# #                         "source_file": pdf_path.name,
# #                         "file_hash": file_hash,
# #                         "ticker": meta["ticker"],
# #                         "fiscal_year": meta["fiscal_year"],
# #                         "chunk_type": "narrative",
# #                         "section_code": page_section["section_code"],
# #                         "section_title": page_section["section_title"],
# #                         "page_start": page["page"],
# #                         "page_end": page["page"],
# #                         "chunk_index": j,
# #                     })

# #             for t_idx, table in enumerate(page["tables"]):
# #                 table_text = table_to_text(table)
# #                 if not table_text:
# #                     continue
# #                 table_chunks = chunk_text(table_text, chunk_size=900, overlap=0)
# #                 for r_idx, tchunk in enumerate(table_chunks):
# #                     texts.append(tchunk)
# #                     ids.append(hashlib.md5(f"{pdf_path.name}_p{page['page']}_t{t_idx}_{r_idx}".encode()).hexdigest())
# #                     metadatas.append({
# #                         "source_file": pdf_path.name,
# #                         "file_hash": file_hash,
# #                         "ticker": meta["ticker"],
# #                         "fiscal_year": meta["fiscal_year"],
# #                         "chunk_type": "table_row" if len(table_chunks) > 1 else "table",
# #                         "section_code": current_section["section_code"],
# #                         "section_title": current_section["section_title"],
# #                         "page_start": page["page"],
# #                         "page_end": page["page"],
# #                         "table_index": t_idx,
# #                         "chunk_index": r_idx,
# #                     })

# #         if texts:
# #             all_embeddings = []
# #             batch_size = 20
# #             for i in range(0, len(texts), batch_size):
# #                 all_embeddings.extend(self.get_embedding(texts[i:i + batch_size]))

# #             self.collection.add(
# #                 ids=ids,
# #                 embeddings=all_embeddings,
# #                 documents=texts,
# #                 metadatas=metadatas,
# #             )

# #     def query(self, question: str, ticker: Optional[str] = None, fiscal_year: Optional[str] = None, section_code: Optional[str] = None, chunk_type: Optional[str] = None) -> dict:
# #         query_embedding = self.get_embedding([question])[0]
# #         conditions = []
# #         if ticker:
# #             conditions.append({"ticker": ticker})
# #         if fiscal_year:
# #             conditions.append({"fiscal_year": fiscal_year})
# #         if section_code:
# #             conditions.append({"section_code": section_code})
# #         if chunk_type:
# #             conditions.append({"chunk_type": chunk_type})

# #         where = None
# #         if len(conditions) == 1:
# #             where = conditions[0]
# #         elif len(conditions) > 1:
# #             where = {"$and": conditions}

# #         kwargs = {
# #             "query_embeddings": [query_embedding],
# #             "n_results": TOP_K,
# #             "include": ["documents", "metadatas", "distances"],
# #         }
# #         if where:
# #             kwargs["where"] = where

# #         results = self.collection.query(**kwargs)
# #         chunks = []
# #         for i in range(len(results["documents"][0])):
# #             chunks.append({
# #                 "text": results["documents"][0][i],
# #                 "metadata": results["metadatas"][0][i],
# #                 "score": 1 - results["distances"][0][i],
# #             })
# #         return {"success": True, "chunks": chunks, "count": len(chunks)}

# #     def format_results(self, chunks: list[dict]) -> str:
# #         if not chunks:
# #             return "No relevant passages found."
# #         parts = []
# #         for i, chunk in enumerate(chunks, 1):
# #             meta = chunk["metadata"]
# #             source = f"{meta.get('ticker','?')} FY{meta.get('fiscal_year','?')} 10-K | Item {meta.get('section_code','?')} | p.{meta.get('page_start','?')}"
# #             parts.append(f"[Source {i}: {source}]\n{chunk['text']}")
# #         return "\n\n---\n\n".join(parts)

# #     def list_sections(self, ticker: Optional[str] = None, fiscal_year: Optional[str] = None) -> list[str]:
# #         where = None
# #         conditions = []
# #         if ticker:
# #             conditions.append({"ticker": ticker})
# #         if fiscal_year:
# #             conditions.append({"fiscal_year": fiscal_year})
# #         if len(conditions) == 1:
# #             where = conditions[0]
# #         elif len(conditions) > 1:
# #             where = {"$and": conditions}

# #         kwargs = {"include": ["metadatas"]}
# #         if where:
# #             kwargs["where"] = where

# #         results = self.collection.get(**kwargs)
# #         return sorted({m.get("section_code", "Unknown") for m in results["metadatas"] if m})

# # import os
# # import re
# # import hashlib
# # from pathlib import Path
# # from typing import Optional

# # import fireworks.client
# # import chromadb
# # from chromadb.config import Settings
# # import pdfplumber

# # CHUNK_SIZE = 1200
# # CHUNK_OVERLAP = 300
# # TOP_K = 8

# # SECTION_PATTERNS = [
# #     (r"(?i)item\s+1(?:\.|\b)(?!\s*a\b)\s*(?:business)?", ("1", "Business")),
# #     (r"(?i)item\s+1a[\.\s]", ("1A", "Risk Factors")),
# #     (r"(?i)item\s+7(?:\.|\b)(?!\s*a\b)\s*", ("7", "MD&A")),
# #     (r"(?i)item\s+8[\.\s]", ("8", "Financial Statements")),
# # ]

# # _COMPILED_SECTION_PATTERNS = [(re.compile(p), code, title) for p, (code, title) in SECTION_PATTERNS]

# # def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
# #     pages = []
# #     with pdfplumber.open(str(pdf_path)) as pdf:
# #         for i, page in enumerate(pdf.pages, start=1):
# #             text = page.extract_text() or ""
# #             tables = []
# #             try:
# #                 tables = page.extract_tables() or []
# #             except Exception:
# #                 tables = []
# #             pages.append({"page": i, "text": text.strip(), "tables": tables})
# #     return pages

# # def detect_section(text: str) -> Optional[dict]:
# #     header_zone = text[:140]
# #     for pattern, code, title in _COMPILED_SECTION_PATTERNS:
# #         if pattern.search(header_zone):
# #             return {"section_code": code, "section_title": title}
# #     return None

# # def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
# #     chunks = []
# #     start = 0
# #     while start < len(text):
# #         piece = text[start:start + chunk_size].strip()
# #         if piece:
# #             chunks.append(piece)
# #         start += max(1, chunk_size - overlap)
# #     return chunks

# # def table_to_text(table: list[list[str]]) -> str:
# #     rows = []
# #     for row in table:
# #         if not row:
# #             continue
# #         cleaned = [cell.strip() if cell else "" for cell in row]
# #         if any(cleaned):
# #             rows.append(" | ".join(cleaned))
# #     return "\n".join(rows).strip()

# # class PDFTool:
# #     def __init__(self, pdf_dir: Path, persist_dir: Path, ensure_indexed: bool = True):
# #         self.pdf_dir = pdf_dir
# #         self.persist_dir = persist_dir
# #         self.api_key = os.getenv("FIREWORKS_API_KEY")
# #         self.persist_dir.mkdir(parents=True, exist_ok=True)

# #         self.client = fireworks.client.Fireworks(api_key=self.api_key)
# #         self.chroma_client = chromadb.PersistentClient(
# #             path=str(self.persist_dir),
# #             settings=Settings(anonymized_telemetry=False),
# #         )
# #         self.collection = self.chroma_client.get_or_create_collection(
# #             name="tenk_filings",
# #             metadata={"hnsw:space": "cosine"},
# #         )

# #         if ensure_indexed:
# #             self._ensure_indexed()

# #     def close(self) -> None:
# #         try:
# #             self.client.close()
# #         except Exception:
# #             pass

# #     def get_embedding(self, texts: list[str]) -> list[list[float]]:
# #         response = self.client.embeddings.create(
# #             model="nomic-ai/nomic-embed-text-v1.5",
# #             input=texts,
# #         )
# #         return [item.embedding for item in response.data]

# #     def _get_pdf_metadata(self, filename: str) -> dict:
# #         match = re.match(r"([A-Z]+)_FY(\d{4})_10-K\.pdf", filename)
# #         if match:
# #             return {"ticker": match.group(1), "fiscal_year": match.group(2)}
# #         return {"ticker": "UNKNOWN", "fiscal_year": "UNKNOWN"}

# #     def _file_hash(self, pdf_path: Path) -> str:
# #         h = hashlib.md5()
# #         with open(pdf_path, "rb") as f:
# #             for block in iter(lambda: f.read(65536), b""):
# #                 h.update(block)
# #         return h.hexdigest()

# #     def _ensure_indexed(self):
# #         pdf_files = list(self.pdf_dir.glob("*.pdf"))
# #         if not pdf_files:
# #             return

# #         existing = {}
# #         try:
# #             results = self.collection.get(include=["metadatas"])
# #             for meta in results["metadatas"]:
# #                 if meta and "source_file" in meta:
# #                     existing[meta["source_file"]] = meta.get("file_hash", "")
# #         except Exception:
# #             pass

# #         for pdf_path in pdf_files:
# #             current_hash = self._file_hash(pdf_path)
# #             if existing.get(pdf_path.name) == current_hash:
# #                 continue
# #             if pdf_path.name in existing:
# #                 self.collection.delete(where={"source_file": pdf_path.name})
# #             self._index_pdf(pdf_path, current_hash)

# #     def _index_pdf(self, pdf_path: Path, file_hash: str):
# #         meta = self._get_pdf_metadata(pdf_path.name)
# #         pages = extract_text_from_pdf(pdf_path)

# #         texts = []
# #         metadatas = []
# #         ids = []

# #         current_section = {"section_code": "Preamble", "section_title": "Preamble"}

# #         for page in pages:
# #             if page["text"]:
# #                 detected = None
# #                 for line in page["text"].splitlines()[:5]:
# #                     detected = detect_section(line)
# #                     if detected:
# #                         current_section = detected
# #                         break

# #                 narrative_chunks = chunk_text(page["text"])
# #                 for j, chunk in enumerate(narrative_chunks):
# #                     texts.append(chunk)
# #                     ids.append(hashlib.md5(f"{pdf_path.name}_p{page['page']}_n{j}".encode()).hexdigest())
# #                     metadatas.append({
# #                         "source_file": pdf_path.name,
# #                         "file_hash": file_hash,
# #                         "ticker": meta["ticker"],
# #                         "fiscal_year": meta["fiscal_year"],
# #                         "chunk_type": "narrative",
# #                         "section": current_section["section_title"],
# #                         "section_code": current_section["section_code"],
# #                         "page_start": page["page"],
# #                         "page_end": page["page"],
# #                         "chunk_index": j,
# #                     })

# #             for t_idx, table in enumerate(page["tables"]):
# #                 table_text = table_to_text(table)
# #                 if not table_text:
# #                     continue
# #                 table_chunks = chunk_text(table_text, chunk_size=900, overlap=0)
# #                 for r_idx, tchunk in enumerate(table_chunks):
# #                     texts.append(tchunk)
# #                     ids.append(hashlib.md5(f"{pdf_path.name}_p{page['page']}_t{t_idx}_{r_idx}".encode()).hexdigest())
# #                     metadatas.append({
# #                         "source_file": pdf_path.name,
# #                         "file_hash": file_hash,
# #                         "ticker": meta["ticker"],
# #                         "fiscal_year": meta["fiscal_year"],
# #                         "chunk_type": "table_row" if len(table_chunks) > 1 else "table",
# #                         "section": current_section["section_title"],
# #                         "section_code": current_section["section_code"],
# #                         "page_start": page["page"],
# #                         "page_end": page["page"],
# #                         "table_index": t_idx,
# #                         "chunk_index": r_idx,
# #                     })

# #         if texts:
# #             all_embeddings = []
# #             batch_size = 20
# #             for i in range(0, len(texts), batch_size):
# #                 all_embeddings.extend(self.get_embedding(texts[i:i + batch_size]))

# #             self.collection.add(
# #                 ids=ids,
# #                 embeddings=all_embeddings,
# #                 documents=texts,
# #                 metadatas=metadatas,
# #             )

# #     def query(self, question: str, ticker: Optional[str] = None, fiscal_year: Optional[str] = None, section: Optional[str] = None) -> dict:
# #         query_embedding = self.get_embedding([question])[0]
# #         conditions = []
# #         if ticker:
# #             conditions.append({"ticker": ticker})
# #         if fiscal_year:
# #             conditions.append({"fiscal_year": fiscal_year})
# #         if section:
# #             conditions.append({"section": {"$contains": section}})

# #         where = None
# #         if len(conditions) == 1:
# #             where = conditions[0]
# #         elif len(conditions) > 1:
# #             where = {"$and": conditions}

# #         kwargs = {
# #             "query_embeddings": [query_embedding],
# #             "n_results": TOP_K,
# #             "include": ["documents", "metadatas", "distances"],
# #         }
# #         if where:
# #             kwargs["where"] = where

# #         results = self.collection.query(**kwargs)
# #         chunks = []
# #         for i in range(len(results["documents"][0])):
# #             chunks.append({
# #                 "text": results["documents"][0][i],
# #                 "metadata": results["metadatas"][0][i],
# #                 "score": 1 - results["distances"][0][i],
# #             })
# #         return {"success": True, "chunks": chunks, "count": len(chunks)}

# #     def format_results(self, chunks: list[dict]) -> str:
# #         if not chunks:
# #             return "No relevant passages found."
# #         parts = []
# #         for i, chunk in enumerate(chunks, 1):
# #             meta = chunk["metadata"]
# #             source = f"{meta.get('ticker','?')} FY{meta.get('fiscal_year','?')} 10-K | Item {meta.get('section_code','?')} | p.{meta.get('page_start','?')}"
# #             parts.append(f"[Source {i}: {source}]\n{chunk['text']}")
# #         return "\n\n---\n\n".join(parts)

# #     def list_sections(self, ticker: Optional[str] = None, fiscal_year: Optional[str] = None) -> list[str]:
# #         where = None
# #         conditions = []
# #         if ticker:
# #             conditions.append({"ticker": ticker})
# #         if fiscal_year:
# #             conditions.append({"fiscal_year": fiscal_year})
# #         if len(conditions) == 1:
# #             where = conditions[0]
# #         elif len(conditions) > 1:
# #             where = {"$and": conditions}

# #         kwargs = {"include": ["metadatas"]}
# #         if where:
# #             kwargs["where"] = where

# #         results = self.collection.get(**kwargs)
# #         return sorted({m.get("section_code", "Unknown") for m in results["metadatas"] if m})


import os
import re
import hashlib
from pathlib import Path
from typing import Optional

import fireworks.client
import chromadb
from chromadb.config import Settings
import pdfplumber

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 300
TOP_K = 8
INDEX_VERSION = "2"

# Most-specific patterns first; anchored to line start to avoid false positives.
_SECTION_SPECS = [
    ("1A", "Risk Factors", r"(?i)^item\s+1a[\.\s\-]"),
    ("1B", "Unresolved Staff Comments", r"(?i)^item\s+1b[\.\s\-]"),
    ("1C", "Cybersecurity", r"(?i)^item\s+1c[\.\s\-]"),
    ("7A", "Quantitative Disclosures", r"(?i)^item\s+7a[\.\s\-]"),
    ("9A", "Controls and Procedures", r"(?i)^item\s+9a[\.\s\-]"),
    ("9B", "Other Information", r"(?i)^item\s+9b[\.\s\-]"),
    ("10", "Directors and Officers", r"(?i)^item\s+10[\.\s\-]"),
    ("11", "Executive Compensation", r"(?i)^item\s+11[\.\s\-]"),
    ("12", "Security Ownership", r"(?i)^item\s+12[\.\s\-]"),
    ("13", "Certain Relationships", r"(?i)^item\s+13[\.\s\-]"),
    ("14", "Principal Accountant Fees", r"(?i)^item\s+14[\.\s\-]"),
    ("15", "Exhibits", r"(?i)^item\s+15[\.\s\-]"),
    ("1", "Business", r"(?i)^item\s+1(?:[\.\s\-]|$)"),
    ("2", "Properties", r"(?i)^item\s+2[\.\s\-]"),
    ("3", "Legal Proceedings", r"(?i)^item\s+3[\.\s\-]"),
    ("4", "Mine Safety", r"(?i)^item\s+4[\.\s\-]"),
    ("5", "Market for Registrant Equity", r"(?i)^item\s+5[\.\s\-]"),
    ("6", "Reserved", r"(?i)^item\s+6[\.\s\-]"),
    ("7", "MD&A", r"(?i)^item\s+7(?:[\.\s\-]|$)"),
    ("8", "Financial Statements", r"(?i)^item\s+8[\.\s\-]"),
    ("9", "Disagreements with Accountants", r"(?i)^item\s+9(?:[\.\s\-]|$)"),
]

_COMPILED_SECTION_PATTERNS = [
    (re.compile(pattern), code, title) for code, title, pattern in _SECTION_SPECS
]


def _detect_section_line(line: str) -> Optional[dict]:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return None
    for pattern, code, title in _COMPILED_SECTION_PATTERNS:
        if pattern.match(stripped):
            return {"section_code": code, "section_title": title}
    return None


def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            pages.append({"page": i, "text": text.strip(), "tables": tables})
    return pages


def detect_section(text: str) -> Optional[str]:
    """Return a section label if text begins with a known Item header."""
    for line in text.splitlines()[:5]:
        detected = _detect_section_line(line)
        if detected:
            code = detected["section_code"]
            title = detected["section_title"]
            return f"Item {code} - {title}"
    return None


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        piece = text[start:start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        start += max(1, chunk_size - overlap)
    return chunks


def chunk_text_with_sections(
    pages: list[dict],
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """Split pages into chunks while tracking 10-K section boundaries line-by-line."""
    current_section = {"section_code": "Preamble", "section_title": "Preamble"}
    chunks: list[dict] = []
    buffer_text = ""
    buffer_page = pages[0]["page"] if pages else 1

    def flush_buffer(buf_text: str, buf_page: int, section: dict) -> None:
        for chunk_index, piece in enumerate(chunk_text(buf_text, chunk_size, overlap)):
            chunks.append({
                "text": piece,
                "section": f"Item {section['section_code']} - {section['section_title']}",
                "section_code": section["section_code"],
                "section_title": section["section_title"],
                "start_page": buf_page,
                "chunk_index": chunk_index,
            })

    for page_info in pages:
        for line in page_info["text"].splitlines():
            detected = _detect_section_line(line)
            if detected and detected["section_code"] != current_section["section_code"]:
                if buffer_text.strip():
                    flush_buffer(buffer_text, buffer_page, current_section)
                current_section = detected
                buffer_text = line + "\n"
                buffer_page = page_info["page"]
            else:
                if not buffer_text:
                    buffer_page = page_info["page"]
                buffer_text += line + "\n"

    if buffer_text.strip():
        flush_buffer(buffer_text, buffer_page, current_section)

    return chunks

def table_to_text(table: list[list[str]]) -> str:
    rows = []
    for row in table:
        if not row:
            continue
        cleaned = [cell.strip() if cell else "" for cell in row]
        if any(cleaned):
            rows.append(" | ".join(cleaned))
    return "\n".join(rows).strip()

class PDFTool:
    def __init__(self, pdf_dir: Path, persist_dir: Path, ensure_indexed: bool = True):
        self.pdf_dir = pdf_dir
        self.persist_dir = persist_dir
        self.api_key = os.getenv("FIREWORKS_API_KEY")
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = fireworks.client.Fireworks(api_key=self.api_key)
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="tenk_filings",
            metadata={"hnsw:space": "cosine"},
        )

        if ensure_indexed:
            self._ensure_indexed()

    def reindex_all(self) -> None:
        try:
            self.chroma_client.delete_collection("tenk_filings")
        except Exception:
            pass
        self.collection = self.chroma_client.get_or_create_collection(
            name="tenk_filings",
            metadata={"hnsw:space": "cosine", "index_version": INDEX_VERSION},
        )
        pdf_files = list(self.pdf_dir.glob("*.pdf"))
        for pdf_path in pdf_files:
            self._index_pdf(pdf_path, self._file_hash(pdf_path))

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def get_embedding(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model="nomic-ai/nomic-embed-text-v1.5",
            input=texts,
        )
        return [item.embedding for item in response.data]

    def _get_pdf_metadata(self, filename: str) -> dict:
        match = re.match(r"([A-Z]+)_FY(\d{4})_10-K\.pdf", filename)
        if match:
            return {"ticker": match.group(1), "fiscal_year": match.group(2)}
        return {"ticker": "UNKNOWN", "fiscal_year": "UNKNOWN"}

    def _file_hash(self, pdf_path: Path) -> str:
        h = hashlib.md5()
        with open(pdf_path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()

    def _ensure_indexed(self):
        pdf_files = list(self.pdf_dir.glob("*.pdf"))
        if not pdf_files:
            return

        stored_version = (self.collection.metadata or {}).get("index_version")
        if stored_version != INDEX_VERSION:
            self.reindex_all()
            return

        existing = {}
        try:
            results = self.collection.get(include=["metadatas"])
            for meta in results["metadatas"]:
                if meta and "source_file" in meta:
                    existing[meta["source_file"]] = meta.get("file_hash", "")
        except Exception:
            pass

        for pdf_path in pdf_files:
            current_hash = self._file_hash(pdf_path)
            if existing.get(pdf_path.name) == current_hash:
                continue
            if pdf_path.name in existing:
                self.collection.delete(where={"source_file": pdf_path.name})
            self._index_pdf(pdf_path, current_hash)

    def _index_pdf(self, pdf_path: Path, file_hash: str):
        meta = self._get_pdf_metadata(pdf_path.name)
        pages = extract_text_from_pdf(pdf_path)

        texts = []
        metadatas = []
        ids = []

        current_section = {"section_code": "Preamble", "section_title": "Preamble"}

        for n_idx, chunk in enumerate(chunk_text_with_sections(pages)):
            texts.append(chunk["text"])
            ids.append(
                hashlib.md5(
                    f"{pdf_path.name}_n{n_idx}_p{chunk['start_page']}_{chunk['section_code']}".encode()
                ).hexdigest()
            )
            metadatas.append({
                "source_file": pdf_path.name,
                "file_hash": file_hash,
                "ticker": meta["ticker"],
                "fiscal_year": meta["fiscal_year"],
                "chunk_type": "narrative",
                "section": chunk["section_title"],
                "section_code": chunk["section_code"],
                "page_start": chunk["start_page"],
                "page_end": chunk["start_page"],
                "chunk_index": chunk["chunk_index"],
            })
            current_section = {
                "section_code": chunk["section_code"],
                "section_title": chunk["section_title"],
            }

        for page in pages:
            for t_idx, table in enumerate(page["tables"]):
                table_text = table_to_text(table)
                if not table_text:
                    continue
                for r_idx, tchunk in enumerate(chunk_text(table_text, chunk_size=900, overlap=0)):
                    texts.append(tchunk)
                    ids.append(hashlib.md5(f"{pdf_path.name}_p{page['page']}_t{t_idx}_{r_idx}".encode()).hexdigest())
                    metadatas.append({
                        "source_file": pdf_path.name,
                        "file_hash": file_hash,
                        "ticker": meta["ticker"],
                        "fiscal_year": meta["fiscal_year"],
                        "chunk_type": "table_row" if len(table_text) > 0 else "table",
                        "section": current_section["section_title"],
                        "section_code": current_section["section_code"],
                        "page_start": page["page"],
                        "page_end": page["page"],
                        "table_index": t_idx,
                        "chunk_index": r_idx,
                    })

        if texts:
            all_embeddings = []
            batch_size = 20
            for i in range(0, len(texts), batch_size):
                all_embeddings.extend(self.get_embedding(texts[i:i + batch_size]))

            self.collection.add(
                ids=ids,
                embeddings=all_embeddings,
                documents=texts,
                metadatas=metadatas,
            )

    def query(
        self,
        question: str,
        ticker: Optional[str] = None,
        fiscal_year: Optional[str] = None,
        section: Optional[str] = None,
        section_code: Optional[str] = None,
        chunk_type: Optional[str] = None,
        top_k: int = TOP_K,
    ) -> dict:
        query_embedding = self.get_embedding([question])[0]
        conditions = []
        if ticker:
            conditions.append({"ticker": ticker})
        if fiscal_year:
            conditions.append({"fiscal_year": fiscal_year})
        if section_code:
            conditions.append({"section_code": section_code})
        elif section:
            conditions.append({"section": section})
        if chunk_type:
            conditions.append({"chunk_type": chunk_type})

        where = None
        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self.collection.query(**kwargs)
        chunks = []
        if results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                chunks.append({
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "score": 1 - results["distances"][0][i],
                })
        return {"success": True, "chunks": chunks, "count": len(chunks)}

    def format_results(self, chunks: list[dict]) -> str:
        if not chunks:
            return "No relevant passages found."
        parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            source = f"{meta.get('ticker','?')} FY{meta.get('fiscal_year','?')} 10-K | Item {meta.get('section_code','?')} | p.{meta.get('page_start','?')}"
            parts.append(f"[Source {i}: {source}]\n{chunk['text']}")
        return "\n\n---\n\n".join(parts)

    def list_sections(self, ticker: Optional[str] = None, fiscal_year: Optional[str] = None) -> list[str]:
        conditions = []
        if ticker:
            conditions.append({"ticker": ticker})
        if fiscal_year:
            conditions.append({"fiscal_year": fiscal_year})

        where = None
        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        kwargs = {"include": ["metadatas"]}
        if where:
            kwargs["where"] = where

        results = self.collection.get(**kwargs)
        labels = set()
        for meta in results["metadatas"]:
            if not meta:
                continue
            code = meta.get("section_code", "")
            title = meta.get("section", "")
            if code and title:
                labels.add(f"Item {code} - {title}")
        return sorted(labels)


# """
# PDF RAG Tool - Embeds and retrieves from 10-K PDF filings using ChromaDB.
# Section-aware chunking with correct header detection.
# """
# import os
# import re
# import hashlib
# from pathlib import Path
# from typing import Optional

# import fireworks.client
# import chromadb
# from chromadb.config import Settings
# import pdfplumber


# # ── Chunking config ───────────────────────────────────────────────────────────
# CHUNK_SIZE    = 1000   # characters per chunk
# CHUNK_OVERLAP = 200    # overlap between chunks
# TOP_K         = 8      # chunks to retrieve per query

# # ── 10-K section patterns ─────────────────────────────────────────────────────
# # Ordered from most specific to least specific.
# # Each entry: (regex, section_code, section_title)
# SECTION_PATTERNS = [
#     (r"(?i)^item\s+1a[\.\s\-]",          "1A",  "Risk Factors"),
#     (r"(?i)^item\s+1b[\.\s\-]",          "1B",  "Unresolved Staff Comments"),
#     (r"(?i)^item\s+1c[\.\s\-]",          "1C",  "Cybersecurity"),
#     (r"(?i)^item\s+10[\.\s\-]",          "10",  "Directors and Officers"),
#     (r"(?i)^item\s+11[\.\s\-]",          "11",  "Executive Compensation"),
#     (r"(?i)^item\s+12[\.\s\-]",          "12",  "Security Ownership"),
#     (r"(?i)^item\s+13[\.\s\-]",          "13",  "Certain Relationships"),
#     (r"(?i)^item\s+14[\.\s\-]",          "14",  "Principal Accountant Fees"),
#     (r"(?i)^item\s+15[\.\s\-]",          "15",  "Exhibits"),
#     (r"(?i)^item\s+1[\.\s\-]",           "1",   "Business"),
#     (r"(?i)^item\s+2[\.\s\-]",           "2",   "Properties"),
#     (r"(?i)^item\s+3[\.\s\-]",           "3",   "Legal Proceedings"),
#     (r"(?i)^item\s+4[\.\s\-]",           "4",   "Mine Safety"),
#     (r"(?i)^item\s+5[\.\s\-]",           "5",   "Market for Registrant Equity"),
#     (r"(?i)^item\s+6[\.\s\-]",           "6",   "Reserved"),
#     (r"(?i)^item\s+7a[\.\s\-]",          "7A",  "Quantitative Disclosures"),
#     (r"(?i)^item\s+7[\.\s\-]",           "7",   "MD&A"),
#     (r"(?i)^item\s+8[\.\s\-]",           "8",   "Financial Statements"),
#     (r"(?i)^item\s+9a[\.\s\-]",          "9A",  "Controls and Procedures"),
#     (r"(?i)^item\s+9b[\.\s\-]",          "9B",  "Other Information"),
#     (r"(?i)^item\s+9[\.\s\-]",           "9",   "Disagreements with Accountants"),
# ]

# _COMPILED = [(re.compile(p), code, title) for p, code, title in SECTION_PATTERNS]


# # ── Helper functions ──────────────────────────────────────────────────────────

# def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
#     """
#     Extract text and tables page by page.
#     Returns list of {"page": int, "text": str, "tables": list}.
#     """
#     pages = []
#     with pdfplumber.open(str(pdf_path)) as pdf:
#         for i, page in enumerate(pdf.pages, start=1):
#             text = page.extract_text() or ""
#             try:
#                 tables = page.extract_tables() or []
#             except Exception:
#                 tables = []
#             pages.append({"page": i, "text": text.strip(), "tables": tables})
#     return pages


# def clean_text(text: str) -> str:
#     """Remove page-number-only lines and common header/footer noise."""
#     lines = []
#     for line in text.splitlines():
#         stripped = line.strip()
#         # Skip standalone page numbers
#         if re.match(r"^\d{1,3}$", stripped):
#             continue
#         # Skip common running headers/footers
#         if re.match(r"(?i)^(apple|microsoft|alphabet)\s+inc\.?\s*\|", stripped):
#             continue
#         lines.append(line)
#     return "\n".join(lines).strip()


# def detect_section(text: str) -> Optional[dict]:
#     """
#     Detect a 10-K section header in the first 20 lines of a page.
#     Only matches short lines (< 100 chars) that START with 'Item N'.
#     Returns {"section_code": ..., "section_title": ...} or None.
#     """
#     for line in text.splitlines()[:20]:
#         stripped = line.strip()
#         # Headers are short standalone lines
#         if not stripped or len(stripped) > 100:
#             continue
#         for pattern, code, title in _COMPILED:
#             if pattern.match(stripped):
#                 return {"section_code": code, "section_title": title}
#     return None


# def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
#                overlap: int = CHUNK_OVERLAP) -> list[str]:
#     """
#     Split text into overlapping chunks, respecting paragraph boundaries.
#     Tries to merge short paragraphs before splitting long ones.
#     """
#     # Normalise whitespace
#     text = re.sub(r"\n{3,}", "\n\n", text)
#     paragraphs = [p.strip() for p in re.split(r"\n\n", text) if p.strip()]

#     chunks: list[str] = []
#     for para in paragraphs:
#         if len(para) <= chunk_size:
#             # Try to merge with previous chunk
#             if chunks and len(chunks[-1]) + len(para) + 2 <= chunk_size:
#                 chunks[-1] += "\n\n" + para
#             else:
#                 chunks.append(para)
#         else:
#             # Split long paragraph with overlap
#             start = 0
#             while start < len(para):
#                 piece = para[start: start + chunk_size].strip()
#                 if piece:
#                     chunks.append(piece)
#                 start += max(1, chunk_size - overlap)
#     return chunks


# def table_to_text(table: list[list]) -> str:
#     """Convert a pdfplumber table (list of rows) to pipe-delimited text."""
#     rows = []
#     for row in table:
#         if not row:
#             continue
#         cleaned = [str(cell).strip() if cell is not None else "" for cell in row]
#         if any(cleaned):
#             rows.append(" | ".join(cleaned))
#     return "\n".join(rows).strip()


# # ── PDFTool class ─────────────────────────────────────────────────────────────

# class PDFTool:
#     def __init__(self, pdf_dir: Path, persist_dir: Path,
#                  ensure_indexed: bool = True):
#         self.pdf_dir     = pdf_dir
#         self.persist_dir = persist_dir
#         self.api_key     = os.getenv("FIREWORKS_API_KEY")
#         self.persist_dir.mkdir(parents=True, exist_ok=True)

#         self.fw_client = fireworks.client.Fireworks(api_key=self.api_key)
#         self.chroma    = chromadb.PersistentClient(
#             path=str(self.persist_dir),
#             settings=Settings(anonymized_telemetry=False),
#         )
#         self.collection = self.chroma.get_or_create_collection(
#             name="tenk_filings",
#             metadata={"hnsw:space": "cosine"},
#         )

#         if ensure_indexed:
#             self._ensure_indexed()

#     # ── Lifecycle ─────────────────────────────────────────────────────────────

#     def close(self) -> None:
#         try:
#             self.fw_client.close()
#         except Exception:
#             pass

#     def reindex_all(self) -> None:
#         """Wipe the collection and re-index every PDF from scratch."""
#         print("Wiping existing index...")
#         self.chroma.delete_collection("tenk_filings")
#         self.collection = self.chroma.get_or_create_collection(
#             name="tenk_filings",
#             metadata={"hnsw:space": "cosine"},
#         )
#         self._ensure_indexed()

#     # ── Indexing ──────────────────────────────────────────────────────────────

#     def _file_hash(self, path: Path) -> str:
#         h = hashlib.md5()
#         with open(path, "rb") as f:
#             for block in iter(lambda: f.read(65536), b""):
#                 h.update(block)
#         return h.hexdigest()

#     def _get_pdf_meta(self, filename: str) -> dict:
#         m = re.match(r"([A-Z]+)_FY(\d{4})_10-K\.pdf", filename)
#         if m:
#             return {"ticker": m.group(1), "fiscal_year": m.group(2)}
#         return {"ticker": "UNKNOWN", "fiscal_year": "UNKNOWN"}

#     def _ensure_indexed(self) -> None:
#         pdf_files = sorted(self.pdf_dir.glob("*.pdf"))
#         if not pdf_files:
#             print(f"Warning: no PDFs found in {self.pdf_dir}")
#             return

#         # Build map of already-indexed files → stored hash
#         indexed: dict[str, str] = {}
#         try:
#             res = self.collection.get(include=["metadatas"])
#             for meta in res["metadatas"]:
#                 if meta and "source_file" in meta:
#                     indexed[meta["source_file"]] = meta.get("file_hash", "")
#         except Exception:
#             pass

#         for pdf_path in pdf_files:
#             current_hash = self._file_hash(pdf_path)
#             if indexed.get(pdf_path.name) == current_hash:
#                 print(f"  Already indexed: {pdf_path.name}")
#                 continue
#             if pdf_path.name in indexed:
#                 print(f"  Re-indexing (changed): {pdf_path.name}")
#                 self.collection.delete(where={"source_file": pdf_path.name})
#             else:
#                 print(f"  Indexing: {pdf_path.name}")
#             self._index_pdf(pdf_path, current_hash)

#     def _index_pdf(self, pdf_path: Path, file_hash: str) -> None:
#         meta     = self._get_pdf_meta(pdf_path.name)
#         pages    = extract_text_from_pdf(pdf_path)
#         texts: list[str]  = []
#         metas: list[dict] = []
#         ids:   list[str]  = []

#         current_section = {"section_code": "Preamble",
#                            "section_title": "Preamble"}

#         for page in pages:
#             raw_text = page["text"]
#             if raw_text:
#                 page_text = clean_text(raw_text)

#                 # Update section tracker
#                 detected = detect_section(page_text)
#                 if detected:
#                     current_section = detected

#                 for j, chunk in enumerate(chunk_text(page_text)):
#                     chunk_id = hashlib.md5(
#                         f"{pdf_path.name}_p{page['page']}_n{j}".encode()
#                     ).hexdigest()
#                     texts.append(chunk)
#                     ids.append(chunk_id)
#                     metas.append({
#                         "source_file":   pdf_path.name,
#                         "file_hash":     file_hash,
#                         "ticker":        meta["ticker"],
#                         "fiscal_year":   meta["fiscal_year"],
#                         "chunk_type":    "narrative",
#                         "section_code":  current_section["section_code"],
#                         "section_title": current_section["section_title"],
#                         "page_start":    page["page"],
#                         "chunk_index":   j,
#                     })

#             # Index tables separately
#             for t_idx, table in enumerate(page.get("tables", [])):
#                 ttext = table_to_text(table)
#                 if not ttext:
#                     continue
#                 for r_idx, tchunk in enumerate(
#                     chunk_text(ttext, chunk_size=900, overlap=0)
#                 ):
#                     chunk_id = hashlib.md5(
#                         f"{pdf_path.name}_p{page['page']}_t{t_idx}_{r_idx}".encode()
#                     ).hexdigest()
#                     texts.append(tchunk)
#                     ids.append(chunk_id)
#                     metas.append({
#                         "source_file":   pdf_path.name,
#                         "file_hash":     file_hash,
#                         "ticker":        meta["ticker"],
#                         "fiscal_year":   meta["fiscal_year"],
#                         "chunk_type":    "table",
#                         "section_code":  current_section["section_code"],
#                         "section_title": current_section["section_title"],
#                         "page_start":    page["page"],
#                         "chunk_index":   r_idx,
#                     })

#         if not texts:
#             print(f"  Warning: no text extracted from {pdf_path.name}")
#             return

#         # Embed in batches of 20
#         all_embeddings: list[list[float]] = []
#         batch_size = 20
#         for i in range(0, len(texts), batch_size):
#             batch = texts[i: i + batch_size]
#             embeddings = self.get_embedding(batch)
#             all_embeddings.extend(embeddings)

#         self.collection.add(
#             ids=ids,
#             embeddings=all_embeddings,
#             documents=texts,
#             metadatas=metas,
#         )
#         print(f"  Done: {len(texts)} chunks from {pdf_path.name}")

#         # Show section breakdown
#         section_counts: dict[str, int] = {}
#         for m in metas:
#             k = f"Item {m['section_code']} - {m['section_title']}"
#             section_counts[k] = section_counts.get(k, 0) + 1
#         for sec, cnt in sorted(section_counts.items()):
#             print(f"    {sec}: {cnt} chunks")

#     # ── Embeddings ────────────────────────────────────────────────────────────

#     def get_embedding(self, texts: list[str]) -> list[list[float]]:
#         response = self.fw_client.embeddings.create(
#             model="nomic-ai/nomic-embed-text-v1.5",
#             input=texts,
#         )
#         return [item.embedding for item in response.data]

#     # ── Retrieval ─────────────────────────────────────────────────────────────

#     def query(
#         self,
#         question:     str,
#         ticker:       Optional[str] = None,
#         fiscal_year:  Optional[str] = None,
#         section_code: Optional[str] = None,
#         chunk_type:   Optional[str] = None,
#     ) -> dict:
#         """
#         Retrieve the TOP_K most relevant chunks for a question.
#         Optional filters: ticker, fiscal_year, section_code, chunk_type.
#         """
#         query_embedding = self.get_embedding([question])[0]

#         conditions = []
#         if ticker:
#             conditions.append({"ticker": ticker})
#         if fiscal_year:
#             conditions.append({"fiscal_year": str(fiscal_year)})
#         if section_code:
#             conditions.append({"section_code": section_code})
#         if chunk_type:
#             conditions.append({"chunk_type": chunk_type})

#         where = None
#         if len(conditions) == 1:
#             where = conditions[0]
#         elif len(conditions) > 1:
#             where = {"$and": conditions}

#         kwargs: dict = {
#             "query_embeddings": [query_embedding],
#             "n_results":        TOP_K,
#             "include":          ["documents", "metadatas", "distances"],
#         }
#         if where:
#             kwargs["where"] = where

#         results = self.collection.query(**kwargs)

#         chunks = []
#         docs  = results.get("documents",  [[]])[0]
#         metas = results.get("metadatas",  [[]])[0]
#         dists = results.get("distances",  [[]])[0]

#         for i in range(len(docs)):
#             chunks.append({
#                 "text":     docs[i],
#                 "metadata": metas[i],
#                 "score":    round(1 - dists[i], 4),
#             })

#         return {"success": True, "chunks": chunks, "count": len(chunks)}

#     # ── Formatting ────────────────────────────────────────────────────────────

#     def format_results(self, chunks: list[dict]) -> str:
#         if not chunks:
#             return "No relevant passages found."
#         parts = []
#         for i, chunk in enumerate(chunks, 1):
#             m = chunk["metadata"]
#             source = (
#                 f"{m.get('ticker','?')} FY{m.get('fiscal_year','?')} 10-K"
#                 f" | Item {m.get('section_code','?')} - {m.get('section_title','?')}"
#                 f" | p.{m.get('page_start','?')}"
#                 f" | score={chunk['score']}"
#             )
#             parts.append(f"[{source}]\n{chunk['text']}")
#         return "\n\n---\n\n".join(parts)

#     def list_sections(
#         self,
#         ticker:      Optional[str] = None,
#         fiscal_year: Optional[str] = None,
#     ) -> list[str]:
#         """Return all unique section codes present in the index."""
#         conditions = []
#         if ticker:
#             conditions.append({"ticker": ticker})
#         if fiscal_year:
#             conditions.append({"fiscal_year": str(fiscal_year)})

#         where = None
#         if len(conditions) == 1:
#             where = conditions[0]
#         elif len(conditions) > 1:
#             where = {"$and": conditions}

#         kwargs: dict = {"include": ["metadatas"]}
#         if where:
#             kwargs["where"] = where

#         res = self.collection.get(**kwargs)
#         return sorted({
#             f"Item {m.get('section_code','?')} - {m.get('section_title','?')}"
#             for m in res["metadatas"] if m
#         })