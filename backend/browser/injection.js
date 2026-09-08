/**
 * vQA Angular Bridge
 * Pierces the Angular 9+ (Ivy) internal state for deterministic inspection and interaction.
 */
(function() {
    if (window.__VQA_ANGULAR_BRIDGE__) return;

    window.__VQA_ANGULAR_BRIDGE__ = {
        /**
         * Get Angular component instance for an element.
         */
        getComponent: function(el) {
            if (!window.ng || !window.ng.getComponent) return null;
            try {
                return window.ng.getComponent(el);
            } catch (e) {
                return null;
            }
        },

        /**
         * Get component properties.
         */
        getComponentState: function(el) {
            const comp = this.getComponent(el);
            if (!comp) return null;

            // Common properties we care about
            return {
                value: comp.value,
                disabled: comp.disabled,
                readonly: comp.readonly,
                options: comp.options,
                label: comp.label,
                invalid: comp.invalid,
                placeholder: comp.placeholder
            };
        },

        /**
         * Trigger change detection for a component.
         */
        markForCheck: function(el) {
            if (!window.ng || !window.ng.applyChanges) return false;
            const comp = this.getComponent(el);
            if (!comp) return false;
            try {
                window.ng.applyChanges(comp);
                return true;
            } catch (e) {
                // Fallback for some Angular versions
                try {
                    const dref = window.ng.getDirectives(el).find(d => d.constructor.name === comp.constructor.name);
                    if (dref) {
                        window.ng.applyChanges(dref);
                        return true;
                    }
                } catch (e2) {}
                return false;
            }
        },

        /**
         * Set component properties and trigger change detection.
         */
        setState: function(el, props) {
            const comp = this.getComponent(el);
            if (!comp) return false;
            try {
                Object.assign(comp, props);
                // Also try to call writeValue if it's a ControlValueAccessor
                if (props.value !== undefined && typeof comp.writeValue === 'function') {
                    comp.writeValue(props.value);
                }
                // Trigger change detection
                this.markForCheck(el);
                return true;
            } catch (e) {
                return false;
            }
        },

        /**
         * PrimeNG p-select (Dropdown) macro.
         */
        pSelect: function(el, value) {
            const comp = this.getComponent(el);
            if (!comp) return { error: 'Component not found' };
            try {
                // PrimeNG Dropdown/Select usually uses 'value' property
                comp.value = value;
                // Emit onChange event
                if (comp.onChange && typeof comp.onChange.emit === 'function') {
                    comp.onChange.emit({ value: value });
                }
                // Trigger change detection
                this.markForCheck(el);
                return { success: true, value: value };
            } catch (e) {
                return { error: e.message };
            }
        },

        /**
         * PrimeNG p-calendar macro.
         */
        pCalendar: function(el, dateStr) {
            const comp = this.getComponent(el);
            if (!comp) return { error: 'Component not found' };
            try {
                const date = new Date(dateStr);
                if (isNaN(date.getTime())) return { error: 'Invalid date string: ' + dateStr };
                
                comp.value = date;
                // Many components use writeValue to update internal state/input
                if (typeof comp.writeValue === 'function') {
                    comp.writeValue(date);
                }
                // Emit onSelect event
                if (comp.onSelect && typeof comp.onSelect.emit === 'function') {
                    comp.onSelect.emit(date);
                }
                // Trigger change detection
                this.markForCheck(el);
                return { success: true, value: dateStr };
            } catch (e) {
                return { error: e.message };
            }
        },

        /**
         * PrimeNG p-table sorting macro.
         */
        pTableSort: function(el, field, order = 1) {
            // Find p-table component. If el is not p-table, look up.
            let target = el;
            while (target && target.tagName !== 'P-TABLE') {
                target = target.parentElement;
            }
            if (!target) {
                // Fallback: try to find p-table inside or nearby if el is a header
                target = el.querySelector('p-table') || el.closest('p-table');
            }
            
            const comp = this.getComponent(target || el);
            if (!comp) return { error: 'Table component not found' };
            
            try {
                // PrimeNG Table has a sort() method
                if (typeof comp.sort === 'function') {
                    comp.sort({ field: field, order: order });
                    this.markForCheck(target || el);
                    return { success: true, field: field, order: order };
                }
                return { error: 'sort method not found on component' };
            } catch (e) {
                return { error: e.message };
            }
        },

        /**
         * Check if Angular is bootstrapped and 'ng' global is available.
         */
        isHydrated: function() {
            return !!(window.ng && window.ng.getComponent);
        }
    };
})();
