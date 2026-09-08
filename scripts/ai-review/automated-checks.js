const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const CONSOLE_USAGE_PATTERN = /console\.(log|debug|info|warn|error|trace)\s*\(/;
const DEBUGGER_PATTERN = new RegExp(`\\b${'debug' + 'ger'}\\b`);
const SPEC_FILE_PATTERN = /\.spec\.ts$/;
const HTML_FILE_PATTERN = /\.html$/;
const TS_FILE_PATTERN = /\.ts$/;
const FORM_CONTROL_NAME_PATTERN = /formControlName\s*=\s*"([^"]+)"/g;
const TEMPLATE_HANDLER_PATTERN = /\)\s*=\s*"([a-zA-Z_][a-zA-Z0-9_]*)\s*\(/g; // (click)="handler("

/**
 * Builds a single automated-check result row
 * @param id: string - checklist id
 * @param status: string - PASS, FAIL, or SKIP
 * @param notes: string - explanation, empty by default
 * @returns object - { id, status, notes }
 */
function result(id, status, notes = '') {
    return { id, status, notes };
}

const REVIEW_TOOLING_PREFIX = 'scripts/ai-review';

/**
 * Checks whether a file path belongs to the ai-review tooling itself (excluded from most checks)
 * @param file: string - repo-relative file path
 * @returns boolean - true when the file is part of the ai-review scripts
 */
function isReviewToolingFile(file) {
    return file === 'scripts/ai-review.js' || file.startsWith(`${REVIEW_TOOLING_PREFIX}/`);
}

/**
 * Checks a single source line for a non-commented console/debugger call
 * @param line: string - source line to check
 * @returns boolean - true when the line contains a live console/debugger statement
 */
function lineHasConsoleOrDebugger(line) {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) {
        return false;
    }
    return CONSOLE_USAGE_PATTERN.test(line) || DEBUGGER_PATTERN.test(line);
}

/**
 * Scans added diff lines in .ts/.js/.html files (excluding ai-review tooling) for console/debugger usage
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns array - file paths that contain a console/debugger addition
 */
function scanDiffAdditionsForPattern(perFileDiffs) {
    const hits = [];
    for (const [file, diff] of Object.entries(perFileDiffs)) {
        if (!/\.(ts|js|html)$/.test(file) || isReviewToolingFile(file)) {
            continue;
        }
        const lines = diff.split(/\r?\n/);
        for (const line of lines) {
            if (!line.startsWith('+') || line.startsWith('+++')) {
                continue;
            }
            if (lineHasConsoleOrDebugger(line.slice(1))) {
                hits.push(file);
                break;
            }
        }
    }
    return hits;
}

/**
 * Scans whole files on disk (used for brand-new/untracked files) for console/debugger usage
 * @param rootDir: string - repo root
 * @param files: array - file paths to scan
 * @returns array - "file:line" entries for each hit
 */
function scanFilesForPattern(rootDir, files) {
    const hits = [];
    for (const file of files) {
        if (!/\.(ts|js|html)$/.test(file) || isReviewToolingFile(file)) {
            continue;
        }
        const fullPath = path.join(rootDir, file);
        if (!fs.existsSync(fullPath)) {
            continue;
        }
        const lines = fs.readFileSync(fullPath, 'utf8').split(/\r?\n/);
        lines.forEach((line, index) => {
            if (lineHasConsoleOrDebugger(line)) {
                hits.push(`${file}:${index + 1}`);
            }
        });
    }
    return hits;
}

/**
 * Runs a filter over every added line across all per-file diffs, collecting hits
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @param filterFn: function - ({ file, line }) => falsy | true | hit-string
 * @returns array - collected hits (file paths or custom hit strings)
 */
function scanDiffAddedLines(perFileDiffs, filterFn) {
    const hits = [];
    for (const [file, diff] of Object.entries(perFileDiffs || {})) {
        const lines = String(diff || '').split(/\r?\n/);
        for (const line of lines) {
            if (!line.startsWith('+') || line.startsWith('+++')) {
                continue;
            }
            const content = line.slice(1);
            const hit = filterFn({ file, line: content });
            if (hit) {
                hits.push(hit === true ? file : hit);
            }
        }
    }
    return hits;
}

