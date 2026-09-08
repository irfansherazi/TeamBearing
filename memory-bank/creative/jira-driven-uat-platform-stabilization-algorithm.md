# Algorithms: jira-driven-uat-platform-stabilization Jira-Driven UAT Platform Stabilization

**Task**: jira-driven-uat-platform-stabilization / FEAT-106  
**Date**: 2026-06-05  
**Author**: Creative Design Agent

---

## 1. Multi-Signal Stagnant UI Detection Algorithm

To prevent false positives from localized DOM shifts (e.g. cursor blinks, loading spinners), the system computes a composite **UI Delta Score** ($S_{delta}$) based on four normalized signals.

### Mathematical Formulation
Let the composite score be defined as:
$$S_{delta} = w_{url} \cdot D_{url} + w_{count} \cdot D_{count} + w_{aria} \cdot D_{aria} + w_{overlay} \cdot D_{overlay}$$

Where:
* $D_{url} \in \{0, 1\}$: $1$ if URL or hash changed, $0$ otherwise.
* $D_{count} \in [0, 1]$: Normalized element count diff: $\min\left(1.0, \frac{|C_{pre} - C_{post}|}{\max(1, C_{pre})}\right)$.
* $D_{aria} \in [0, 1]$: Levenshtein distance normalized by length between pre- and post-action serialized ARIA trees.
* $D_{overlay} \in \{-1, 0\}$: Penalty modifier. If a known active blocking overlay is detected post-action (e.g., PrimeNG loading modal), $D_{overlay} = -1.0$, which dampens structural changes.
* Weights are set as: $w_{url} = 0.50$, $w_{count} = 0.15$, $w_{aria} = 0.35$.

### Threshold Gate
If $S_{delta} < 0.05$ (meaning less than 5% total change and no URL navigation occurred), the UI is classified as **STAGNANT**.

### Pseudo-Code
```python
def compute_ui_delta(pre_state: dict, post_state: dict) -> float:
    # 1. URL Delta
    d_url = 1.0 if pre_state["url"] != post_state["url"] else 0.0
    
    # 2. Element Count Delta
    c_pre, c_post = pre_state["element_count"], post_state["element_count"]
    d_count = min(1.0, abs(c_pre - c_post) / max(1, c_pre))
    
    # 3. ARIA Tree Delta (String representation Levenshtein)
    aria_pre, aria_post = pre_state["aria_tree"], post_state["aria_tree"]
    max_len = max(1, len(aria_pre), len(aria_post))
    lev_dist = levenshtein_distance(aria_pre, aria_post)
    d_aria = lev_dist / max_len
    
    # 4. Overlay penalty
    d_overlay = -1.0 if post_state["has_blocking_overlay"] else 0.0
    
    # Weights
    w_url, w_count, w_aria = 0.50, 0.15, 0.35
    
    # Composite Score
    score = (w_url * d_url) + (w_count * d_count) + (w_aria * d_aria)
    if d_overlay == -1.0:
        score = max(0.0, score - 0.30) # Apply overlay dampening
        
    return score
```

---

## 2. A11y Tree Pruning & Playwright Role-Mapping Algorithm

The `a11y_discovery.py` module parses raw Chromium accessibility snapshots and filters noise to extract interactive targets.

### Tree Pruning Strategy
The accessibility snapshot contains static text, layout groups, and generic elements. The pruning algorithm retains only interactive elements based on:
1. Interactive roles: `button`, `textbox`, `checkbox`, `combobox`, `link`, `menuitem`, `tab`, `radio`.
2. Interactive states: Elements that have `focusable: true`, are not `disabled: true`, and have non-empty semantic names.

### Playwright getByRole Mapping
Pruned interactive nodes are mapped to Playwright locator instructions using the following translation dictionary:

```
[Role]       ->  [Playwright Locator API Method]
-----------------------------------------------------------
button       ->  page.getByRole("button", { name: "..." })
textbox      ->  page.getByRole("textbox", { name: "..." })
checkbox     ->  page.getByRole("checkbox", { name: "..." })
combobox     ->  page.getByRole("combobox", { name: "..." })
link         ->  page.getByRole("link", { name: "..." })
```

### Pseudo-Code
```python
def prune_and_map_a11y_tree(raw_snapshot: dict) -> list:
    interactive_elements = []
    
    def traverse(node):
        role = node.get("role")
        name = node.get("name", "").strip()
        focusable = node.get("focusable", False)
        disabled = node.get("disabled", False)
        
        # Interactive elements matching criterion
        if role in ["button", "textbox", "checkbox", "combobox", "link"] and focusable and not disabled:
            if name:
                interactive_elements.append({
                    "role": role,
                    "name": name,
                    "locator": f'page.getByRole("{role}", {{"name": "{name}"}})'
                })
        
        # Recurse children
        for child in node.get("children", []):
            traverse(child)
            
    traverse(raw_snapshot)
    return interactive_elements
```

---

## 3. A11y-Powered Self-Healing Logic (Category 2 & 6 Retry Loop)

When a Playwright execution step fails, the self-healing driver catches the error, inspects browser telemetry, and applies corrective actions.

### Flowchart
```
                Playwright Step Fails
                         │
                         ▼
             Inspect Exception Message
               /                   \
        [Is TIMEOUT?]         [Is ELEMENT NOT FOUND?]
              /                       \
             ▼                         ▼
      Category 2: Timing       Category 6: Interaction Shift
             │                         │
             ▼                         ▼
    Check for Active Loaders     Capture Fresh A11y Tree
             │                         │
             ▼                         ▼
    Delay + Incremental Wait    Fuzzy Match Role/Name Similarity
             │                         │
             ▼                         ▼
         Retry Step               Rewrite Locator & Retry
```

### Fuzzy Selector Matching Metric
For Category 6 (Interaction Shifts), we compute a **Match Similarity Score** ($S_{sim}$) between the original intended element target ($T_{orig}$) and every element ($E_{cand}$) in the fresh A11y Tree.

Let $T_{orig} = (R_{orig}, N_{orig})$ and $E_{cand} = (R_{cand}, N_{cand})$ where $R$ is role and $N$ is name.
$$S_{sim} = \begin{cases} 
0.0 & \text{if } R_{orig} \neq R_{cand} \\
\text{JaroWinkler}(N_{orig}, N_{cand}) & \text{if } R_{orig} = R_{cand}
\end{cases}$$

The candidate with the highest similarity score $S_{sim} \geq 0.70$ is selected as the self-healed target.

### Pseudo-Code
```python
def resolve_interaction_change(target_role: str, target_name: str, fresh_a11y_elements: list) -> str:
    best_candidate = None
    best_score = 0.0
    
    for cand in fresh_a11y_elements:
        if cand["role"] == target_role:
            score = jaro_winkler_similarity(target_name, cand["name"])
            if score > best_score:
                best_score = score
                best_candidate = cand
                
    if best_score >= 0.70:
        return best_candidate["locator"]
    raise Exception("Self-healing failed to find a structurally similar element on the current viewport.")
```
