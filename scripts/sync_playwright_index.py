import json
import re
from pathlib import Path


def sync_playwright_index():
    # Paths relative to project root
    tests_dir = Path("playwright/tests")
    index_file = Path("playwright/playwright_index.json")

    results = []

    # Regex to find JIRA keys like QA-125 or VC2-8821
    # We restrict to uppercase and numbers followed by hyphen and numbers
    jira_pattern = re.compile(r'\b([A-Za-z][A-Za-z0-9]+-[0-9]+)\b')

    # Regex for test.describe and test(...)
    describe_pattern = re.compile(r"test\.describe\(\s*['\"]([^'\"]+)['\"]")
    test_pattern = re.compile(r"\btest\(\s*['\"]([^'\"]+)['\"]")

    if not tests_dir.exists():
        print(f"Error: {tests_dir} does not exist.")
        return

    test_files = list(tests_dir.rglob("*.test.ts"))
    # Only include tests whose basename begins with a JIRA-style prefix
    # (qa- or vc2-, case-insensitive). Filters out diagnostic/utility tests
    # (debug.test.ts, webkit-*.test.ts, verify-login.test.ts, etc.) and unit
    # tests (unit/*.test.ts) that aren't part of the regression suite.
    test_files = [f for f in test_files if f.name.lower().startswith(("qa-", "vc2-"))]
    test_files = sorted(test_files)

    for file_path in test_files:
        try:
            content = file_path.read_text(encoding='utf-8')

            # Extract JIRA keys from file name and content
            raw_keys = jira_pattern.findall(file_path.name) + jira_pattern.findall(content)
            jira_keys = set(k.upper() for k in raw_keys)

            # Extract description from first test.describe
            description_match = describe_pattern.search(content)
            description = description_match.group(1) if description_match else ""

            # Count test(...) calls
            steps = test_pattern.findall(content)
            steps_count = len(steps)

            # If no description from test.describe, fall back to the first
            # test(...) title. A first-line // comment is unreliable — files
            # frequently open with an unrelated comment (TODOs, quarantine
            # notices, inline helper docstrings), which would otherwise get
            # promoted to the test's display name.
            if not description and steps:
                description = steps[0]

            results.append({
                "id": file_path.stem,
                "file": file_path.relative_to("playwright").as_posix(),
                "jira_keys": sorted(list(jira_keys)),
                "description": description,
                "steps_count": steps_count,
                "step_names": steps
            })
        except Exception as e:
            print(f"Skipping {file_path}: {e}")

    # Sort results by ID for stability
    results.sort(key=lambda x: x["id"])

    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    print(f"[OK] Synced {len(results)} tests to {index_file}")

if __name__ == "__main__":
    sync_playwright_index()
