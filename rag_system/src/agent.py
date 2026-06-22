import os
import json
import re
from pathlib import Path
from typing import Optional, Literal, Any

import fireworks.client
from pydantic import BaseModel, Field

from sql_tool import SQLTool
from pdf_tool import PDFTool

SQL_HINTS = (
    "revenue", "income", "margin", "ratio", "percent", "percentage",
    "growth rate", "eps", "ebitda", "operating income", "net income",
    "balance sheet", "cash flow", "segment revenue", "geographic revenue",
    "compare", "comparison", "table", "how much", "how many"
)

PDF_HINTS = (
    "risk factor", "risk factors", "why", "explain", "describe",
    "strategy", "management discussion", "md&a", "definition",
    "what does", "what are the components", "qualitative"
)

SYSTEM_PROMPT = """You are a financial research assistant with access to two tools.

1. sql_query(question): Query structured financial data.
2. pdf_search(question, ticker?, fiscal_year?, section?): Search 10-K PDF filings.

Routing rules:
- Numbers, financials, ratios -> sql_query
- Risk factors, strategy, explanations, why questions -> pdf_search
- Questions asking both numbers and explanations -> use BOTH tools
- Prefer required_modalities when provided by the caller

Return only valid JSON matching the schema.
"""

_SYNTHESIS_PROMPT_LIST = """Answer the question below using ONLY the provided evidence.

Question: {question}

Evidence:
{evidence}

Rules:
- Start immediately with the answer — no preamble like "Based on the provided evidence"
- Use bullet points for each distinct risk factor, component, or disclosure theme
- Cover every major theme present in the evidence (manufacturing, suppliers, geography, disruptions, shortages, etc.)
- Use the company's disclosure language where possible; do not invent risks not in the evidence
- End with a short inline citation, e.g. "per Apple FY2025 10-K Item 1A"
- If evidence is missing, say "Insufficient data" and stop

Answer:"""

_SUPPLY_CHAIN_QUERY_TERMS = (
    "supply chain single or limited sources third-party manufacturers outsourcing "
    "component shortages price increases supplier agreements geopolitical tensions "
    "natural disasters public health emergencies manufacturing concentration regions"
)

_SYNTHESIS_PROMPT_DEFAULT = """Answer the question below using ONLY the provided evidence. Be concise and direct.

Question: {question}

Evidence:
{evidence}

Rules:
- Start immediately with the answer
- For numeric answers, lead with the number and include units
- For company comparisons, name the winner first then explain
- Cite sources inline: "per SQL data" or "per Apple FY2025 10-K"
- Maximum 4 sentences for simple questions, 8 for complex multi-part questions
- If evidence is missing, say "Insufficient data" and stop

Answer:"""

class ToolCall(BaseModel):
    tool: Literal["sql_query", "pdf_search"]
    args: dict[str, Any] = Field(default_factory=dict)

class RouteDecision(BaseModel):
    thoughts: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    status: Literal["ok", "fallback", "required"] = "ok"

class ToolResult(BaseModel):
    source: Literal["sql", "pdf"]
    success: bool
    content: str = ""
    raw: Any = None
    sql: Optional[str] = None
    chunks: Optional[list[dict]] = None
    error: Optional[str] = None

class AnswerResult(BaseModel):
    answer: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    routing: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

def _is_list_question(question: str) -> bool:
    q = question.lower()
    return any(
        kw in q for kw in (
            "risk factor", "risk factors", "what are", "list", "what is included",
            "what does", "describe", "explain", "how does", "what types",
            "primary", "components of", "key components",
        )
    )


def _pdf_retrieval_query(question: str) -> str:
    q = question.lower()
    if "supply chain" in q:
        return f"{_SUPPLY_CHAIN_QUERY_TERMS} {question}"
    if "youtube" in q or "google services" in q:
        return f"YouTube advertising revenue change year over year MD&A segment revenue {question}"
    return question


