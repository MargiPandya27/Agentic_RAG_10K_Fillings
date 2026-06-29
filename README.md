# Agentic RAG for 10-K Analysis

This project is a local agentic RAG system I built to answer questions over 10-K filings and structured financial data.

I wanted to keep the setup simple to run locally, while still showing the parts that matter: routing, evidence gathering, and grounded answers.

## What I Focused On

1. Routing questions to SQL, PDFs, or both.
2. Keeping answers grounded in the source data.
3. Making the system easy to run and inspect locally.
4. Being explicit about evaluation and trade-offs.
5. Writing down the implementation clearly enough that I could revisit it later.

## Project Context

I used the provided 10-K filings, SQLite database, and dev questions as the basis for the project.

The system is meant to handle questions that require:

- decide when to query the SQLite database versus the filings
- gather evidence from the right sources
- answer questions that range from direct lookup to multi-step synthesis
- stay grounded in the provided documents and data

The provided data includes:

- six 10-K filings for Apple, Microsoft, and Alphabet across FY2024 and FY2025
- a local SQLite database with structured financial data
- a 10-question development set

That combination made it a good fit for a small personal project where I could experiment with retrieval, agent routing, and evaluation without needing a large production stack.

## Project Structure

- `data/`: generated or provided assignment data, including the SQLite DB and 10-K PDFs
- `questions/`: the development-set questions, public dev answer key, and the `dev_answers.json` example template
- `scripts/`: helper scripts that can fetch the SEC source data, render PDFs, and build `financials.db`
- `starter/`: lightweight starter dependencies for setup and experimentation
- `setup.sh`: end-to-end local setup script

## What You Receive

- `questions/dev_questions.json`: 10 development-set questions
- `questions/dev_questions_with_answers.json`: the public dev-set answer key
- `questions/dev_answers_example.json`: template for your `dev_answers.json`
- `setup.sh`: local bootstrap script
- `starter/requirements.txt`: setup and starter dependencies
- `scripts/`: scripts that can fetch or rebuild the data if it is not already present

If `data/financials.db` and the 10-K PDFs are already present, `setup.sh` will reuse them. It only fetches SEC data if it needs to rebuild missing assets.

The dev-set answer key is public so you can evaluate your system locally. I intentionally did not include an evaluation harness; part of the exercise is deciding how to measure correctness against the provided questions, answers, and data. A separate held-out set is used for the hidden final evaluation.

## Data Overview

The SQLite database includes these tables:

- `companies`: company metadata
- `income_statements`: revenue, gross profit, operating income, net income, EPS, and R&D
- `balance_sheets`: assets, liabilities, equity, cash, debt, and current balance metrics
- `segment_revenue`: revenue by business segment
- `geographic_revenue`: revenue by geography

The filings provide the narrative context needed for questions about risks, strategy, segment definitions, geographic commentary, and management discussion.
