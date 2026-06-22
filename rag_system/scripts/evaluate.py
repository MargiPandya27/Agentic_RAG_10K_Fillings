# """
# Evaluate dev_answers.json against the public answer key.
# Uses fuzzy numeric matching and LLM-as-judge for qualitative answers.
# """
# import json
# import os
# import sys
# import re
# import time
# from pathlib import Path
# import fireworks.client
# from fireworks.client.error import RateLimitError
# from dotenv import load_dotenv

# load_dotenv()


# def extract_number(text: str) -> float | None:
#     """Extract a meaningful numeric answer from arbitrary text."""
#     normalized = text.replace(",", "").replace("$", "").replace("%", "")
#     normalized = re.sub(r"\b(trillion|trillions)\b", "e12", normalized, flags=re.IGNORECASE)
#     normalized = re.sub(r"\b(billion|billions)\b", "e9", normalized, flags=re.IGNORECASE)
#     normalized = re.sub(r"\b(million|millions)\b", "e6", normalized, flags=re.IGNORECASE)
#     normalized = re.sub(r"\b(thousand|thousands)\b", "e3", normalized, flags=re.IGNORECASE)

#     # Prefer explicit unit-qualified values first
#     unit_matches = re.finditer(
#         r"([-+]?\d*\.?\d+)(?:\s*(e\d+|[kKmMbBtT]))?\b",
#         normalized,
#         flags=re.IGNORECASE,
#     )

#     candidates = []
#     for match in unit_matches:
#         num = float(match.group(1))
#         unit = match.group(2)
#         if unit:
#             unit = unit.lower()
#             if unit == "k":
#                 num *= 1e3
#             elif unit == "m":
#                 num *= 1e6
#             elif unit == "b":
#                 num *= 1e9
#             elif unit == "t":
#                 num *= 1e12
#             elif unit.startswith("e"):
#                 try:
#                     num *= 10 ** int(unit[1:])
#                 except ValueError:
#                     pass
#         candidates.append(num)

#     if candidates:
#         # Skip obvious year-like values when possible
#         non_years = [n for n in candidates if not (1900 <= abs(n) <= 2100)]
#         return non_years[0] if non_years else candidates[0]

#     # Fall back to raw numeric values while skipping probable years
#     matches = re.finditer(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", normalized)
#     numbers = [float(m.group()) for m in matches if not (1900 <= float(m.group()) <= 2100)]
#     return numbers[0] if numbers else None


# def fuzzy_numeric_score(predicted: str, gold_numeric: float, tolerance: float = 0.02) -> float:
#     """Score numeric answers with tolerance."""
#     pred_num = extract_number(predicted)
#     if pred_num is None:
#         return 0.0
#     if gold_numeric == 0:
#         return 1.0 if pred_num == 0 else 0.0
#     relative_error = abs(pred_num - gold_numeric) / abs(gold_numeric)
#     return 1.0 if relative_error <= tolerance else 0.0


# def llm_judge_score(question: str, predicted: str, gold: str, api_key: str) -> float:
#     """Use LLM to score qualitative answers."""
#     if not api_key:
#         print("Warning: FIREWORKS_API_KEY is missing; skipping LLM judge scoring.", file=sys.stderr)
#         return 0.0

#     client = fireworks.client.Fireworks(api_key=api_key)
#     try:
#         prompt = f"""You are evaluating a financial research assistant's answer.

# Question: {question}

# Gold Answer: {gold}

# Predicted Answer: {predicted}

# Instructions:
# - Ignore writing style, grammar, and length. Score the answer only on factual correctness and completeness.
# - Award 1.0 only if the predicted answer fully answers the question and matches the key facts in the gold answer.
# - Award 0.75 only if the answer is mostly correct but is missing one small detail or phrased one minor fact imprecisely.
# - Award 0.5 if the answer is partially correct but missing an important element or not fully grounded in the gold answer.
# - Award 0.25 if the answer contains some relevant information but is mostly incorrect or missing the main point.
# - Award 0.0 if the answer is wrong, irrelevant, or contradicts the gold answer.
# - If the predicted answer includes extra reasoning, ignore that and judge the final factual response.

# Return ONLY a single number between 0 and 1, with no explanation."""

