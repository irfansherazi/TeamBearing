#!/usr/bin/env python3
import sys
import os
import re

def extract_from_roadmap(feature_id, roadmap_path):
    if not os.path.exists(roadmap_path):
        print(f"Error: Roadmap file not found at '{roadmap_path}'", file=sys.stderr)
        sys.exit(1)
        
    feature_id = feature_id.upper().strip()
    # Pattern to match '### FEAT-XXX:' or '### FEAT-XXX ' with optional leading spaces
    header_pattern = re.compile(rf"^\s*###\s+({re.escape(feature_id)})(?:\s|:|$)", re.IGNORECASE)
    
    with open(roadmap_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    found = False
    extracted_lines = []
    
    for line in lines:
        if header_pattern.match(line):
            found = True
            extracted_lines.append(line)
            continue
            
        if found:
            # If we hit another H3 header or higher, stop (ignoring leading whitespace)
            stripped = line.strip()
            if stripped.startswith("### ") or stripped.startswith("## ") or stripped.startswith("# "):
                break
            extracted_lines.append(line)
            
    if not found:
        print(f"Error: Feature '{feature_id}' not found in roadmap.", file=sys.stderr)
        sys.exit(1)
        
    return "".join(extracted_lines).strip()

def main():
    if len(sys.argv) < 2:
        print("Usage: extract_feature.py <feature_id_or_file_path> [roadmap_path]", file=sys.stderr)
        sys.exit(1)
        
    target = sys.argv[1].strip()
    
    # If target is a file path and exists, read it
    if os.path.exists(target) and os.path.isfile(target):
        try:
            with open(target, 'r', encoding='utf-8') as f:
                print(f.read().strip())
                sys.exit(0)
        except Exception as e:
            print(f"Error reading file '{target}': {e}", file=sys.stderr)
            sys.exit(1)
            
    # Otherwise, assume it is a Feature ID and lookup in roadmap.md
    roadmap_path = sys.argv[2] if len(sys.argv) > 2 else "memory-bank/roadmap.md"
    
    # Check if roadmap_path is relative, if so, resolve it from current work dir
    if not os.path.isabs(roadmap_path):
        # Prefer workspace root or current dir
        potential_paths = [
            roadmap_path,
            os.path.join(os.getcwd(), roadmap_path),
            os.path.join("/Users/joshschauer/Documents/vProMedia/vQA", roadmap_path)
        ]
        for p in potential_paths:
            if os.path.exists(p):
                roadmap_path = p
                break
                
    result = extract_from_roadmap(target, roadmap_path)
    print(result)

if __name__ == "__main__":
    main()
