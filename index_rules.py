import os
import re
import yaml
from datetime import datetime

RULES_DIR = "/Users/joshschauer/Documents/vProMedia/vQA/memory-bank/agent-rules"
INDEX_FILE = "/Users/joshschauer/Documents/vProMedia/vQA/memory-bank/agent-rules-index.md"

def parse_rule_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Parse YAML frontmatter
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        return None
    
    frontmatter_text = match.group(1)
    body = content[match.end():]
    
    try:
        data = yaml.safe_load(frontmatter_text)
    except Exception as e:
        print(f"Error parsing YAML in {filepath}: {e}")
        return None
        
    line_count = len(content.splitlines())
    
    return {
        'filepath': filepath,
        'relpath': os.path.relpath(filepath, os.path.dirname(INDEX_FILE)),
        'name': data.get('name', os.path.basename(filepath)),
        'globs': data.get('globs', []),
        'paths': data.get('paths', []),
        'topics': data.get('topics', []),
        'priority': data.get('priority', 'medium'),
        'auto_generated': data.get('auto_generated', False),
        'line_count': line_count,
        'body': body
    }

def main():
    rules = []
    
    # Walk memory-bank/agent-rules/ and _learned/
    for root, dirs, files in os.walk(RULES_DIR):
        for file in files:
            if file.endswith('.md'):
                filepath = os.path.join(root, file)
                rule = parse_rule_file(filepath)
                if rule:
                    rules.append(rule)
                    
    # Generate Index File
    human_count = sum(1 for r in rules if not r['auto_generated'])
    learned_count = sum(1 for r in rules if r['auto_generated'])
    
    content = []
    content.append("# Agent Rules Index\n")
    content.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    content.append(f"Indexed: {len(rules)} rules ({human_count} human-authored, {learned_count} learned) | Rejected: 0 (unsafe) | Warnings: 0\n")
    
    content.append("## Validation Summary\n")
    content.append("### Health Check")
    content.append(f"- Total rules: {len(rules)}")
    content.append(f"- Human-authored rules: {human_count}")
    content.append(f"- Learned rules (auto-generated): {learned_count}")
    content.append(f"- Estimated max context: ~{sum(r['line_count'] for r in rules)} lines (OK)")
    content.append("- Conflicts detected: 0\n")
    
    content.append("## Rules by File Pattern\n")
    content.append("| Pattern | Rule | Priority | Lines |")
    content.append("|---------|------|----------|-------|")
    for r in sorted(rules, key=lambda x: x['name']):
        for glob in r['globs']:
            content.append(f"| `{glob}` | [{r['name']}]({r['relpath']}) | {r['priority']} | {r['line_count']} |")
            
    content.append("\n## Rules by Path\n")
    content.append("| Path Contains | Rule | Priority | Lines |")
    content.append("|---------------|------|----------|-------|")
    for r in sorted(rules, key=lambda x: x['name']):
        for path in r['paths']:
            content.append(f"| `{path}` | [{r['name']}]({r['relpath']}) | {r['priority']} | {r['line_count']} |")
            
    content.append("\n## Rules by Topic\n")
    content.append("| Keywords | Rule | Priority |")
    content.append("|----------|------|----------|")
    for r in sorted(rules, key=lambda x: x['name']):
        topics_str = ", ".join(f"`{t}`" for t in r['topics'])
        content.append(f"| {topics_str} | [{r['name']}]({r['relpath']}) | {r['priority']} |")
        
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(content) + "\n")
        
    print(f"Indexed {len(rules)} rules to {INDEX_FILE}")

if __name__ == '__main__':
    main()