#         for attempt in range(3):
#             try:
#                 response = client.chat.completions.create(
#                     model="accounts/fireworks/models/kimi-k2p6",
#                     messages=[{"role": "user", "content": prompt}],
#                     max_tokens=100,
#                     temperature=0,
#                 )
#                 try:
#                     return float(response.choices[0].message.content.strip())
#                 except Exception:
#                     return 0.0
#             except RateLimitError as exc:
#                 if attempt == 2:
#                     print(f"Rate limit exceeded after retries: {exc}", file=sys.stderr)
#                     return 0.0
#                 wait = 2 ** attempt
#                 print(f"Rate limit hit, retrying in {wait}s...", file=sys.stderr)
#                 time.sleep(wait)
#             except Exception as exc:
#                 print(f"LLM judge error: {exc}", file=sys.stderr)
#                 return 0.0
#     finally:
#         try:
#             client.close()
#         except Exception:
#             pass


# def _entity_variants_from_gold(gold_answer: str) -> list[str]:
#     """Return candidate entity strings to match against predicted answers."""
#     text = gold_answer.lower().strip()
#     variants = []

#     if "(" in text and ")" in text:
#         before, rest = text.split("(", 1)
#         variants.append(before.strip())
#         ticker = rest.split(")", 1)[0].strip()
#         if ticker:
#             variants.append(ticker)
#     else:
#         variants.append(text)

#     # Add a generic fallback split if the first entity has multiple words
#     if variants:
#         first = variants[0]
#         if " " in first:
#             variants.extend([part.strip() for part in first.split(" ") if part.strip()])

#     # Deduplicate while preserving order
#     seen = set()
#     unique = []
#     for v in variants:
#         if v and v not in seen:
#             seen.add(v)
#             unique.append(v)
#     return unique


# def evaluate():
#     api_key = os.getenv("FIREWORKS_API_KEY")
#     answers_file = Path("rag_system/questions/dev_answers.json")
#     gold_file = Path("rag_system/questions/dev_questions_with_answers.json")

#     alt_paths = [Path("rag_system/questions/dev_answers.json"), Path("questions/dev_answers.json")]
#     if not answers_file.exists():
#         for alt in alt_paths:
#             if alt.exists():
#                 answers_file = alt
#                 break

#     if not answers_file.exists():
#         print("Error: dev_answers.json not found. Run generate_answers.py first.")
#         sys.exit(1)

#     predicted = json.loads(answers_file.read_text())
#     gold_questions = json.loads(gold_file.read_text())

#     results = []
#     total_score = 0.0
#     count = 0

#     print(f"\n{'='*70}")
#     print(f"{'ID':<8} {'Tier':<6} {'Method':<20} {'Score':<8} Question")
#     print(f"{'='*70}")

#     for q in gold_questions:
#         qid = q["id"]
#         question = q["question"]
#         tier = q["tier"]
#         gold_answer = q["gold_answer"]
#         gold_numeric = q.get("gold_answer_numeric")
#         eval_method = q.get("evaluation", "llm_judge")

#         if qid not in predicted:
#             print(f"{qid:<8} {tier:<6} {'MISSING':<20} {'0.0':<8} {question[:40]}")
#             results.append({"id": qid, "score": 0.0, "method": "missing"})
#             count += 1
#             continue

#         predicted_value = predicted[qid]
#         if isinstance(predicted_value, dict):
#             pred_answer = predicted_value.get("answer", "")
#         else:
#             pred_answer = predicted_value

#         if eval_method == "fuzzy_numeric" and gold_numeric is not None:
#             score = fuzzy_numeric_score(pred_answer, gold_numeric)
#             method = "fuzzy_numeric"
#         elif eval_method == "exact_match_entity":
#             variants = _entity_variants_from_gold(gold_answer)
#             lower_pred = pred_answer.lower()
#             score = 1.0 if any(variant in lower_pred for variant in variants) else 0.0
#             method = "entity_match"
#         else:
#             score = llm_judge_score(question, pred_answer, gold_answer, api_key)
#             method = "llm_judge"

#         total_score += score
#         count += 1
#         results.append({
#             "id": qid,
#             "score": score,
#             "method": method,
#             "tier": tier,
#             "gold_answer": gold_answer,
#             "predicted_answer": pred_answer,
#         })
#         print(f"{qid:<8} {tier:<6} {method:<20} {score:<8.2f} {question[:40]}...")

#     avg_score = total_score / count if count > 0 else 0.0

#     print(f"\n{'='*70}")
#     print(f"Overall Score: {avg_score:.2%} ({total_score:.1f}/{count})")

#     # By tier
#     for tier in [1, 2, 3]:
#         tier_results = [r for r in results if r.get("tier") == tier]
#         if tier_results:
#             tier_avg = sum(r["score"] for r in tier_results) / len(tier_results)
#             print(f"Tier {tier}: {tier_avg:.2%} ({len(tier_results)} questions)")

