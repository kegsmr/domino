window.Domino = (() => {
    function pageId() {
        const root = document.querySelector('[data-domino-page]');
        return root ? root.dataset.dominoPage : null;
    }

    async function triggerEvent(eventId) {
        try {
            const response = await fetch('/_domino/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_id: pageId(), event_id: eventId })
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

            el.addEventListener(eventType, async () => {
                await triggerEvent(eventId);
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
