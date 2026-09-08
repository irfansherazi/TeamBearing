# jira-attachment-support-and-vision-integration Algorithm Design: Jira Attachment Selection & Prioritization

**Created**: 2026-05-20
**Task**: jira-attachment-support-and-vision-integration
**Feature**: FEAT-045
**Phase**: CREATIVE — Algorithm Design
**Status**: COMPLETE

---

## Decision

**Chosen**: Option A — Recency-Based High-Value Filtering

The agent will use a rule-based filtering and prioritization algorithm to select the most relevant image attachments for vision analysis. This minimizes token cost and latency while maximizing the probability of extracting useful visual context.

---

## Selection Algorithm

### Step 1: Candidate Filtering
Iterate through the `attachments` list from the Jira ticket and apply the following filters:

| Filter | Criteria | Action if Failed |
|---|---|---|
| **MimeType** | Must be in `['image/png', 'image/jpeg', 'image/webp']` | Exclude (Skip PDFs/Logs) |
| **Size** | Must be `< 10 MB` | Exclude (Avoid Timeout/Cost) |
| **Filename** | Exclude files containing `thumbnail` or `icon` | Exclude (Low context) |

### Step 2: Prioritization
If the number of candidates exceeds `MAX_ATTACHMENTS_ANALYZED` (default: 3), sort the candidates by:
1. **Creation Date**: Descending (Newest first).
2. **Size**: Ascending (Smaller files are often more focused screenshots).

### Step 3: Execution Logic
```python
def select_attachments(attachments: list[dict], max_count: int = 3) -> list[dict]:
    candidates = [
        a for a in attachments 
        if a["mimeType"] in SUPPORTED_IMAGE_TYPES
        and a["size"] < MAX_IMAGE_SIZE
        and not is_noise_file(a["filename"])
    ]
    
    # Sort by created desc, then size asc
    candidates.sort(key=lambda x: (x["created"], -x["size"]), reverse=True)
    
    return candidates[:max_count]
```

---

## Vision Prompt Optimization

To ensure high signal-to-noise ratio in the vision analysis, the prompt is dynamically constructed:

### Prompt Template
```
System:
You are a Senior QA Automation Engineer. Your goal is to extract visual grounding 
data from this Jira attachment to help write a test plan.

Focus on:
1. Exact text of buttons, links, and dropdowns.
2. Layout relationship (e.g., "The 'Save' button is inside the 'Header' component").
3. Field names in forms.

User:
[Image]
Context: These are the Acceptance Criteria for the feature:
{ac_text}

Analyze the image and provide 3-5 concise bullet points of visual facts that 
specifically help clarify the terms or workflows mentioned in the AC.
```

---

## Error & Edge Case Handling

| Scenario | Behavior |
|---|---|
| **Zero Image Attachments** | Graceful NO-OP. `visual_context` remains empty string. |
| **Download Failure** | Log `WARNING`, skip file, proceed with remaining. |
| **Vision LLM Timeout** | Log `WARNING`, skip analysis for that file. |
| **Nonsensical Image** | If LLM returns "I cannot see anything useful", skip injection. |
| **Non-Image High-Value (PDF)** | **Phase 2 Expansion**: Use Bedrock's PDF support (if available) or skip. |

---

## Performance Targets

- **Filtering & Selection**: < 10ms (Local CPU).
- **Parallel Downloads**: < 1s (Assuming 3 images @ 500KB each).
- **Parallel Vision Calls**: < 3s (Bedrock standard latency).
- **Total Overhead**: < 5s added to the parsing stage.