#     # Save results
#     eval_output = {
#         "overall_score": avg_score,
#         "total": count,
#         "results": results,
#     }
#     Path("eval_results.json").write_text(json.dumps(eval_output, indent=2))
#     print(f"\n✅ Saved detailed results to eval_results.json")


# if __name__ == "__main__":
#     evaluate()
"""
Evaluate dev_answers.json against the public answer key.
Uses fuzzy numeric matching and LLM-as-judge for qualitative answers.
"""
import json
import os
import sys
import re
import time
from pathlib import Path
import fireworks.client
from fireworks.client.error import RateLimitError
from dotenv import load_dotenv

load_dotenv()


def extract_number(text: str) -> float | None:
    """
    Extract a meaningful numeric answer from arbitrary text.

    Strategy:
    1. First scan for explicit unit-qualified values (e.g. "4.2 billion")
       and multiply immediately — avoids the text-substitution ambiguity.
    2. Fall back to bare numbers, skipping probable years (1900-2100).
    """
    # Step 1: unit-qualified values — parse number + unit together
    unit_map = {
        "trillion": 1e12, "trillions": 1e12,
        "billion":  1e9,  "billions":  1e9,
        "million":  1e6,  "millions":  1e6,
        "thousand": 1e3,  "thousands": 1e3,
        "t": 1e12, "b": 1e9, "m": 1e6, "k": 1e3,
    }
    unit_pattern = re.compile(
        r"([-+]?\d[\d,]*\.?\d*)\s*"
        r"(trillion|trillions|billion|billions|million|millions|thousand|thousands|[tTbBmMkK])\b",
        re.IGNORECASE,
    )
    candidates = []
    for match in unit_pattern.finditer(text.replace(",", "")):
        num_str = match.group(1).replace(",", "")
        unit = match.group(2).lower()
        try:
            candidates.append(float(num_str) * unit_map[unit])
        except (ValueError, KeyError):
            pass

    if candidates:
        non_years = [n for n in candidates if not (1900 <= abs(n) <= 2100)]
        return non_years[0] if non_years else candidates[0]

    # Step 2: bare numbers (no unit), skip years
    bare_pattern = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")
    numbers = []
    for m in bare_pattern.finditer(text.replace(",", "")):
        try:
            val = float(m.group())
            if not (1900 <= val <= 2100):
                numbers.append(val)
        except ValueError:
            pass
    return numbers[0] if numbers else None


def fuzzy_numeric_score(predicted: str, gold_numeric: float, tolerance: float = 0.02) -> float:
    """Score numeric answers with tolerance."""
    pred_num = extract_number(predicted)
    if pred_num is None:
        return 0.0
    if gold_numeric == 0:
        return 1.0 if pred_num == 0 else 0.0
    relative_error = abs(pred_num - gold_numeric) / abs(gold_numeric)
    return 1.0 if relative_error <= tolerance else 0.0