def _rerank_pdf_chunks(chunks: list[dict], question: str) -> list[dict]:
    q = question.lower()
    if not chunks:
        return chunks

    focus_terms: list[str] = []
    if "supply chain" in q or "risk factor" in q:
        focus_terms = [
            "supply", "manufactur", "component", "single or limited", "third-party",
            "third party", "supplier", "geopolit", "natural disaster", "pandemic",
            "concentrat", "region", "outsource", "shortage", "contract manufacturer",
        ]
    elif "youtube" in q or "google services" in q:
        focus_terms = ["youtube", "google search", "google network", "subscription", "revenue", "billion"]

    if not focus_terms:
        return chunks

    def score(chunk: dict) -> float:
        text = chunk.get("text", "").lower()
        keyword_hits = sum(1 for term in focus_terms if term in text)
        return chunk.get("score", 0.0) + (0.04 * keyword_hits)

    ranked = sorted(chunks, key=score, reverse=True)
    return ranked[: min(8, len(ranked))]

def _format_money(value: float | int) -> str:
    if isinstance(value, bool):
        return str(value)
    v = float(value)
    if abs(v) >= 1_000_000_000:
        return f"${v / 1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.0f}M"
    return f"${v:,.0f}"

def _format_scalar(value: Any, question: str) -> str:
    q = question.lower()
    if isinstance(value, (int, float)) and any(w in q for w in ("margin", "ratio", "percent", "rate", "%")):
        return f"{float(value):.1f}%"
    if isinstance(value, (int, float)):
        return _format_money(value) if abs(float(value)) >= 1_000_000 else f"{value:,.2f}" if isinstance(value, float) else str(value)
    return str(value)


def _format_column(key: str, value: Any, question: str) -> str:
    key_lower = key.lower()
    if isinstance(value, (int, float)):
        if "current_ratio" in key_lower or key_lower == "ratio":
            return f"{float(value):.2f}x"
        if any(token in key_lower for token in ("pct", "percent", "margin", "rate", "growth")):
            return f"{float(value):.1f}%"
        if any(token in key_lower for token in ("revenue", "income", "assets", "liabilities", "cash", "eps", "amount")):
            return _format_money(value)
    return _format_scalar(value, question)


def _format_largest_increase_answer(preset: dict) -> str:
    company_names = {"AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet"}
    companies = preset["results"]
    segments = preset.get("segment_results", [])
    winner = companies[0]
    winner_ticker = winner["company_ticker"]
    winner_name = company_names.get(winner_ticker, winner_ticker)

    segment_bits = []
    for row in segments:
        segment_bits.append(
            f"{row['segment_name']} grew by {_format_money(row['segment_change'])} "
            f"({_format_money(row['revenue_2024'])} to {_format_money(row['revenue_2025'])})"
        )

    other_bits = []
    for row in companies[1:]:
        name = company_names.get(row["company_ticker"], row["company_ticker"])
        other_bits.append(f"{name} increased by {_format_money(row['absolute_increase'])}")

    answer = (
        f"{winner_name} had the largest absolute increase at approximately "
        f"{_format_money(winner['absolute_increase'])} "
        f"({_format_money(winner['revenue_2024'])} to {_format_money(winner['revenue_2025'])}). "
        f"By operating segment, {', '.join(segment_bits)}"
    )
    if other_bits:
        answer += f". {'; '.join(other_bits)}"
    return answer + " (per SQL data)"


def _infer_company_label(question: str) -> str:
    q = question.lower()
    if "apple" in q:
        return "Apple (AAPL)"
    if "microsoft" in q:
        return "Microsoft (MSFT)"
    if "alphabet" in q or "google" in q:
        return "Alphabet (GOOGL)"
    return "The company"


def _format_single_row_sql_answer(row: dict[str, Any], question: str) -> str:
    if not row:
        return ""

    ticker = row.get("company_ticker") or row.get("ticker")
    company = ticker or _infer_company_label(question)

    if "growth_pct" in row:
        return f"{company} had the fastest revenue growth rate at {_format_column('growth_pct', row['growth_pct'], question)} (per SQL data)"
    if "us_pct" in row:
        return f"{company} had {_format_column('us_pct', row['us_pct'], question)} of its total revenue from the United States in FY2025 (per SQL data)"
    if "current_ratio" in row:
        return f"{company} had a current ratio of {_format_column('current_ratio', row['current_ratio'], question)} in FY2025 (per SQL data)"

    if ticker and len(row) == 2:
        other_key = next(k for k in row if k not in ("company_ticker", "ticker"))
        return f"{company} {_format_column(other_key, row[other_key], question)} (per SQL data)"

    pct_keys = [
        k for k, v in row.items()
        if isinstance(v, (int, float)) and any(token in k.lower() for token in ("pct", "ratio", "margin", "rate"))
    ]
    if len(pct_keys) == 1:
        return f"{_format_column(pct_keys[0], row[pct_keys[0]], question)} (per SQL data)"

    parts = []
    for key, value in row.items():
        if key in ("company_ticker", "ticker", "region"):
            continue
        parts.append(f"{key.replace('_', ' ')} {_format_column(key, value, question)}")
    if parts:
        prefix = f"{company} " if company != "The company" else ""
        return f"{prefix}{'; '.join(parts)} (per SQL data)"
    return f"{'; '.join(parts)} (per SQL data)"

