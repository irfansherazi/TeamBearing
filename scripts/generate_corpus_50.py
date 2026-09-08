#!/usr/bin/env python3
"""
Generate Benchmark Corpus (corpus_50.json) from Jira CSV
=========================================================
Reads the first 50 rows of Jira (2).csv, extracts summaries and descriptions,
and uses Claude via AWS Bedrock to synthesize structured Acceptance Criteria and
Given/When/Then steps. Falls back to deterministic regex parsing if LLM is unavailable.
"""

import asyncio
import csv
import json
import logging
import os
import re
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.llm import get_llm
from langchain_core.messages import HumanMessage, SystemMessage

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CSV_PATH = "/Users/joshschauer/Documents/vProMedia/vQA/Jira (2).csv"
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "tests/benchmarks/corpus_50.json")

SYSTEM_PROMPT = """You are an expert QA Automation Engineer.
Given a Jira ticket's Title and Description, you must synthesize:
1. High-quality Acceptance Criteria (a clear numbered list of key functional check points).
2. Given/When/Then expected BDD steps that can be run in our Playwright-based engine.

You must respond with a single, valid JSON object in strict format with exactly two keys:
{
  "acceptance_criteria": "1. ...\\n2. ...\\n3. ...",
  "expected_steps": [
    "Given ...",
    "When ...",
    "And ...",
    "Then ..."
  ]
}

Ensure:
- "acceptance_criteria" is a formatted string with line breaks.
- "expected_steps" is an array of clean string steps matching standard BDD format.
- No markdown fences (like ```json), no preambles, and no extra explanation. Return ONLY the raw JSON string.
"""

def heuristic_parse(summary: str, description: str) -> dict:
    """
    Deterministic fallback parser that extracts key items from the description.
    """
    lines = [line.strip() for line in description.split("\n") if line.strip()]
    
    # Extract bullets / numbers
    bullet_lines = []
    for line in lines:
        if line.startswith(("*", "-", "##", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            clean = re.sub(r"^[\*\-#\d\.\s\[\]x]+", "", line).strip()
            if clean and len(clean) > 5:
                bullet_lines.append(clean)
                
    if not bullet_lines:
        bullet_lines = [line for line in lines if len(line) > 12][:4]
        
    ac_lines = [f"{i+1}. {item}" for i, item in enumerate(bullet_lines)]
    acceptance_criteria = "\n".join(ac_lines) if ac_lines else f"1. Verify {summary} functionality works as expected."
    
    expected_steps = [
        "Given the user is logged in as an Account Executive",
        f"When the user navigates to the feature for {summary}"
    ]
    for item in bullet_lines[:3]:
        # limit length of step
        step_desc = item[:60] + "..." if len(item) > 63 else item
        expected_steps.append(f"And the user verifies: {step_desc}")
    expected_steps.append(f"Then the system confirms {summary} is successful")
    
    return {
        "acceptance_criteria": acceptance_criteria,
        "expected_steps": expected_steps
    }

async def generate_card_data(sem, llm, ticket_id: str, summary: str, description: str) -> dict:
    """
    Generate structured AC and expected steps for a single ticket, using LLM with heuristic fallback.
    """
    async with sem:
        # Construct message content
        user_content = f"Title: {summary}\nDescription:\n{description}"
        
        logger.info(f"Processing ticket {ticket_id}...")
        try:
            # Call the LLM
            response = await llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_content)
            ])
            
            raw_text = response.content.strip()
            
            # Clean potential markdown fences
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                raw_text = raw_text.strip()
            if raw_text.startswith("json"):
                raw_text = raw_text[4:].strip()
                
            data = json.loads(raw_text)
            
            if "acceptance_criteria" in data and "expected_steps" in data:
                logger.info(f"✅ Successfully parsed {ticket_id} with LLM.")
                return {
                    "ticket_id": ticket_id,
                    "summary": summary,
                    "description": description,
                    "acceptance_criteria": data["acceptance_criteria"],
                    "expected_steps": data["expected_steps"]
                }
            else:
                raise ValueError("Missing required keys in LLM JSON response.")
                
        except Exception as e:
            logger.warning(f"⚠️ LLM failed for {ticket_id}: {str(e)}. Falling back to heuristic parsing.")
            fallback = heuristic_parse(summary, description)
            return {
                "ticket_id": ticket_id,
                "summary": summary,
                "description": description,
                "acceptance_criteria": fallback["acceptance_criteria"],
                "expected_steps": fallback["expected_steps"]
            }

async def main():
    if not os.path.exists(CSV_PATH):
        logger.error(f"Jira CSV file not found at {CSV_PATH}")
        sys.exit(1)
        
    # Read the first 50 rows
    candidates = []
    with open(CSV_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        for r in reader:
            if len(r) > 28:
                key = r[1]
                summary = r[0]
                desc = r[28]
                if key and summary and desc.strip():
                    candidates.append((key, summary, desc))
                    if len(candidates) >= 50:
                        break
                        
    logger.info(f"Loaded {len(candidates)} tickets from CSV. Starting structured generation...")
    
    # Initialize LLM
    try:
        llm = get_llm("parser", max_tokens=2048)
    except Exception as e:
        logger.error(f"Failed to initialize LLM provider: {str(e)}")
        sys.exit(1)
        
    # Limit concurrency to avoid Bedrock rate limits
    sem = asyncio.Semaphore(5)
    
    tasks = [
        generate_card_data(sem, llm, key, summary, desc)
        for key, summary, desc in candidates
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Save output corpus
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        json.dump(results, out, indent=2, ensure_ascii=False)
        
    logger.info(f"🎉 Successfully generated corpus with {len(results)} items and saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
