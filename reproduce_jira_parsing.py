
import asyncio
import json
import logging
from typing import Any
from backend.jira.client import _extract_text_from_adf, fetch_ticket_context
from backend.engine.ac_parser import _stage_1_normalize, _stage_2_compile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock ADF content for QA-239 (based on common issues with complex ADF)
# QA-239: "Jira Card descriptions are not getting parsed into Acceptance Criteria/Testing steps"
# Link: https://vcreative.atlassian.net/jira/software/c/projects/QA/boards/36?search=239&selectedIssue=QA-239
# Note: Since I can't access real Jira, I will simulate a "messy" ADF structure.

MOCK_QA_239_ADF = {
    "type": "doc",
    "version": 1,
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "Acceptance Criteria"}]
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "1. User should be able to log in as "},
                {"type": "text", "text": "Account Executive", "marks": [{"type": "strong"}]},
                {"type": "text", "text": "."}
            ]
        },
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Navigate to the dashboard."}]
                        }
                    ]
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Verify the "},
                                {"type": "text", "text": "Quick Order", "marks": [{"type": "code"}]},
                                {"type": "text", "text": " button is present."}
                            ]
                        }
                    ]
                }
            ]
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Attachments:"}]
        },
        {
            "type": "mediaSingle",
            "attrs": {"layout": "center"},
            "content": [
                {
                    "type": "media",
                    "attrs": {
                        "id": "12345",
                        "type": "file",
                        "collection": "contentId-239",
                        "filename": "screenshot-1.png"
                    }
                }
            ]
        }
    ]
}

async def reproduce_parsing():
    print("--- Testing ADF Extraction ---")
    extracted_text = _extract_text_from_adf(MOCK_QA_239_ADF)
    print(f"Extracted Text:\n{extracted_text}")
    print("-" * 30)

    print("\n--- Testing Stage 1 BDD Normalization ---")
    # Simulate the context that ac_parser_node would have
    summary = "Fix Jira Card Parsing"
    description = extracted_text
    run_id = "test-run-123"
    
    try:
        bdd_text = await _stage_1_normalize(
            raw_ac=extracted_text,
            summary=summary,
            description=description,
            run_id=run_id
        )
        print(f"BDD Text:\n{bdd_text}")
    except Exception as e:
        print(f"Stage 1 Failed: {e}")
        return

    print("-" * 30)
    print("\n--- Testing Stage 2 JSON Compilation ---")
    try:
        test_plan = await _stage_2_compile(bdd_text, run_id)
        print(f"Test Plan Title: {test_plan.test_title}")
        print(f"Steps Count: {len(test_plan.steps)}")
        for step in test_plan.steps:
            print(f"  Step {step.step_id}: {step.goal} ({step.step_type})")
    except Exception as e:
        print(f"Stage 2 Failed: {e}")

if __name__ == "__main__":
    asyncio.run(reproduce_parsing())
