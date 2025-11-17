window.Domino = (() => {
    async function triggerEvent(eventId) {
        try {
            const response = await fetch('/_domino/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ event_id: eventId })
            });
            const data = await response.json();
            const target = document.getElementById(data.id);
            if (target) target.outerHTML = data.html;
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
