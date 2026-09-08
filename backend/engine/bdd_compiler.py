"""
vQA — Pre-Flight BDD Compiler (Multi-Actor)
===========================================
Module: backend/engine/bdd_compiler.py

This module implements the Layer 1 Pre-Flight BDD Compiler which scans raw 
JIRA tickets for multi-actor collaboration keywords and compiles them into 
structured MultiActorTestPlans.

It uses a two-stage process:
1. ChromaDB RAG: Look up similar successful plans.
2. LLM Compilation: Use Tier 1 Flash to compile new plans if RAG misses.
"""

import json
import logging
import re
from typing import Optional, List

from langchain_core.messages import SystemMessage
from backend.engine.schemas import MultiActorTestPlan
from backend.engine.prompts import BDD_COMPILER_PROMPT
from backend.kb.rag import test_plan_vault
from backend.config import settings

logger = logging.getLogger(__name__)

# Keywords that indicate a multi-actor scenario
MULTI_ACTOR_KEYWORDS = [
    r"\bshares?\b",
    r"\binvites?\b",
    r"\bcollaborat(e|or|ion)\b",
    r"\breceives?\b",
    r"\bswitch(es)? (to|persona|actor)\b",
    r"\bpersona\b",
    r"\bowner\b",
    r"\bviewer\b",
    r"\beditor\b",
    r"\brevokes?\b",
    r"\baccess\b",
]

def is_multi_actor_scenario(text: str) -> bool:
    """
    Detect if a JIRA ticket likely involves multiple actors based on keywords.
    """
    if not text:
        return False
        
    pattern = "|".join(MULTI_ACTOR_KEYWORDS)
    return bool(re.search(pattern, text, re.IGNORECASE))

def _get_compiler_llm(max_tokens: int = 4096):
    """Factory for the compiler LLM (Tier 1 Flash)."""
    from backend.llm import get_llm
    return get_llm("parser", max_tokens=max_tokens)

async def compile_multi_actor_plan(ticket_text: str, run_id: str = "unknown") -> MultiActorTestPlan:
    """
    Use Tier 1 Flash to compile raw JIRA text into a MultiActorTestPlan.
    """
    llm = _get_compiler_llm()
    
    # In a real scenario, we might inject blueprints from RAG here
    system_prompt = BDD_COMPILER_PROMPT.format(
        ticket_text=ticket_text,
        blueprints="(no similar blueprints found)"
    )
    
    messages = [SystemMessage(content=system_prompt)]
    
    logger.info("[%s] Compiling multi-actor test plan via LLM...", run_id)
    response = await llm.ainvoke(messages)
    
    raw_text = response.content.strip()
    
    # Strip markdown fences
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        
    try:
        parsed = json.loads(raw_text)
        plan = MultiActorTestPlan.model_validate(parsed)
        logger.info("[%s] Successfully compiled multi-actor plan: %s", run_id, plan.test_title)
        return plan
    except Exception as e:
        logger.error("[%s] Failed to compile multi-actor plan: %s", run_id, e)
        raise ValueError(f"Multi-actor compilation failed: {e}")

async def get_preflight_plan(ticket_text: str, run_id: str = "unknown") -> Optional[MultiActorTestPlan]:
    """
    Orchestrate the pre-flight BDD compilation:
    1. Check if multi-actor.
    2. Try RAG retrieval from TestPlanVault.
    3. Fallback to LLM compilation.
    """
    if not is_multi_actor_scenario(ticket_text):
        logger.info("[%s] Scenario does not appear to be multi-actor. Skipping pre-flight.", run_id)
        return None
        
    # 1. RAG Retrieval
    try:
        similar_plans = test_plan_vault.query_plans(ticket_text, n_results=1)
        if similar_plans:
            # For now, we take the first one. 
            # In a real scenario, we'd check a similarity threshold.
            logger.info("[%s] RAG HIT: Found similar multi-actor plan in vault.", run_id)
            return similar_plans[0]
    except Exception as e:
        logger.warning("[%s] RAG retrieval failed: %s", run_id, e)
        
    # 2. LLM Compilation Fallback
    return await compile_multi_actor_plan(ticket_text, run_id)