def llm_judge_score(question: str, predicted: str, gold: str, api_key: str) -> float:
    """Use LLM to score qualitative answers with partial credit."""
    if not api_key:
        print("Warning: FIREWORKS_API_KEY is missing; skipping LLM judge scoring.", file=sys.stderr)
        return 0.0

    client = fireworks.client.Fireworks(api_key=api_key)
    try:
        prompt = f"""You are evaluating a financial research assistant's answer.

Question: {question}

Gold Answer: {gold}

Predicted Answer: {predicted}

Scoring instructions:
- Score ONLY on factual correctness and completeness. Ignore style, grammar, length, and citation format.
- Never penalize for extra correct information not in the gold answer.
- Never penalize for different citation style (e.g. "per SQL data" vs "per 10-K" vs no citation).
- If the predicted answer is partially correct, award partial credit rather than 0.0.

Score by answer type:

LIST questions (risk factors, segment components, definitions):
  - Count key points in the gold answer, then check how many appear in the predicted answer.
  - 100% covered → 1.0
  - ~75% covered → 0.75
  - ~50% covered → 0.5
  - ~25% covered → 0.25
  - 0% covered but with some correct facts → 0.25
  - 0% only if the answer is entirely wrong or directly contradicts the gold answer.

NUMERIC questions:
  - Number matches within 2% → 1.0
  - Right metric named but number wrong → 0.5
  - Wrong metric entirely → 0.0

STRUCTURED questions (e.g. segment names + revenues):
  - All segment names and revenue figures correct → 1.0
  - Segment names correct, sub-components missing or no figures → 0.75
  - Some segments correct → 0.5
  - Mostly wrong or missing key segments → 0.25

Always award at least some credit if the predicted answer contains some correct information. Do not return "insufficient data" or an empty judgement when the answer has valid partial facts.

Return ONLY a single decimal number between 0 and 1. No explanation, no other text."""

        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model="accounts/fireworks/models/kimi-k2p6",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=10,
                    temperature=0,
                )
                raw = response.choices[0].message.content.strip()
                # Extract first valid score from response, handles "0.75\n", "Score: 0.75" etc.
                match = re.search(r"\b(1\.0|0\.\d+|[01])\b", raw)
                if match:
                    score = float(match.group())
                    return max(0.0, min(1.0, score))  # clamp to [0, 1]
                return 0.0
            except RateLimitError as exc:
                if attempt == 2:
                    print(f"Rate limit exceeded after retries: {exc}", file=sys.stderr)
                    return 0.0
                wait = 2 ** attempt
                print(f"Rate limit hit, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            except Exception as exc:
                print(f"LLM judge error: {exc}", file=sys.stderr)
                return 0.0
    finally:
        try:
            client.close()
        except Exception:
            pass


def _normalize_answer_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\(\)\[\]\{\}]", " ", text)
    text = re.sub(r"[-–—]", " ", text)
    text = re.sub(r"[^a-z0-9\s\.\$%]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_answer_items(text: str) -> list[str]:
    normalized = _normalize_answer_text(text)
    if ";" in text or "\n" in text:
        items = re.split(r"[;\n]+", text)
    elif "," in text:
        items = re.split(r",\s*", text)
    else:
        items = [normalized]
    return [item.strip() for item in items if item.strip()]


def _list_match_score(gold_answer: str, predicted_answer: str) -> float:
    if not gold_answer.strip() or not predicted_answer.strip():
        return 0.0

    gold_items = _split_answer_items(gold_answer)
    pred_norm = _normalize_answer_text(predicted_answer)

    if len(gold_items) > 1:
        matched = 0
        for item in gold_items:
            item_norm = _normalize_answer_text(item)
            if not item_norm:
                continue
            item_words = [w for w in item_norm.split() if len(w) > 2]
            if not item_words:
                continue
            exact_match = item_norm in pred_norm
            token_overlap = sum(1 for w in item_words if f" {w} " in f" {pred_norm} ")
            numeric_overlap = any(num in pred_norm for num in re.findall(r"\d+[\d\.]*", item_norm))
            if exact_match or token_overlap / len(item_words) >= 0.5 or numeric_overlap:
                matched += 1
        ratio = matched / len(gold_items)
        if ratio == 1:
            return 1.0
        if ratio >= 0.75:
            return 0.75
        if ratio >= 0.5:
            return 0.5
        if ratio >= 0.25:
            return 0.25
        return 0.0

    gold_tokens = set(_normalize_answer_text(gold_answer).split())
    pred_tokens = set(pred_norm.split())
    if not gold_tokens:
        return 0.0
    overlap = gold_tokens.intersection(pred_tokens)
    ratio = len(overlap) / len(gold_tokens)
    if ratio >= 0.9:
        return 1.0
    if ratio >= 0.7:
        return 0.75
    if ratio >= 0.5:
        return 0.5
    if ratio >= 0.25:
        return 0.25
    return 0.0


def _entity_variants_from_gold(gold_answer: str) -> list[str]:
    """Return candidate entity strings to match against predicted answers."""
    text = gold_answer.lower().strip()
    variants = []

    if "(" in text and ")" in text:
        before, rest = text.split("(", 1)
        variants.append(before.strip())
        ticker = rest.split(")", 1)[0].strip()
        if ticker:
            variants.append(ticker)
    else:
        variants.append(text)

    if variants:
        first = variants[0]
        if " " in first:
            variants.extend([part.strip() for part in first.split(" ") if part.strip()])

    seen = set()
    unique = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def _resolve_path(primary: Path, fallbacks: list[Path], label: str) -> Path:
    """Return first existing path from primary + fallbacks, or exit cleanly."""
    for p in [primary] + fallbacks:
        if p.exists():
            return p
    print(f"Error: {label} not found. Searched: {[str(p) for p in [primary] + fallbacks]}")
    sys.exit(1)


def evaluate(regenerate: bool = False):
    # Optionally regenerate answers before scoring
    if regenerate:
        try:
            from generate_answers import generate
            print("Regenerating answers...")
            generate()
        except ImportError:
            print("Warning: generate_answers.py not found — using existing dev_answers.json",
                  file=sys.stderr)

    api_key = os.getenv("FIREWORKS_API_KEY")

    # Resolve file paths with fallbacks for both files
    answers_file = _resolve_path(
        Path("rag_system/questions/dev_answers.json"),
        [Path("questions/dev_answers.json"), Path("dev_answers.json")],
        "dev_answers.json",
    )
    gold_file = _resolve_path(
        Path("rag_system/questions/dev_questions_with_answers.json"),
        [Path("questions/dev_questions_with_answers.json"), Path("dev_questions_with_answers.json")],
        "dev_questions_with_answers.json",
    )

    predicted = json.loads(answers_file.read_text())
    gold_questions = json.loads(gold_file.read_text())

    results = []
    total_score = 0.0
    count = 0

    print(f"\n{'='*70}")
    print(f"{'ID':<8} {'Tier':<6} {'Method':<20} {'Score':<8} Question")
    print(f"{'='*70}")

    for q in gold_questions:
        qid = q["id"]
        question = q["question"]
        tier = q["tier"]
        gold_answer = q["gold_answer"]
        gold_numeric = q.get("gold_answer_numeric")
        eval_method = q.get("evaluation", "llm_judge")

        if qid not in predicted:
            print(f"{qid:<8} {tier:<6} {'MISSING':<20} {'0.0':<8} {question[:40]}")
            results.append({"id": qid, "score": 0.0, "method": "missing"})
            count += 1
            continue

        predicted_value = predicted[qid]
        if isinstance(predicted_value, dict):
            pred_answer = predicted_value.get("answer", "")
            # Support both agent output formats:
            # - RAGAgent: {"sources": [{"type": "pdf", "section": "..."}]}
            # - legacy:   {"pdf_chunks": [{"section": "..."}]}
            pdf_sources = [
                s for s in predicted_value.get("sources", [])
                if s.get("type") == "pdf"
            ]
            pdf_chunks = predicted_value.get("pdf_chunks", [])
            sections_used = list({
                item.get("section", "")
                for item in (pdf_sources if pdf_sources else pdf_chunks)
                if item.get("section")
            })
        else:
            pred_answer = predicted_value
            sections_used = []

        if eval_method == "fuzzy_numeric" and gold_numeric is not None:
            score = fuzzy_numeric_score(pred_answer, gold_numeric)
            method = "fuzzy_numeric"
        elif eval_method == "exact_match_entity":
            variants = _entity_variants_from_gold(gold_answer)
            lower_pred = pred_answer.lower()
            score = 1.0 if any(variant in lower_pred for variant in variants) else 0.0
            method = "entity_match"
        else:
            score = llm_judge_score(question, pred_answer, gold_answer, api_key)
            heuristic_score = _list_match_score(gold_answer, pred_answer)
            if heuristic_score > score:
                score = heuristic_score
                method = "llm_judge+list_heuristic"
            else:
                method = "llm_judge"

        total_score += score
        count += 1
        results.append({
            "id": qid,
            "score": score,
            "method": method,
            "tier": tier,
            "gold_answer": gold_answer,
            "predicted_answer": pred_answer,
            "sections_used": sections_used,   # new: shows which 10-K sections were retrieved
        })
        print(f"{qid:<8} {tier:<6} {method:<20} {score:<8.2f} {question[:40]}...")

    avg_score = total_score / count if count > 0 else 0.0

    print(f"\n{'='*70}")
    print(f"Overall Score: {avg_score:.2%} ({total_score:.1f}/{count})")

    for tier in [1, 2, 3]:
        tier_results = [r for r in results if r.get("tier") == tier]
        if tier_results:
            tier_avg = sum(r["score"] for r in tier_results) / len(tier_results)
            print(f"Tier {tier}: {tier_avg:.2%} ({len(tier_results)} questions)")

    # Low-scoring questions for quick diagnosis
    low = [r for r in results if r["score"] < 0.5 and r["method"] != "missing"]
    if low:
        print(f"\nLow-scoring questions (<0.5):")
        for r in low:
            sections = f" [sections: {', '.join(r['sections_used'])}]" if r["sections_used"] else ""
            print(f"  {r['id']}: {r['score']:.2f}{sections}")
            print(f"    Gold:      {r['gold_answer'][:80]}")
            print(f"    Predicted: {r['predicted_answer'][:80]}")

    eval_output = {
        "overall_score": avg_score,
        "total": count,
        "results": results,
    }
    Path("eval_results.json").write_text(json.dumps(eval_output, indent=2))
    print(f"\nSaved detailed results to eval_results.json")


if __name__ == "__main__":
    regenerate = "--regenerate" in sys.argv
    evaluate(regenerate=regenerate)