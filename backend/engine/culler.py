import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# ARIA roles representing interactive elements the agent can act on
INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "option",
    "menuitem",
    "tab",
    "switch",
    "slider",
    "spinbutton",
    "searchbox",
    "menuitemcheckbox",
    "menuitemradio",
    "gridcell",
    "columnheader",
    "rowheader",
}

# ARIA roles representing safety containers and structural landmarks
SAFETY_ROLES = {
    "dialog",
    "alert",
    "navigation",
    "tab",
    "main",
    "heading",
    "form",
    "alertdialog",
    "tablist",
    "tabpanel",
    "region",
    "banner",
    "contentinfo",
    "complementary",
    "document",
    "application",
}


class ARIANode:
    """Represents a node in the parsed ARIA accessibility tree."""
    def __init__(self, line: str, indent: int, role: str):
        self.line = line
        self.indent = indent
        self.role = role
        self.children: List[ARIANode] = []
        self.keep = False


class SemanticDOMCuller:
    """Utility to prune structural noise and boilerplate from ARIA accessibility trees."""

    @staticmethod
    def parse_tree(text: str) -> List[ARIANode]:
        """Parses indented ARIA tree text lines into a hierarchy of ARIANodes."""
        lines = text.split("\n")
        roots: List[ARIANode] = []
        stack: List[tuple[int, ARIANode]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Calculate indentation level (count leading spaces)
            indent = len(line) - len(line.lstrip(" "))

            # Extract role from [role] pattern
            role = ""
            role_match = re.search(r"\[([^\]]+)\]", stripped)
            if role_match:
                role = role_match.group(1).lower()

            node = ARIANode(line=line, indent=indent, role=role)

            # Walk stack to find parent
            while stack and stack[-1][0] >= indent:
                stack.pop()

            if not stack:
                roots.append(node)
            else:
                stack[-1][1].children.append(node)

            stack.append((indent, node))

        return roots

    @staticmethod
    def mark_nodes(nodes: List[ARIANode]) -> bool:
        """
        Recursively marks nodes that should be kept.
        Returns True if any descendant (or this node itself) is kept.
        """
        has_kept_descendant = False

        for node in nodes:
            # Check if this node is inherently interactive or a safety landmark
            is_interactive = node.role in INTERACTIVE_ROLES
            is_safety = node.role in SAFETY_ROLES
            # We also always keep the root WebArea node to anchor the tree
            is_root = node.role == "webarea" or node.indent == 0

            # Recurse into children
            children_kept = SemanticDOMCuller.mark_nodes(node.children)

            if is_interactive or is_safety or is_root or children_kept:
                node.keep = True
                has_kept_descendant = True
            else:
                node.keep = False

        return has_kept_descendant

    @staticmethod
    def serialize_tree(nodes: List[ARIANode]) -> List[str]:
        """Serializes kept nodes back to indented text."""
        lines: List[str] = []
        for node in nodes:
            if node.keep:
                lines.append(node.line)
                lines.extend(SemanticDOMCuller.serialize_tree(node.children))
        return lines

    @classmethod
    def cull(cls, aria_tree: str) -> str:
        """
        Main entrypoint: takes raw ARIA tree text, prunes structural/empty nodes,
        and returns the compressed ARIA tree text.
        """
        if not aria_tree or aria_tree.strip().startswith("(accessibility tree unavailable"):
            return aria_tree

        roots = cls.parse_tree(aria_tree)
        cls.mark_nodes(roots)
        serialized_lines = cls.serialize_tree(roots)
        return "\n".join(serialized_lines)


def semantic_dom_cull(aria_tree: str) -> str:
    """Wrapper function to perform semantic culling on an ARIA tree string."""
    return SemanticDOMCuller.cull(aria_tree)
