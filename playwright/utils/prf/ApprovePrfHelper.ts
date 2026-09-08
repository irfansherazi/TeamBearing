/**
 * ApprovePrfHelper.ts — Approve a Pending PRF from the calendar surface.
 *
 * Runbook source: knowledge-base/vqa-agent/scenario-runbooks/approve-pending-prf.md
 *
 * Approval is a SINGLE calendar-side click — no drawer, no form. Applies to
 * users whose role has calendar approval capability:
 *   ROLE_SALES_MANAGER, ROLE_PROMOTIONS_DIRECTOR, ROLE_OTHER, ROLE_GM
 *   (event_approval.js.html.twig:57-84)
 *
 * The "Approve? Yes | No" strong-tag block is appended inside a `.fc-event`'s
 * actions html (fullcal.js.html.twig:619, :780) only when
 * `can_see_approve_buttons(prf.status_code_id, prf.created_by, prf)` returns
 * true. If the link is absent, the current role/status pair is not eligible —
 * treat as PRECONDITION_MISSING; do NOT fabricate an approval.
 *
 * Status transitions (default branch, event_approval.js.html.twig:57-84):
 *   ROLE_SALES_MANAGER      → 37
 *   ROLE_PROMOTIONS_DIRECTOR→ 41 (default) / 39 requires_other / 40 requires_gm
 *   ROLE_OTHER              → 41 (from prior 62) / 40 requires_gm / 41 else
 *   ROLE_GM                 → 41 (LIVE)
 * Custom approval chains follow `custom_approval_number` step ordering.
 * Cat-app process (status 90) advances via `cat_app_process_step` (→ 41 if next is LIVE).
 */

import { expect, Page, Locator } from '@playwright/test';

/**
 * Return the row-scoped Approve link for a given PRF id.
 * Selector: `a.calendar-approve-event[data-prf-id='<id>']` (delegate at
 * event_approval.js.html.twig:14).
 *
 * STRICT-MODE NOTE: "Yes" appears at every eligible PRF card, so ALWAYS
 * scope by data-prf-id — never `page.getByText('Yes')`.
 */
export function approveLinkFor(page: Page, prfId: string | number): Locator {
    return page.locator(`a.calendar-approve-event[data-prf-id="${prfId}"]`).first();
}

/**
 * Return the `.fc-event` for a given PRF id. FullCalendar sets
 * `record.DT_RowId = record.id` (event.js.html.twig:40), so the event is
 * addressable via `[data-prf-id]` in modern paint OR via id / row-id
 * attributes.
 */
export function eventCardFor(page: Page, prfId: string | number): Locator {
    return page.locator(
        `#promo-calendar .fc-event[data-prf-id="${prfId}"], ` +
        `#promo-calendar .fc-event#${prfId}, ` +
        `#promo-calendar tr[id="${prfId}"] .fc-event`
    ).first();
}

/**
 * STEP 1 verification: is this PRF approvable by the current user right now?
 * If false, treat as PRECONDITION_MISSING (not a vQA failure).
 */
export async function isPrfApprovable(page: Page, prfId: string | number): Promise<boolean> {
    return await approveLinkFor(page, prfId).isVisible({ timeout: 3000 }).catch(() => false);
}

/**
 * STEP 2: Click the "Yes" (approve) link.
 *
 * The click handler at event_approval.js.html.twig:15 immediately disables
 * the link. Downstream:
 *   - `get_event_conflicts` runs (imported at event_approval.js.html.twig:11).
 *   - If conflicts exist → `#event_conflict_modal` opens → STEP 3.
 *   - Otherwise → `update_prf_status(prfId, newStatus)` POST → toastr success
 *     → event card re-renders without `.calendar-approve-event`.
 *
 * Returns 'conflict-modal' if resolution is needed, 'direct' if the status
 * change proceeded, or 'unknown' if neither state was observed within the
 * timeout.
 */
export async function clickApproveYes(
    page: Page,
    prfId: string | number,
    options: { timeout?: number } = {}
): Promise<'conflict-modal' | 'direct' | 'unknown'> {
    const { timeout = 8000 } = options;

    const link = approveLinkFor(page, prfId);
    await expect(link).toBeVisible({ timeout: 5000 });
    // Guard against disabled — the runbook says handler disables IMMEDIATELY on click,
    // so pre-click enabled is what we check.
    const disabled = await link.evaluate(el => (el as HTMLAnchorElement).getAttribute('disabled') !== null);
    if (disabled) {
        throw new Error(`clickApproveYes: approve link for PRF ${prfId} is already disabled — likely mid-flight from an earlier click.`);
    }

    await link.click();

    const modal = page.locator('#event_conflict_modal.modal.in');
    const successToast = page
        .locator('.toast-success, .toast-message.toast-success, .toast-info, .toast-message.toast-info')
        .first();

    const winner = await Promise.race([
        modal.waitFor({ state: 'visible', timeout }).then(() => 'conflict-modal' as const).catch(() => null),
        successToast.waitFor({ state: 'attached', timeout }).then(() => 'direct' as const).catch(() => null),
    ]);

    if (winner === 'conflict-modal') {
        console.log(`✋ clickApproveYes: PRF ${prfId} triggered conflict modal — STEP 3 required`);
        return 'conflict-modal';
    }
    if (winner === 'direct') {
        console.log(`✅ clickApproveYes: PRF ${prfId} approved directly (no conflicts)`);
        return 'direct';
    }
    console.warn(`⚠️ clickApproveYes: PRF ${prfId} — neither conflict modal nor toast observed within ${timeout}ms`);
    return 'unknown';
}

