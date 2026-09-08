#!/usr/bin/env python3
import re
from pathlib import Path


def sync_tasks():
    tasks_dir = Path("memory-bank/tasks")
    tasks_md_path = Path("memory-bank/tasks.md")

    if not tasks_dir.exists():
        print(f"Error: {tasks_dir} does not exist.")
        return

    tasks = []
    # Sort by number descending for "All Tasks"
    task_files = sorted(tasks_dir.glob("TASK-*.md"),
                        key=lambda x: int(re.search(r"TASK-(\d+)", x.name).group(1)),
                        reverse=True)

    for task_file in task_files:
        content = task_file.read_text()

        # Extract ID and Title from first line
        first_line = content.splitlines()[0]
        match = re.search(r"# (TASK-\d+): (.*)", first_line)
        if not match:
            continue
        task_id = match.group(1)
        task_title = match.group(2).strip()

        # Extract metadata
        status_match = re.search(r"\*\*Status\*\*: (.*)", content)
        status = status_match.group(1).strip() if status_match else "UNKNOWN"

        feature_match = re.search(r"\*\*Feature\*\*: (.*)", content)
        feature = feature_match.group(1).strip() if feature_match else "N/A"

        # Map Status to Phase
        if "REFLECTION" in status:
            phase = "REFLECT"
        elif "BUILD" in status or "PROGRESS" in status:
            phase = "BUILD"
        elif status == "COMPLETE":
            phase = "ARCHIVE"
        elif "PLAN" in status or status == "INITIALIZED":
            phase = "PLAN"
        else:
            phase = "UNKNOWN"

        tasks.append({
            "id": task_id,
            "title": task_title,
            "phase": phase,
            "status": status,
            "feature": feature
        })

    # Prepare tables
    active_tasks = [t for t in tasks if t["status"] != "COMPLETE"]
    # Sort active tasks by ID ascending
    active_tasks.sort(key=lambda t: int(re.search(r"TASK-(\d+)", t["id"]).group(1)))

    # Sort all tasks by ID descending
    all_tasks = sorted(tasks, key=lambda t: int(re.search(r"TASK-(\d+)", t["id"]).group(1)), reverse=True)

    def format_table(task_list):
        lines = ["| ID | Task | Phase | Status | Feature |", "|----|------|-------|--------|---------|"]
        for t in task_list:
            lines.append(f"| {t['id']} | {t['title']} | {t['phase']} | {t['status']} | {t['feature']} |")
        return "\n".join(lines)

    new_content = f"""# Active Tasks

{format_table(active_tasks)}

---

## All Tasks

{format_table(all_tasks)}
"""

    tasks_md_path.write_text(new_content)
    print(f"Successfully synced {len(tasks)} tasks to {tasks_md_path}")

if __name__ == "__main__":
    sync_tasks()