/**
 * Reads a file's full content if it exists, without throwing
 * @param rootDir: string - repo root
 * @param relativePath: string - file path relative to rootDir
 * @returns string - file contents, or null when missing/unreadable
 */
function readFileIfExists(rootDir, relativePath) {
    try {
        const fullPath = path.join(rootDir, relativePath);
        if (!fs.existsSync(fullPath)) {
            return null;
        }
        return fs.readFileSync(fullPath, 'utf8');
    } catch (_e) {
        return null;
    }
}

/**
 * CQ-05: no console.log/debugger in changed or new files
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-05 result
 */
function checkNoConsoleOrDebugger(rootDir, files, perFileDiffs) {
    const hits = scanDiffAdditionsForPattern(perFileDiffs);
    const newFiles = files.filter((f) => {
        const diff = perFileDiffs[f] || '';
        return diff.startsWith('(new/untracked file');
    });
    const fileHits = newFiles.length ? scanFilesForPattern(rootDir, newFiles) : [];
    const allHits = [...new Set([...hits, ...fileHits.map((h) => h.split(':')[0])])];

    if (allHits.length === 0) {
        return result('CQ-05', 'PASS');
    }
    return result(
        'CQ-05',
        'FAIL',
        `Found console/debugger in changes: ${allHits.slice(0, 5).join(', ')}${allHits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-01 guardrail: if an HTML file contains *ngFor and we add a literal id="..."
 * (not [id]= binding), it is very likely to become a duplicated DOM id.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-01 result
 */
function checkUniqueIdsInNgFor(rootDir, files, perFileDiffs) {
    const htmlFilesInScope = files.filter((f) => HTML_FILE_PATTERN.test(f));
    if (htmlFilesInScope.length === 0) {
        return result('CQ-01', 'SKIP', 'No HTML template files in scope');
    }

    const riskyFiles = new Set();

    // Only consider literal id="..." additions (not [id]= and not attr binding)
    const idAdditionHits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!HTML_FILE_PATTERN.test(file)) return false;
        if (line.includes('[id]') || line.includes('[attr.id]')) return false;
        return /\bid\s*=\s*"/.test(line);
    });
    idAdditionHits.forEach((f) => riskyFiles.add(f));

    if (riskyFiles.size === 0) {
        return result('CQ-01', 'PASS');
    }

    // Confirm file contains *ngFor somewhere (full file content)
    const confirmed = [];
    for (const file of riskyFiles) {
        const content = readFileIfExists(rootDir, file);
        if (!content) continue;
        if (content.includes('*ngFor')) {
            confirmed.push(file);
        }
    }

    if (confirmed.length === 0) {
        return result('CQ-01', 'PASS');
    }

    return result(
        'CQ-01',
        'FAIL',
        `Potential duplicate DOM ids inside *ngFor. Prefer unique [id] bindings (e.g. "'prefix-' + file.s3_filename") and matching label [attr.for]. Files: ${confirmed.slice(0, 5).join(', ')}${confirmed.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-10 guardrail: misleading optional chaining after a spread. Example:
 *   const x = [...arr]?.sort(...)
 * The spread throws before ?. is evaluated when arr is null/undefined.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-10 result
 */
function checkMisleadingOptionalChaining(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file)) return false;
        return /\[\s*\.\.\.[^\]]+\]\s*\?\./.test(line);
    });

    if (hits.length === 0) {
        return result('CQ-10', 'PASS');
    }

    return result(
        'CQ-10',
        'FAIL',
        `Misleading optional chaining after spread (spread throws before ?. runs). Use null-coalesce before spread: [...(arr ?? [])]. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-03: spread + sort/map without null guard inside spread (e.g. [...arr].sort when arr may be null).
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-03 result
 */
function checkUnsafeSpreadBeforeSort(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        const spreadMatch = line.match(/\[\s*\.\.\.\s*([^\]]+)\]\s*\.(sort|map|filter|forEach)\s*\(/);
        if (!spreadMatch) return false;
        const spreadExpr = spreadMatch[1];
        if (/\?\?/.test(spreadExpr)) return false;
        if (/\?\./.test(spreadExpr)) return false;
        return true;
    });

    if (hits.length === 0) {
        return result('CQ-03', 'PASS');
    }

    return result(
        'CQ-03',
        'FAIL',
        `Array spread before .sort/.map without null guard (use [...(arr ?? [])]). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-09: no string + concat in HTML bindings — use template literals in TS or language_pipe helpers.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-09 result
 */
function checkHtmlBindingConventions(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!HTML_FILE_PATTERN.test(file)) return false;
        if (/\{\{[^}]*\+[^}]*\}\}/.test(line)) return file;
        if (/\[[\w.-]*\]\s*=\s*"[^"]*\+[^"]*"/.test(line)) return file;
        if (/\[[\w.-]*\]\s*=\s*'[^']*\+[^']*'/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-09', 'PASS');
    }

    return result(
        'CQ-09',
        'FAIL',
        `String + concat in HTML binding (use template literal in TS or language_pipe). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-01 composite: conventions commonly missed in pre-push review (diff additions only).
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-01 result
 */
function checkConventionGuardrails(rootDir, files, perFileDiffs) {
    const issues = [];

    const ngForIdHits = checkUniqueIdsInNgFor(rootDir, files, perFileDiffs);
    if (ngForIdHits.status === 'FAIL') {
        issues.push(ngForIdHits.notes);
    }

    const interactiveHits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!HTML_FILE_PATTERN.test(file)) return false;
        if (!/<(button|input|select|textarea)\b/i.test(line)) return false;
        if (/\bid\s*=/.test(line) || /\[id\]/.test(line) || /\[attr\.id\]/.test(line)) return false;
        return file;
    });
    if (interactiveHits.length > 0) {
        issues.push(
            `New interactive element without id/[id] (Cypress). Files: ${[...new Set(interactiveHits)].slice(0, 3).join(', ')}`
        );
    }

    const ngForNoTrackBy = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!HTML_FILE_PATTERN.test(file)) return false;
        if (!/\*ngFor\s*=/.test(line)) return false;
        if (/trackBy\s*:/.test(line) || /;\s*trackBy\s*:/.test(line)) return false;
        return file;
    });
    if (ngForNoTrackBy.length > 0) {
        issues.push(
            `New *ngFor without trackBy. Files: ${[...new Set(ngForNoTrackBy)].slice(0, 3).join(', ')}`
        );
    }

    const bsHits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file)) return false;
        const match = line.match(/(?:public|private|protected)?\s*(\w+)\s*(?::[^=]+)?=\s*new\s+BehaviorSubject\b/);
        if (!match) return false;
        if (match[1].endsWith('$')) return false;
        return `${file} (${match[1]} should end with $)`;
    });
    if (bsHits.length > 0) {
        issues.push(`BehaviorSubject property missing $ suffix: ${bsHits.slice(0, 3).join(', ')}`);
    }

    if (issues.length === 0) {
        return result('CQ-01', 'PASS');
    }

    return result('CQ-01', 'FAIL', issues.slice(0, 4).join(' | ') + (issues.length > 4 ? ' | ...' : ''));
}

/**
 * CQ-02: decorative banner comments in changed files (common spec sendback).
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-02 result
 */
function checkDeadCodeAndBannerComments(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        const trimmed = line.trim();
        if (/^\/\/\s*[-=]{10,}/.test(trimmed)) return file;
        if (/^\/\*\s*[-=]{10,}/.test(trimmed)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-02', 'PASS');
    }

    return result(
        'CQ-02',
        'FAIL',
        `Decorative banner comments (use describe() blocks). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-11: doRequest must not appear in new/changed production TS.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-11 result
 */
function checkNoDoRequest(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        if (isReviewToolingFile(file)) return false;
        if (/\bdoRequest\s*\(/.test(line) || /\.doRequest\s*\(/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-11', 'PASS');
    }

    return result(
        'CQ-11',
        'FAIL',
        `doRequest found in changes — use vcAPI (VcApiService). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/** Boolean-ish identifiers that must not use || null / || undefined (use ??). */
const BOOLEANISH_NULLISH_OR =
    /\b([\w$]*(?:[Ee]nabled|[Dd]isabled|[Aa]djusted|[Ff]lag|[Vv]isible|[Ll]oading|[Oo]pen|[Cc]losed|Listening|wantListening|is[A-Z]\w*|has[A-Z]\w*|can[A-Z]\w*|should[A-Z]\w*|datesAdjusted\w*))\s*\|\|\s*(null|undefined)\b/;

/**
 * CQ-12: boolean / flag defaults must use ?? not || null|undefined.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-12 result
 */
function checkBooleanNullishOr(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || isReviewToolingFile(file)) return false;
        if (BOOLEANISH_NULLISH_OR.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-12', 'PASS');
    }

    return result(
        'CQ-12',
        'FAIL',
        `Boolean-ish \`|| null/undefined\` (use ??). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-14: logError with severity 2 navigates home — avoid for soft UX in changed TS.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-14 result
 */
function checkNoNavigatingErrorSeverity(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        if (isReviewToolingFile(file)) return false;
        if (!/\blogError\s*\(/.test(line) && !/\.logError\s*\(/.test(line)) return false;
        // severity is typically 2nd arg: logError(msg, 2, ...) or logError(msg, 2)
        if (/logError\s*\([^)]*,\s*2\s*[,)]/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-14', 'PASS');
    }

    return result(
        'CQ-14',
        'FAIL',
        `logError severity 2 navigates away — use inline/soft error for recoverable UX. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-16: hard-coded Thanksgiving (and day after) as fixed MM/DD.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-16 result
 */
function checkNoHardCodedThanksgiving(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || isReviewToolingFile(file)) return false;
        if (/"11\/28"\s*:/.test(line) || /'11\/28'\s*:/.test(line)) return file;
        if (/"11\/29"\s*:/.test(line) || /'11\/29'\s*:/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-16', 'PASS');
    }

    return result(
        'CQ-16',
        'FAIL',
        `Hard-coded Thanksgiving MM/DD (compute 4th Thursday). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/** One-off test emails that have caused CI 401s; prefer DemoProdDirector and peers. */
const RISKY_TEST_EMAILS = /\b(?:ProductionDir|ProdDirector)\b/;

/**
 * T-05: await async setup; avoid risky one-off CI seed emails in specs.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - T-05 result
 */
function checkSpecAsyncSetupAndSeedUsers(rootDir, files, perFileDiffs) {
    const issues = [];

    const missingAwait = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!SPEC_FILE_PATTERN.test(file) || isReviewToolingFile(file)) return false;
        const trimmed = line.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')) return false;
        // assignment without await: token = service.getUserAndToken(
        if (/\bgetUserAndToken\s*\(/.test(line) && !/\bawait\b/.test(line)) {
            return `${file} (getUserAndToken without await)`;
        }
        return false;
    });
    if (missingAwait.length > 0) {
        issues.push(...missingAwait.slice(0, 3));
    }

    const riskyEmails = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!SPEC_FILE_PATTERN.test(file) || isReviewToolingFile(file)) return false;
        if (RISKY_TEST_EMAILS.test(line)) return `${file} (risky seed email — prefer DemoProdDirector)`;
        return false;
    });
    if (riskyEmails.length > 0) {
        issues.push(...riskyEmails.slice(0, 3));
    }

    if (issues.length === 0) {
        return result('T-05', 'PASS');
    }

    return result('T-05', 'FAIL', issues.slice(0, 4).join(' | ') + (issues.length > 4 ? ' | ...' : ''));
}

/**
 * CQ-19: browser / Web Speech refs and handlers must not be typed as any.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-19 result
 */
function checkNoUntypedBrowserHandlers(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        if (isReviewToolingFile(file)) return false;
        if (/\brecognition\s*:\s*any\b/.test(line)) return `${file} (recognition: any)`;
        if (/\bon(?:result|error|end|start|audiostart|audioend|speechstart|speechend)\s*=\s*\(\s*\w+\s*:\s*any\b/.test(line)) {
            return `${file} (speech handler event: any)`;
        }
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-19', 'PASS');
    }

    return result(
        'CQ-19',
        'FAIL',
        `Untyped browser/speech handler (use SpeechRecognition / typed event). ${[...new Set(hits)].slice(0, 4).join(' | ')}${hits.length > 4 ? ' | ...' : ''}`
    );
}

/**
 * CQ-20 heuristic: mapping list items with (u: any) and raw id: u.id.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-20 result
 */
function checkApiDtoMapHygiene(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        if (isReviewToolingFile(file)) return false;
        if (/\(\s*\w+\s*:\s*any\s*\)/.test(line) && /\bid\s*:\s*\w+\.id\b/.test(line)) {
            return file;
        }
        if (/\bid\s*:\s*\w+\.id\b/.test(line) && !/\bNumber\s*\(/.test(line) && /first_name|last_name|firstName|lastName/.test(line)) {
            return file;
        }
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-20', 'PASS');
    }

    return result(
        'CQ-20',
        'FAIL',
        `API map may pass raw id via any — coerce Number + filter Number.isFinite. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * F-04: history_info / historyInfo with user/API values should use escapeHtml.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - F-04 result
 */
function checkHistoryInfoEscaping(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        if (!/\bhistory_info\b|\bhistoryInfo\b/.test(line)) return false;
        const hasInterpolation = /\$\{/.test(line) || /\+\s*\w/.test(line) || /\+\s*['"]/.test(line);
        if (!hasInterpolation) return false;
        if (/escapeHtml\s*\(/.test(line)) return false;
        return file;
    });

    if (hits.length === 0) {
        return result('F-04', 'PASS');
    }

    return result(
        'F-04',
        'FAIL',
        `history_info/historyInfo interpolation without escapeHtml (XSS risk). Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-07 composite: spec file presence + test-case format guardrails.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-07 result
 */
function checkSpecConventions(rootDir, files, perFileDiffs) {
    const issues = [];

    const presentResult = checkSpecFilePresent(rootDir, files);
    if (presentResult.status === 'FAIL') {
        issues.push(presentResult.notes);
    }

    const formatHits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!SPEC_FILE_PATTERN.test(file)) return false;
        if (/\b(desc|run)\s*:/.test(line)) return `${file} (use description/setup, not desc/run)`;
        return false;
    });
    if (formatHits.length > 0) {
        issues.push(`Non-compliant spec case format: ${formatHits.slice(0, 3).join(', ')}`);
    }

    const asyncSpecHits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!SPEC_FILE_PATTERN.test(file)) return false;
        if (!/\.then\s*\(\s*\(\)\s*=>\s*\{/.test(line)) return false;
        if (!/expect\s*\(/.test(line)) return false;
        if (/fakeAsync|tick\s*\(|return\s+/.test(line)) return false;
        return `${file} (use fakeAsync+tick or return promise in it())`;
    });
    if (asyncSpecHits.length > 0) {
        issues.push(`Async assertions in sync it(): ${asyncSpecHits.slice(0, 3).join(', ')}`);
    }

    if (issues.length === 0) {
        return result('CQ-07', 'PASS');
    }

    return result('CQ-07', 'FAIL', issues.join(' | '));
}

/**
 * CQ-04 guardrails:
 * 1) SQLModelBase.set(...) returns void — flag any .set(...).then(...) in TS diffs.
 * 2) Template ↔ component sanity: new formControlName / handler calls should exist in paired .ts.
 *    (Heuristic, diff-based, catches common runtime errors.)
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-04 result
 */
function checkTemplateBindingsAndSqlModelSet(rootDir, files, perFileDiffs) {
    const issues = [];

    // 1) SQLModelBase.set().then(...)
    const setThenHits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || SPEC_FILE_PATTERN.test(file)) return false;
        return /\.set\s*\([^)]*\)\s*\.then\s*\(/.test(line);
    });
    if (setThenHits.length > 0) {
        issues.push(
            `Found ".set(...).then(...)" in TS changes (SQLModelBase.set returns void). Use: set(...); return update(). Files: ${[...new Set(setThenHits)].slice(0, 3).join(', ')}`
        );
    }

    // 2) Template ↔ component check for HTML in scope
    const htmlFiles = files.filter((f) => HTML_FILE_PATTERN.test(f));
    for (const htmlFile of htmlFiles) {
        const diff = perFileDiffs?.[htmlFile] || '';
        const addedLines = String(diff).split(/\r?\n/).filter((l) => l.startsWith('+') && !l.startsWith('+++')).map((l) => l.slice(1));

        const addedFormControls = new Set();
        const addedHandlers = new Set();

        for (const line of addedLines) {
            let match;
            while ((match = FORM_CONTROL_NAME_PATTERN.exec(line)) !== null) {
                addedFormControls.add(match[1]);
            }
            while ((match = TEMPLATE_HANDLER_PATTERN.exec(line)) !== null) {
                addedHandlers.add(match[1]);
            }
        }

        if (addedFormControls.size === 0 && addedHandlers.size === 0) {
            continue;
        }

        const pairedTs = htmlFile.replace(/\.html$/, '.ts');
        const tsContent = readFileIfExists(rootDir, pairedTs);
        if (!tsContent) {
            issues.push(`Template changed (${htmlFile}) but paired TS file not found: ${pairedTs}`);
            continue;
        }

        // Handlers: ensure method name exists as a function/method token
        const missingHandlers = [];
        for (const handler of addedHandlers) {
            const handlerRe = new RegExp(`\\b${handler}\\s*\\(`);
            if (!handlerRe.test(tsContent)) {
                missingHandlers.push(handler);
            }
        }

        // Controls: heuristic check for common patterns in TS
        const missingControls = [];
        for (const control of addedFormControls) {
            const patterns = [
                new RegExp(`\\b${control}\\s*:\\s*`), // group({ control: '' })
                new RegExp(`controls\\s*\\[\\s*['"]${control}['"]\\s*\\]`),
                new RegExp(`get\\s*\\(\\s*['"]${control}['"]\\s*\\)`),
            ];
            if (!patterns.some((re) => re.test(tsContent))) {
                missingControls.push(control);
            }
        }

        if (missingHandlers.length || missingControls.length) {
            issues.push(
                `Template↔component mismatch risk in ${htmlFile}. Missing in ${pairedTs}:` +
                `${missingHandlers.length ? ` handlers(${missingHandlers.join(', ')})` : ''}` +
                `${missingControls.length ? ` controls(${missingControls.join(', ')})` : ''}`
            );
        }
    }

    if (issues.length === 0) {
        return result('CQ-04', 'PASS');
    }

    return result('CQ-04', 'FAIL', issues.slice(0, 3).join(' | ') + (issues.length > 3 ? ' | ...' : ''));
}

/**
 * CQ-06 (platform) / CQ-08 (vcapi): runs lint when source files are in scope
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param config: object - merged ai-review config (uses config.app)
 * @returns object - lint result (id remapped by runAutomatedChecks)
 */
function checkLint(rootDir, files, config = {}) {
    if (config.app === 'vcapi') {
        const tsSource = files.filter((f) => /^(src|apps|libs|test)\/.+\.ts$/.test(f));
        if (tsSource.length === 0) {
            return result('CQ-08', 'SKIP', 'No TypeScript source files in scope');
        }

        try {
            execSync('npm run lint', {
                cwd: rootDir,
                encoding: 'utf8',
                stdio: ['ignore', 'pipe', 'pipe'],
                timeout: 300000,
                shell: true
            });
            return result('CQ-08', 'PASS');
        } catch (err) {
            const output = [err.stdout, err.stderr].filter(Boolean).join('\n').trim();
            const snippet = output.split(/\r?\n/).slice(-8).join(' | ');
            return result('CQ-08', 'FAIL', snippet || 'Lint failed (npm run lint)');
        }
    }

    const angularSource = files.filter((f) => /^src\/.+\.(ts|html)$/.test(f));
    if (angularSource.length === 0) {
        return result('CQ-06', 'SKIP', 'No Angular source files in scope');
    }

    try {
        execSync('node --max_old_space_size=12288 node_modules/@angular/cli/bin/ng lint', {
            cwd: rootDir,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'pipe'],
            timeout: 300000,
            shell: true
        });
        return result('CQ-06', 'PASS');
    } catch (err) {
        const output = [err.stdout, err.stderr].filter(Boolean).join('\n').trim();
        const snippet = output.split(/\r?\n/).slice(-8).join(' | ');
        return result('CQ-06', 'FAIL', snippet || 'Lint failed (ng lint)');
    }
}

/**
 * CQ-07: flags changed .ts source files that have no corresponding .spec.ts, in scope or on disk
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @returns object - CQ-07 result
 */
function checkSpecFilePresent(rootDir, files) {
    const tsFiles = files.filter(
        (f) => f.endsWith('.ts') && !f.endsWith('.spec.ts') && f.includes('/')
    );
    const missing = [];

    for (const file of tsFiles) {
        const specFile = file.replace(/\.ts$/, '.spec.ts');
        const inScope = files.includes(specFile);
        const exists = fs.existsSync(path.join(rootDir, specFile));
        if (!inScope && !exists) {
            missing.push(file);
        }
    }

    if (missing.length === 0) {
        return result('CQ-07', 'PASS');
    }
    return result('CQ-07', 'FAIL', `Missing spec files for: ${missing.join(', ')}`);
}

/**
 * CQ-23: no async/await in frontend code — Promises must use .then()/.catch().
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-23 result
 */
function checkNoAsyncAwait(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || isReviewToolingFile(file)) return false;
        const trimmed = line.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')) return false;
        if (/\bawait\b/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-23', 'PASS');
    }

    return result(
        'CQ-23',
        'FAIL',
        `async/await found in frontend code — use .then()/.catch() instead. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-24: no hasOwnProperty() — use optional chaining or explicit structure checks.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-24 result
 */
function checkNoHasOwnProperty(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if ((!TS_FILE_PATTERN.test(file) && !HTML_FILE_PATTERN.test(file)) || isReviewToolingFile(file)) return false;
        const trimmed = line.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')) return false;
        if (/\.hasOwnProperty\s*\(/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-24', 'PASS');
    }

    return result(
        'CQ-24',
        'FAIL',
        `hasOwnProperty() found — use optional chaining (?.) or explicit structure checks. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-25: no disabling/suppressing ESLint rules in changed code.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-25 result
 */
function checkNoEslintDisable(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if ((!TS_FILE_PATTERN.test(file) && !HTML_FILE_PATTERN.test(file)) || isReviewToolingFile(file)) return false;
        if (/eslint-disable/.test(line)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-25', 'PASS');
    }

    return result(
        'CQ-25',
        'FAIL',
        `ESLint rule disabled/suppressed in changes — fix the underlying issue instead. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * CQ-29: `} else {` must stay on the same line, not drop `else` to its own line.
 * @param rootDir: string - repo root
 * @param files: array - files in scope
 * @param perFileDiffs: object - map of file path -> unified diff text
 * @returns object - CQ-29 result
 */
function checkElseBraceSameLine(rootDir, files, perFileDiffs) {
    const hits = scanDiffAddedLines(perFileDiffs, ({ file, line }) => {
        if (!TS_FILE_PATTERN.test(file) || isReviewToolingFile(file)) return false;
        const trimmed = line.trim();
        if (trimmed.startsWith('//') || trimmed.startsWith('*')) return false;
        if (/^else\b/.test(trimmed) && !/^\}\s*else\b/.test(trimmed)) return file;
        return false;
    });

    if (hits.length === 0) {
        return result('CQ-29', 'PASS');
    }

    return result(
        'CQ-29',
        'FAIL',
        `"else" dropped to its own line — format as "} else {" on the same line. Files: ${[...new Set(hits)].slice(0, 5).join(', ')}${hits.length > 5 ? '...' : ''}`
    );
}

/**
 * T-01: runs unit tests (platform: serverTest; vcapi: npm test)
 * @param rootDir: string - repo root
 * @param config: object - merged ai-review config
 * @returns object - T-01 result
 */
function checkTestsPass(rootDir, config = {}) {
    const command = config.app === 'vcapi' ? 'npm test' : 'npm run serverTest';
    try {
        execSync(command, {
            cwd: rootDir,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'pipe'],
            timeout: 600000,
            shell: true
        });
        return result('T-01', 'PASS');
    } catch (err) {
        const output = [err.stdout, err.stderr].filter(Boolean).join('\n').trim();
        const snippet = output.split(/\r?\n/).slice(-3).join(' | ');
        return result('T-01', 'FAIL', snippet || `Tests failed (${command})`);
    }
}

/**
 * Remaps an automated check result to the checklist ID from config.automatedChecks
 * so vcapi and platform can share check implementations with different ID numbers
 * @param itemId: string - checklist id from config
 * @param checkResult: object - { id, status, notes } from a check function
 * @returns object - result with id forced to itemId
 */
function remapCheckResult(itemId, checkResult) {
    return {
        ...checkResult,
        id: itemId
    };
}

/**
 * Runs every automated check configured in config.automatedChecks (plus T-01 when --run-tests is set)
 * @param options: object - { rootDir, files, config, perFileDiffs }
 * @returns array - one result per configured automated check
 */
function runAutomatedChecks({ rootDir, files, config, perFileDiffs }) {
    const checks = config.automatedChecks || {};
    const results = [];
    const diffs = perFileDiffs || {};

    for (const [itemId, checkName] of Object.entries(checks)) {
        let checkResult;
        if (checkName === 'noConsoleOrDebugger') {
            checkResult = checkNoConsoleOrDebugger(rootDir, files, diffs);
        } else if (checkName === 'lint') {
            checkResult = checkLint(rootDir, files, config);
        } else if (checkName === 'specFilePresent') {
            checkResult = checkSpecFilePresent(rootDir, files);
        } else if (checkName === 'specConventions') {
            checkResult = checkSpecConventions(rootDir, files, diffs);
        } else if (checkName === 'uniqueIdsInNgFor') {
            checkResult = checkUniqueIdsInNgFor(rootDir, files, diffs);
        } else if (checkName === 'conventionGuardrails') {
            checkResult = checkConventionGuardrails(rootDir, files, diffs);
        } else if (checkName === 'deadCodeAndBannerComments') {
            checkResult = checkDeadCodeAndBannerComments(rootDir, files, diffs);
        } else if (checkName === 'unsafeSpreadBeforeSort') {
            checkResult = checkUnsafeSpreadBeforeSort(rootDir, files, diffs);
        } else if (checkName === 'htmlBindingConventions') {
            checkResult = checkHtmlBindingConventions(rootDir, files, diffs);
        } else if (checkName === 'noDoRequest') {
            checkResult = checkNoDoRequest(rootDir, files, diffs);
        } else if (checkName === 'booleanNullishOr') {
            checkResult = checkBooleanNullishOr(rootDir, files, diffs);
        } else if (checkName === 'noNavigatingErrorSeverity') {
            checkResult = checkNoNavigatingErrorSeverity(rootDir, files, diffs);
        } else if (checkName === 'noHardCodedThanksgiving') {
            checkResult = checkNoHardCodedThanksgiving(rootDir, files, diffs);
        } else if (checkName === 'specAsyncSetupAndSeedUsers') {
            checkResult = checkSpecAsyncSetupAndSeedUsers(rootDir, files, diffs);
        } else if (checkName === 'noUntypedBrowserHandlers') {
            checkResult = checkNoUntypedBrowserHandlers(rootDir, files, diffs);
        } else if (checkName === 'apiDtoMapHygiene') {
            checkResult = checkApiDtoMapHygiene(rootDir, files, diffs);
        } else if (checkName === 'historyInfoEscaping') {
            checkResult = checkHistoryInfoEscaping(rootDir, files, diffs);
        } else if (checkName === 'templateBindingsAndSqlModelSet') {
            checkResult = checkTemplateBindingsAndSqlModelSet(rootDir, files, diffs);
        } else if (checkName === 'misleadingOptionalChaining') {
            checkResult = checkMisleadingOptionalChaining(rootDir, files, diffs);
        } else if (checkName === 'noAsyncAwait') {
            checkResult = checkNoAsyncAwait(rootDir, files, diffs);
        } else if (checkName === 'noHasOwnProperty') {
            checkResult = checkNoHasOwnProperty(rootDir, files, diffs);
        } else if (checkName === 'noEslintDisable') {
            checkResult = checkNoEslintDisable(rootDir, files, diffs);
        } else if (checkName === 'elseBraceSameLine') {
            checkResult = checkElseBraceSameLine(rootDir, files, diffs);
        } else {
            continue;
        }

        results.push(remapCheckResult(itemId, checkResult));
    }

    if (config.runTests) {
        results.push(checkTestsPass(rootDir, config));
    }

    return results;
}

module.exports = { runAutomatedChecks };