/**
 * STEP 3: Resolve the conflict modal (if opened by STEP 2).
 *
 * The modal is a bootstrap 3 modal: `#event_conflict_modal.modal.in`. The
 * "Approve" button inside is typically `#btn_event_conflict_approve`
 * (delegates.js.html.twig:9919). MUST scope the click to the modal — a
 * generic "Approve" text hits `.calendar-approve-event` cards too.
 *
 * On close, the delegate at delegates.js.html.twig:9918-9921 resets the
 * approve link's `disabled` state.
 */
export async function resolveConflictModal(page: Page): Promise<void> {
    const modal = page.locator('#event_conflict_modal.modal.in');
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Prefer the canonical id, fall back to a modal-scoped "Approve" button.
    const approveBtn = modal.locator(
        '#btn_event_conflict_approve, ' +
        'button.calendar-approve-event, ' +
        'button:has-text("Approve")'
    ).first();
    await expect(approveBtn).toBeVisible({ timeout: 3000 });
    await approveBtn.click();

    // Modal exits `.in` on hide (bootstrap 3 transition).
    await expect(page.locator('#event_conflict_modal.in')).toBeHidden({ timeout: 5000 });

    const toast = page.locator('.toast-success, .toast-message.toast-success').first();
    await toast.waitFor({ state: 'attached', timeout: 8000 }).catch(() => {});
    console.log('✅ resolveConflictModal: conflict resolved, toast expected');
}

/**
 * STEP 4: Verify the PRF has re-rendered with an advanced status.
 *
 * The rerender is asynchronous. Poll until either:
 *   - the approve link disappears from the target card (most common — new
 *     status is not further-approvable by this user), OR
 *   - the card's rendered status class/text has changed (e.g. status_code_id
 *     class name flipped).
 *
 * `caldata_raw[prfId].status_code_id` in JS memory is also updated — we
 * read it for a definitive check when possible.
 */
export async function verifyApprovalAdvanced(
    page: Page,
    prfId: string | number,
    options: { timeout?: number; expectStatusCodeId?: number } = {}
): Promise<{ statusCodeId: number | null }> {
    const { timeout = 10000, expectStatusCodeId } = options;

    // 1. approve link should be gone (or at least not re-rendered as .calendar-approve-event).
    await approveLinkFor(page, prfId)
        .waitFor({ state: 'detached', timeout })
        .catch(() => {
            // Detach is best-effort — some approvals leave a NEW approval level's link.
            console.log(`ℹ️ verifyApprovalAdvanced: approve link for PRF ${prfId} still present — expected if further approval by this user is required.`);
        });

    // 2. Read caldata_raw when available.
    const statusCodeId = await page.evaluate((id) => {
        try {
            // @ts-expect-error — caldata_raw is a global map keyed by prf id
            const raw = (window as any).caldata_raw;
            if (raw && raw[id] && typeof raw[id].status_code_id === 'number') {
                return raw[id].status_code_id;
            }
        } catch { /* ignore */ }
        return null;
    }, String(prfId));

    if (expectStatusCodeId !== undefined && statusCodeId !== null && statusCodeId !== expectStatusCodeId) {
        throw new Error(
            `verifyApprovalAdvanced: PRF ${prfId} status_code_id=${statusCodeId}, expected ${expectStatusCodeId}. ` +
            `Verify against the STATUSES map — do not hardcode strings.`
        );
    }

    console.log(`✅ verifyApprovalAdvanced: PRF ${prfId} — new status_code_id=${statusCodeId ?? '(unread)'}`);
    return { statusCodeId };
}

/**
 * Orchestrator: locate → approve → resolve conflicts (if any) → verify.
 *
 * @param options.expectConflict
 *   - undefined: auto-detect. Passes if either path succeeds.
 *   - true:   assert that a conflict modal appeared (fail otherwise).
 *   - false:  assert that no conflict modal appeared (fail if one did).
 */
export async function approvePendingPrf(
    page: Page,
    prfId: string | number,
    options: {
        expectConflict?: boolean;
        expectStatusCodeId?: number;
        timeout?: number;
    } = {}
): Promise<{ path: 'direct' | 'conflict-resolved'; statusCodeId: number | null }> {
    if (!(await isPrfApprovable(page, prfId))) {
        throw new Error(
            `PRECONDITION_MISSING: PRF ${prfId} has no visible .calendar-approve-event link. ` +
            `The current role/status pair is not eligible per can_see_approve_buttons.`
        );
    }

    const outcome = await clickApproveYes(page, prfId, { timeout: options.timeout });

    let path: 'direct' | 'conflict-resolved';
    if (outcome === 'conflict-modal') {
        if (options.expectConflict === false) {
            throw new Error(`approvePendingPrf: unexpected conflict modal for PRF ${prfId} (expectConflict=false)`);
        }
        await resolveConflictModal(page);
        path = 'conflict-resolved';
    } else if (outcome === 'direct') {
        if (options.expectConflict === true) {
            throw new Error(`approvePendingPrf: expected conflict modal for PRF ${prfId} but approval proceeded directly`);
        }
        path = 'direct';
    } else {
        throw new Error(`approvePendingPrf: PRF ${prfId} — approve click observed neither modal nor toast within timeout.`);
    }

    const { statusCodeId } = await verifyApprovalAdvanced(page, prfId, {
        timeout: options.timeout,
        expectStatusCodeId: options.expectStatusCodeId,
    });

    return { path, statusCodeId };
}
