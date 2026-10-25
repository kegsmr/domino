window.Domino = (() => {
    const FIELDS = ['INPUT', 'SELECT', 'TEXTAREA'];
    const TOGGLES = ['checkbox', 'radio', 'range', 'color', 'file', 'submit', 'button'];

    // Event types we already listen for on the document
    const listening = new Set();

    // Pending debounce timers per element, and elements with a scheduled after()
    const debounceTimers = new WeakMap();
    const scheduled = new WeakSet();

    // Newest update applied per component. The server numbers updates in the order it made
    // them, so a response that arrives late can't overwrite a newer one.
    const latest = new Map();

    // The app's "public" settings. The server puts them in the page before this script.
    const settingsTag = document.getElementById('domino-settings');
    const settings = settingsTag ? JSON.parse(settingsTag.textContent) : {};

    function pageId() {
        const root = document.querySelector('[data-domino-page]');
        return root ? root.dataset.dominoPage : null;
    }

    function eventData(el) {
        const data = {};

        // The element's own value (checkboxes and radios report checked)
        if (el.type === 'checkbox' || el.type === 'radio') {
            data.value = el.checked;
        } else if (FIELDS.includes(el.tagName)) {
            data.value = el.value;
        }

        // Every field of the surrounding form (repeated names become lists)
        const form = el.tagName === 'FORM' ? el : el.closest('form');
        if (form) {
            data.form = {};
            new FormData(form).forEach((value, name) => {
                if (typeof value !== 'string') return; // files aren't supported
                data.form[name] = name in data.form ? [].concat(data.form[name], value) : value;
            });
        }

        return data;
    }

    // Update `from` in place to match `to`, touching only what changed. Fields keep what the
    // user entered unless the server changed their value, or they're inside the element that
    // fired the event (`reset`): the server has handled that, so its state wins. A field the
    // user is still typing in is left alone unless the event was a submit.
    function morph(from, to, reset) {
        if (from.nodeType !== to.nodeType || from.nodeName !== to.nodeName) {
            from.replaceWith(to);
            return;
        }
        if (from.nodeType !== Node.ELEMENT_NODE) {
            if (from.nodeValue !== to.nodeValue) from.nodeValue = to.nodeValue;
            return;
        }

        const field = FIELDS.includes(from.tagName);
        const serverChanged = field && serverValue(from) !== serverValue(to);

        // Keep the marks of an element that's still waiting for another response
        const pending = busy.get(from);
        // If the server disables it too, it must stay disabled once the requests end
        if (pending && to.hasAttribute('disabled')) pending.disabled = false;
        for (const { name } of Array.from(from.attributes)) {
            if (pending && (name === 'aria-busy' || name === 'data-loading' || (name === 'disabled' && pending.disabled))) continue;
            if (!to.hasAttribute(name)) from.removeAttribute(name);
        }
        for (const { name, value } of Array.from(to.attributes)) {
            if (from.getAttribute(name) !== value) from.setAttribute(name, value);
        }

        morphChildren(from, to, reset);

        const focused = from === document.activeElement;
        const typing = isTyping(from);
        const resetting = reset && reset.root.contains(from) && (reset.submit || !typing);
        if (field && (resetting || (serverChanged && !focused))) {
            if (from.type === 'checkbox' || from.type === 'radio') {
                from.checked = to.hasAttribute('checked');
            } else if (from.tagName === 'SELECT') {
                const selected = to.querySelector('option[selected]');
                from.value = selected ? selected.value : (from.options[0] || {}).value;
            } else {
                from.value = from.tagName === 'TEXTAREA' ? to.textContent : (to.getAttribute('value') || '');
            }
        }
    }

    function isTextField(el) {
        return el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !TOGGLES.includes(el.type));
    }

    // A focused text field: the user may be typing in it
    function isTyping(el) {
        return el === document.activeElement && isTextField(el);
    }

    // The value the server rendered into a field (not what the user has typed since)
    function serverValue(el) {
        if (el.tagName === 'TEXTAREA') return el.textContent;
        if (el.tagName === 'SELECT') {
            const selected = el.querySelector('option[selected]');
            return selected ? selected.getAttribute('value') : null;
        }
        return el.getAttribute('value') + '|' + el.hasAttribute('checked');
    }

    // Set the fields inside the element that fired to the values the server last rendered,
    // which morph keeps in their attributes (what form.reset() restores)
    function resetFields(reset) {
        if (!reset.root.isConnected) return;
        const fields = Array.from(reset.root.querySelectorAll('input, select, textarea'));
        if (FIELDS.includes(reset.root.tagName)) fields.push(reset.root);

        for (const field of fields) {
            const typing = field === document.activeElement && !reset.submit && !TOGGLES.includes(field.type);
            if (typing) continue;
            if (field.type === 'checkbox' || field.type === 'radio') {
                field.checked = field.defaultChecked;
            } else if (field.tagName === 'SELECT') {
                for (const option of field.options) option.selected = option.defaultSelected;
            } else {
                field.value = field.defaultValue;
            }
        }
    }

    function morphChildren(from, to, reset) {
        // Children with an id are matched by id, so reordered lists keep their nodes
        const keyed = new Map();
        for (const child of from.children) {
            if (child.id) keyed.set(child.id, child);
        }

        let current = from.firstChild;
        for (const next of Array.from(to.childNodes)) {
            let match = null;
            if (next.nodeType === Node.ELEMENT_NODE && next.id && keyed.has(next.id)) {
                match = keyed.get(next.id);
                keyed.delete(next.id);
            } else if (current && current.nodeName === next.nodeName && !(current.id && current.id !== next.id)) {
                match = current;
            }

            if (match === null) {
                from.insertBefore(next, current);
                continue;
            }
            if (match === current) {
                current = current.nextSibling;
            } else {
                from.insertBefore(match, current);
            }
            morph(match, next, reset);
        }

        while (current) {
            const following = current.nextSibling;
            current.remove();
            current = following;
        }
    }

    function apply(data, reset) {
        if (!data.id || !data.html) return;
        if (latest.get(data.id) >= data.version) {
            // A newer update (e.g. pushed by the server) got here first, so the page already
            // shows the server's state; still reset the fields of the element that fired
            if (reset) resetFields(reset);
            return;
        }
        latest.set(data.id, data.version);

        const target = document.getElementById(data.id);
        if (!target) return;

        const template = document.createElement('template');
        template.innerHTML = data.html;
        const replacement = template.content.firstElementChild;
        if (!replacement) return;

        morph(target, replacement, reset);

        const updated = document.getElementById(data.id);
        if (updated) {
            listen(updated);
            scheduleAfterEvents(updated);
            openStream();
        }
    }

    // Components re-rendered with refresh() arrive over Server-Sent Events. Only pages
    // showing a live component open the stream. EventSource reconnects by itself after a
    // dropped connection but gives up on an error status, so an expired page (404) stops.
    let stream = null;

    function openStream() {
        if (stream || !document.querySelector('[data-live]')) return;
        const id = pageId();
        if (!id) return;

        stream = new EventSource('/_domino/stream?page=' + encodeURIComponent(id));
        stream.onmessage = (e) => apply(JSON.parse(e.data), null);
    }

    // Requests in flight, so overlapping ones keep <html data-domino-loading> until the last ends
    let inFlight = 0;

    // Requests in flight per marked element, and whether we disabled it, so overlapping
    // requests from one element (e.g. debounced typing) unmark it only when the last ends
    const busy = new WeakMap();

    // Mark the element that fired; the component the response updates isn't known yet.
    // Returns a function that undoes it, once.
    function markBusy(el, submit) {
        const marked = [el];
        // Enter in a field submits too, so mark the form's submit buttons as well
        if (submit) marked.push(...el.querySelectorAll('button:not([type]), button[type=submit], input[type=submit]'));

        for (const node of marked) {
            const state = busy.get(node) || { count: 0, disabled: false, focused: false };
            busy.set(node, state);
            if (state.count++ > 0) continue;
            node.setAttribute('aria-busy', 'true');
            node.setAttribute('data-loading', '');
            if (canDisable(node, submit)) {
                // Disabling the focused element blurs it, so focus it again afterwards
                state.focused = node === document.activeElement;
                state.disabled = true;
                node.disabled = true;
            }
        }

        let undone = false;
        return () => {
            if (undone) return;
            undone = true;
            for (const node of marked) {
                const state = busy.get(node);
                if (--state.count > 0) continue;
                busy.delete(node);
                node.removeAttribute('aria-busy');
                node.removeAttribute('data-loading');
                if (!state.disabled) continue;
                node.disabled = false;
                if (state.focused && node.isConnected && document.activeElement === document.body) node.focus();
            }
        };
    }

    function canDisable(el, submit) {
        // Only a submitting form's buttons, so a form isn't sent twice; other clicks all
        // count (ten clicks on a counter add ten). Leave alone what's already disabled (it
        // stays that way) and text fields, which the user may still be typing in.
        if (!submit || !['BUTTON', 'FIELDSET', 'INPUT', 'SELECT'].includes(el.tagName)) return false;
        return !el.disabled && !isTextField(el);
    }

    // Tell the page about a failed event, and show it unless a listener cancelled that
    function reportError(el, eventId, data) {
        const detail = { error: data.error, traceback: data.traceback || null, eventId };
        // A replaced element is detached, and events on it wouldn't reach the document
        const target = el && el.isConnected ? el : document;
        const event = new CustomEvent('domino:error', { bubbles: true, cancelable: true, detail });
        if (!target.dispatchEvent(event)) return;

        console.error('Domino event error:', data.traceback || data.error);
        if (data.debug) showOverlay(detail);
    }

    // Only shown in debug mode. Server text goes in as textContent, never as HTML.
    function showOverlay(detail) {
        const old = document.getElementById('domino-error');
        if (old) old.remove();

        const overlay = document.createElement('div');
        overlay.id = 'domino-error';
        overlay.setAttribute('role', 'alert');
        overlay.style.cssText = 'position:fixed;left:1rem;right:1rem;bottom:1rem;z-index:2147483647;max-height:60vh;overflow:auto;'
            + 'background:#fff;color:#111;border:2px solid #c00;border-radius:6px;padding:1rem;'
            + 'box-shadow:0 4px 24px rgba(0,0,0,.3);font:14px system-ui,sans-serif';

        const close = document.createElement('button');
        close.type = 'button';
        close.textContent = '×';
        close.setAttribute('aria-label', 'Close');
        close.style.cssText = 'float:right;font-size:1.25rem;border:0;background:none;cursor:pointer';
        close.addEventListener('click', () => overlay.remove());

        const title = document.createElement('strong');
        title.style.color = '#c00';
        title.textContent = detail.error;

        const trace = document.createElement('pre');
        trace.style.cssText = 'font:12px ui-monospace,monospace;white-space:pre-wrap;margin:.75rem 0 0';
        trace.textContent = detail.traceback || '';

        overlay.append(close, title, trace);
        document.body.appendChild(overlay);
    }

    async function triggerEvent(eventId, payload = {}, reset = null, el = null) {
        const unmark = el ? markBusy(el, reset && reset.submit) : null;
        if (inFlight++ === 0) document.documentElement.setAttribute('data-domino-loading', '');
        try {
            const response = await fetch('/_domino/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_id: pageId(), event_id: eventId, data: payload })
            });
            if (response.status === 404) {
                // The server no longer knows this page (expired or restarted)
                window.location.reload();
                return;
            }
            const data = await response.json().catch(() => ({ error: `${response.status} ${response.statusText}` }));
            if (!response.ok) {
                reportError(el, eventId, data);
                return;
            }
            // Unmark first, so the server's HTML decides whether the element ends up disabled
            if (unmark) unmark();
            apply(data, reset);
        } catch (err) {
            reportError(el, eventId, { error: String(err) });
        } finally {
            if (unmark) unmark();
            if (--inFlight === 0) document.documentElement.removeAttribute('data-domino-loading');
        }
    }

    function fire(el, eventId) {
        const submit = el.tagName === 'FORM' && eventId.endsWith('-submit');
        triggerEvent(eventId, eventData(el), { root: el, submit }, el);
    }

    function handle(el, eventId, e) {
        const type = e.type;
        if (type === 'submit') e.preventDefault();

        const delay = parseInt(el.getAttribute('data-debounce-' + type), 10);
        if (!delay) {
            fire(el, eventId);
            return;
        }

        // Wait until the user pauses, then send only the latest value
        const timers = debounceTimers.get(el) || new Map();
        debounceTimers.set(el, timers);
        clearTimeout(timers.get(eventId));
        timers.set(eventId, setTimeout(() => {
            timers.delete(eventId);
            fire(el, eventId);
        }, delay));
    }

    // One listener per event type on the document; it finds the bound elements itself
    function onEvent(e) {
        let el = e.target;
        while (el && el.nodeType === Node.ELEMENT_NODE) {
            const ids = el.getAttribute('data-event-id');
            if (ids) {
                for (const eventId of ids.split(' ')) {
                    if (eventId.split('-').pop() === e.type) handle(el, eventId, e);
                }
            }
            // Events like focus or mouseenter belong only to their own element
            if (!e.bubbles) return;
            el = el.parentElement;
        }
    }

    function within(root, selector) {
        const found = Array.from(root.querySelectorAll(selector));
        if (root.matches && root.matches(selector)) found.unshift(root);
        return found;
    }

    function listen(root = document) {
        for (const el of within(root, '[data-event-id]')) {
            for (const eventId of el.getAttribute('data-event-id').split(' ')) {
                const type = eventId.split('-').pop();
                if (listening.has(type)) continue;
                listening.add(type);
                document.addEventListener(type, onEvent, true);
            }
        }
    }

    function scheduleAfterEvents(root = document) {
        for (const el of within(root, '[data-after-id]')) {
            if (scheduled.has(el)) continue;
            scheduled.add(el);

            const delay = parseInt(el.getAttribute('data-after-id').split('-').pop(), 10);
            setTimeout(() => {
                scheduled.delete(el);
                // Skip elements that were removed while waiting
                if (el.isConnected) triggerEvent(el.getAttribute('data-after-id'));
            }, delay);
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        listen();
        scheduleAfterEvents();
        openStream();
    });

    return { settings, listen, scheduleAfterEvents, triggerEvent, morph, bindEvents: listen };
})();