class RAGAgent:
    def __init__(self, data_dir: Path, ensure_pdf_index: bool = True):
        self.data_dir = data_dir
        self.api_key = os.getenv("FIREWORKS_API_KEY")
        if not self.api_key:
            raise ValueError("FIREWORKS_API_KEY environment variable not set")

        self.client = fireworks.client.Fireworks(api_key=self.api_key)
        self.sql_tool = SQLTool(db_path=data_dir / "financials.db")
        self.pdf_tool = PDFTool(
            pdf_dir=data_dir / "pdfs",
            persist_dir=data_dir / "chroma_db",
            ensure_indexed=ensure_pdf_index,
        )

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.pdf_tool.close()
        except Exception:
            pass

    def _infer_pdf_args(self, question: str) -> dict[str, Any]:
        q = question.lower()
        args: dict[str, Any] = {"question": question}

        if "apple" in q:
            args["ticker"] = "AAPL"
        elif "microsoft" in q:
            args["ticker"] = "MSFT"
        elif "alphabet" in q or "google" in q:
            args["ticker"] = "GOOGL"

        if "2025" in q:
            args["fiscal_year"] = "2025"
        elif "2024" in q:
            args["fiscal_year"] = "2024"

        if any(k in q for k in ("risk factor", "risk factors", "risk")):
            args["section"] = "Risk Factors"
            args["section_code"] = "1A"
            args["chunk_type"] = "narrative"
        elif any(k in q for k in ("revenue change", "how did", "year-over-year", "between fy", "youtube")):
            args["section"] = "MD&A"
            args["section_code"] = "7"
            args["chunk_type"] = "narrative"
        elif any(k in q for k in ("md&a", "management discussion", "why", "explain", "strategy")):
            args["section"] = "MD&A"
            args["section_code"] = "7"
            args["chunk_type"] = "narrative"
        elif "financial statements" in q:
            args["section"] = "Financial Statements"
        elif "business" in q or "components" in q:
            args["section"] = "Business"
            args["chunk_type"] = "narrative"

        return args

    def _rule_route(self, question: str) -> Optional[RouteDecision]:
        q = question.lower()
        sql_score = sum(h in q for h in SQL_HINTS)
        pdf_score = sum(h in q for h in PDF_HINTS)

        if sql_score > pdf_score + 1:
            return RouteDecision(
                thoughts="Rule-based route: SQL",
                tool_calls=[ToolCall(tool="sql_query", args={"question": question})],
                status="ok",
            )

        if pdf_score > sql_score + 1:
            return RouteDecision(
                thoughts="Rule-based route: PDF",
                tool_calls=[ToolCall(tool="pdf_search", args=self._infer_pdf_args(question))],
                status="ok",
            )

        return None

    def _llm_route(self, question: str) -> RouteDecision:
        response = self.client.chat.completions.create(
            model="accounts/fireworks/models/deepseek-v4-pro",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Question: {question}\nReturn JSON only."},
            ],
            max_tokens=100,
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            return RouteDecision(
                thoughts="Fallback: SQL-only",
                tool_calls=[ToolCall(tool="sql_query", args={"question": question})],
                status="fallback",
            )

        try:
            parsed = json.loads(json_match.group())
            tool_calls = [ToolCall(**tc) for tc in parsed.get("tool_calls", [])]
            if not tool_calls:
                raise ValueError("No tool calls")
            return RouteDecision(
                thoughts=parsed.get("thoughts", ""),
                tool_calls=tool_calls,
                status="ok",
            )
        except Exception:
            return RouteDecision(
                thoughts="Fallback: SQL-only",
                tool_calls=[ToolCall(tool="sql_query", args={"question": question})],
                status="fallback",
            )

    def _route(self, question: str, required_modalities: Optional[list[str]] = None) -> RouteDecision:
        if required_modalities:
            tool_calls: list[ToolCall] = []
            mods = set(required_modalities)
            if "sql" in mods:
                tool_calls.append(ToolCall(tool="sql_query", args={"question": question}))
            if "pdf" in mods:
                tool_calls.append(ToolCall(tool="pdf_search", args=self._infer_pdf_args(question)))
            return RouteDecision(thoughts="Routed from required_modalities", tool_calls=tool_calls, status="required")

        rule_result = self._rule_route(question)
        if rule_result is not None:
            return rule_result

        return self._llm_route(question)

    def _execute_tools(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        results: list[ToolResult] = []

        for call in tool_calls:
            if call.tool == "sql_query":
                try:
                    result = self.sql_tool.query(call.args.get("question", ""))
                    if result.get("success") and result.get("results"):
                        content = result.get("formatted") or self.sql_tool.format_results(result["results"])
                        results.append(
                            ToolResult(
                                source="sql",
                                success=True,
                                sql=result.get("sql", ""),
                                raw=result["results"],
                                content=content,
                            )
                        )
                    else:
                        results.append(
                            ToolResult(
                                source="sql",
                                success=False,
                                error=result.get("error", "no rows"),
                                raw=result.get("results", []),
                                content=result.get("error", "No rows returned."),
                            )
                        )
                except Exception as e:
                    results.append(ToolResult(source="sql", success=False, error=str(e), content=str(e), raw=[]))

            elif call.tool == "pdf_search":
                pdf_question = _pdf_retrieval_query(call.args.get("question", ""))
                pdf_args = {**call.args, "question": pdf_question}
                print(f"Calling PDF tool with args: {pdf_args}")
                try:
                    result = self.pdf_tool.query(
                            question=pdf_question,
                            ticker=call.args.get("ticker"),
                            fiscal_year=call.args.get("fiscal_year"),
                            section=call.args.get("section"),
                            section_code=call.args.get("section_code"),
                            chunk_type=call.args.get("chunk_type"),
                            top_k=12 if _is_list_question(call.args.get("question", "")) else 8,
                        )
                    if result.get("chunks"):
                        result["chunks"] = _rerank_pdf_chunks(
                            result["chunks"], call.args.get("question", "")
                        )
                    print(result)
                    if result.get("success") and result.get("chunks"):
                        results.append(
                            ToolResult(
                                source="pdf",
                                success=True,
                                chunks=result["chunks"],
                                content=self.pdf_tool.format_results(result["chunks"]),
                                raw=result["chunks"],
                            )
                        )
                    else:
                        results.append(
                            ToolResult(
                                source="pdf",
                                success=False,
                                error="No relevant PDF chunks found",
                                raw=[],
                                content="No relevant PDF chunks found.",
                            )
                        )
                except Exception as e:
                    results.append(ToolResult(source="pdf", success=False, error=str(e), content=str(e), raw=[]))

        return results

    def _diagnostics(self, routed: RouteDecision, tool_results: list[ToolResult]) -> dict[str, Any]:
        used = [r.source for r in tool_results]
        failures = [r.source for r in tool_results if not r.success]
        return {
            "status": "ok" if tool_results and any(r.success for r in tool_results) else "insufficient_data",
            "routing_status": routed.status,
            "tools_used": used,
            "failed_tools": failures,
            "evidence_count": sum(1 for r in tool_results if r.success),
        }

    def _synthesize(self, question: str, tool_results: list[ToolResult]) -> str:
        sql_results = [r for r in tool_results if r.source == "sql" and r.success]
        pdf_results = [r for r in tool_results if r.source == "pdf" and r.success]
        sql_failures = [r for r in tool_results if r.source == "sql" and not r.success]

        if self.sql_tool._matches_highest_current_ratio(question):
            preset = self.sql_tool.try_preset_query(question)
            if preset and preset.get("preset_type") == "current_ratio":
                formatted = preset.get("formatted") or self.sql_tool.format_current_ratio_results(
                    preset["results"]
                )
                return formatted + " (per SQL data)"

        if self.sql_tool._matches_largest_increase_with_segments(question):
            preset = self.sql_tool.try_preset_query(question)
            if preset and preset.get("preset_type") != "current_ratio":
                return _format_largest_increase_answer(preset)

        if len(sql_results) == 1 and not pdf_results:
            raw_rows = sql_results[0].raw or []
            if len(raw_rows) == 1:
                row = raw_rows[0]
                if len(row) == 1:
                    scalar_value = next(iter(row.values()))
                    if isinstance(scalar_value, (int, float)):
                        return f"{_format_scalar(scalar_value, question)} (per SQL data)"
                    return f"{scalar_value} (per SQL data)"
                formatted = _format_single_row_sql_answer(row, question)
                if formatted:
                    return formatted

        if sql_results and pdf_results:
            sql_text = "\n\n".join(r.content for r in sql_results)
            pdf_text = "\n\n".join(r.content for r in pdf_results)
            prompt = f"""
Question: {question}

SQL evidence:
{sql_text}

PDF evidence:
{pdf_text}

Rules:
- Use SQL evidence for numeric facts, changes, and comparisons.
- Use PDF evidence for narrative explanation, definitions, and disclosure language.
- If one part is supported and the other is not, answer the supported part and say which part is missing.
- Do not invent missing explanation.
- Be concise and grounded.
"""
            max_tokens = 1000

        elif sql_results:
            sql_text = "\n\n".join(r.content for r in sql_results)
            prompt = f"""
Question: {question}

SQL evidence:
{sql_text}

Rules:
- Answer using only the SQL evidence.
- If the question needs explanation that SQL cannot provide, say that explanation is missing.
- Be concise and grounded.
"""
            max_tokens = 700

        elif sql_failures and not pdf_results:
            sql_text = "\n\n".join(r.content or r.error or "SQL query failed." for r in sql_failures)
            prompt = f"""
Question: {question}

SQL evidence:
{sql_text}

Rules:
- The SQL query failed or returned no rows.
- Say the structured data could not be retrieved. Do not mention PDF evidence.
- Be concise.
"""
            max_tokens = 300

        else:
            pdf_text = "\n\n".join(r.content for r in pdf_results) if pdf_results else "No PDF evidence."
            if _is_list_question(question):
                prompt = _SYNTHESIS_PROMPT_LIST.format(question=question, evidence=pdf_text)
                max_tokens = 900
            else:
                prompt = f"""
Question: {question}

PDF evidence:
{pdf_text}

Rules:
- Answer using only the PDF evidence.
- If the question asks for numbers not present here, say those numbers are missing.
- Be concise and grounded.
"""
                max_tokens = 700

        response = self.client.chat.completions.create(
            model="accounts/fireworks/models/deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0,
        )
        return response.choices[0].message.content.strip()

    def answer(self, question: str, required_modalities: Optional[list[str]] = None) -> dict[str, Any]:
        routed = self._route(question, required_modalities=required_modalities)
        tool_results = self._execute_tools(routed.tool_calls)
        answer = self._synthesize(question, tool_results)

        sources: list[dict[str, Any]] = []
        for r in tool_results:
            if r.source == "sql" and r.success:
                sources.append({"type": "sql", "sql": r.sql or "", "content": r.content})
            elif r.source == "pdf" and r.success:
                for chunk in r.chunks or []:
                    meta = chunk.get("metadata", {})
                    sources.append({
                        "type": "pdf",
                        "file": meta.get("source_file", ""),
                        "ticker": meta.get("ticker", ""),
                        "fiscal_year": meta.get("fiscal_year", ""),
                        "section": meta.get("section_title", meta.get("section", "")),
                        "score": round(chunk.get("score", 0), 3),
                        "text": chunk.get("text", ""),
                    })

        out = AnswerResult(
            answer=answer,
            diagnostics=self._diagnostics(routed, tool_results),
            sources=sources,
            routing=routed.thoughts,
            tool_calls=[tc.model_dump() for tc in routed.tool_calls],
        )
        return out.model_dump()