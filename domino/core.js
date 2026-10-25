window.Domino = (() => {
    function pageId() {
        const root = document.querySelector('[data-domino-page]');
        return root ? root.dataset.dominoPage : null;
    }

    function eventData(el) {
        const data = {};

        // The element's own value (checkboxes and radios report checked)
        if (el.type === 'checkbox' || el.type === 'radio') {
            data.value = el.checked;
        } else if (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) {
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

    async function triggerEvent(eventId, payload = {}) {
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
            const data = await response.json();
            const target = data.id && document.getElementById(data.id);
            if (target && data.html) target.outerHTML = data.html;
        } catch (err) {
            console.error('Domino event error:', err);
        }
    }

    function bindEvents() {
        document.querySelectorAll('[data-event-id]').forEach(el => {
            if (el.dataset.bound) return;
            el.dataset.bound = true;

            const eventId = el.dataset.eventId;
            const eventType = eventId.split('-').pop();

            el.addEventListener(eventType, async (e) => {
                if (eventType === 'submit') e.preventDefault();
                await triggerEvent(eventId, eventData(el));
                bindEvents(); // rebind new elements
            });
        });
    }

    function scheduleAfterEvents() {
        document.querySelectorAll('[data-after-id]').forEach(el => {
            if (el.dataset.afterBound) return;
            el.dataset.afterBound = true;

            const eventId = el.dataset.afterId;
            const delay = parseInt(eventId.split('-').pop());

            setTimeout(async () => {
                await triggerEvent(eventId);
                bindEvents();
                scheduleAfterEvents();
            }, delay);
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        bindEvents();
        scheduleAfterEvents();
    });

    return { bindEvents, scheduleAfterEvents, triggerEvent };
})();
