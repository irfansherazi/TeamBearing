const fs = require('fs');
const path = require('path');

const ID_PATTERN = /^\*\*\[([A-Z]+-\d+)\]\*\*\s*(.+)$/;

/**
 * Parses pr-review-checklist.md into structured { id, section, text } items
 * @param rootDir: string - repo root
 * @param instructionsFile: string - path to the checklist file, relative to rootDir
 * @returns array - checklist items in file order
 */
function parseChecklistFile(rootDir, instructionsFile) {
    const filePath = path.resolve(rootDir, instructionsFile);
    if (!fs.existsSync(filePath)) {
        throw new Error(`Checklist file not found: ${instructionsFile}`);
    }

    const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
    const items = [];
    let currentSection = '';

    for (const line of lines) {
        const sectionMatch = line.match(/^###\s+\d+\.\s+(.+)$/);
        if (sectionMatch) {
            currentSection = sectionMatch[1].trim();
            continue;
        }

        const bulletMatch = line.match(/^-\s+\*\*\[([A-Z]+-\d+)\]\*\*\s*(.+)$/);
        if (bulletMatch) {
            items.push({
                id: bulletMatch[1],
                section: currentSection,
                text: bulletMatch[2].trim()
            });
        }
    }

    if (items.length === 0) {
        throw new Error(
            `No checklist items with IDs found in ${instructionsFile}. Expected format: - **[CQ-01]** description`
        );
    }

    return items;
}

/**
 * Filters checklist items down to the ones an AI/chat reviewer must still score
 * @param items: array - full checklist items from parseChecklistFile
 * @param automatedChecks: object - map of checklist id -> automated check name
 * @param advisoryAutomatedIds: array - ids that run an automated check but still need an AI verdict
 * @returns array - checklist items requiring AI judgment
 */
function getAiReviewItems(items, automatedChecks, advisoryAutomatedIds) {
    const automatedIds = new Set(Object.keys(automatedChecks || {}));
    const advisoryIds = new Set(advisoryAutomatedIds || []);
    // Fully-automated IDs are excluded from the AI-required table. Advisory IDs
    // (regex coverage narrower than the written rule) stay in the table even
    // though an automated check also ran — the AI verdict is still required.
    return items.filter((item) => !automatedIds.has(item.id) || advisoryIds.has(item.id));
}

module.exports = { parseChecklistFile, getAiReviewItems, ID_PATTERN };
