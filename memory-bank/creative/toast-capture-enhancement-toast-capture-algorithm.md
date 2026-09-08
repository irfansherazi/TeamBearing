# Algorithm: Toast Capture MutationObserver

## Decision
**Chosen**: Option 1 — Global Body MutationObserver with CSS Selector Filtering
**Rationale**: PrimeNG toasts are often dynamically injected into a top-level container that might not exist at initialization, or into a container that is deep in the DOM. Observing the `body` with `subtree: true` ensures we catch all toasts regardless of where they are mounted. Filtering by `.p-toast-message` provides high precision with low overhead.

## Algorithm Design

```javascript
(function() {
  window.__VQA_TOAST_BUFFER__ = [];
  const MAX_SIZE = 10;

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType !== 1) continue; // Only elements

        // Check if the node itself is a toast or contains a toast
        const toastElements = node.matches('.p-toast-message') 
          ? [node] 
          : node.querySelectorAll('.p-toast-message');

        toastElements.forEach(el => {
          const text = el.innerText.trim();
          if (!text) return;

          // Push to FIFO buffer
          window.__VQA_TOAST_BUFFER__.push({
            text: text,
            timestamp: Date.now(),
            severity: Array.from(el.classList)
              .find(c => c.startsWith('p-toast-message-'))
              ?.replace('p-toast-message-', '') || 'info'
          });

          // Maintain max size
          if (window.__VQA_TOAST_BUFFER__.length > MAX_SIZE) {
            window.__VQA_TOAST_BUFFER__.shift();
          }
        });
      }
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });
})();
```

## Complexity Analysis
- **Time**: O(N * M) where N is number of mutations and M is size of added subtree. In practice, O(1) per mutation as toast subtrees are small.
- **Space**: O(K) where K is `MAX_SIZE` (fixed at 10). Memory footprint is negligible.

## Options Explored

### Option 1: Global Body MutationObserver (Chosen)
- **Description**: Attach observer to `document.body` and filter added nodes for `.p-toast-message`.
- **Pros**: Catches all toasts, robust to changes in container mounting.
- **Cons**: Slightly more overhead than observing a specific container.

### Option 2: Specific Container Observer
- **Description**: Wait for `.p-toast` to appear, then attach observer to it.
- **Pros**: Minimal overhead (only observes toast events).
- **Cons**: Fragile. If `.p-toast` is removed/re-added, the observer dies. Requires complex logic to re-attach.

### Option 3: MessageService Hooking
- **Description**: Wrap PrimeNG's `MessageService` methods in the browser.
- **Pros**: Direct access to structured message data.
- **Cons**: Highly dependent on PrimeNG internals. May fail if the application uses a custom service or different version.

## Evaluation Matrix

| Criteria | Option 1 (Chosen) | Option 2 | Option 3 |
|----------|------------------|----------|----------|
| Correctness | High | Medium | Medium |
| Reliability | High | Low | Low |
| Simplicity | High | Medium | Low |
| Performance | Medium | High | High |
| **Total Score** | **9/10** | **6/10** | **5/10** |
