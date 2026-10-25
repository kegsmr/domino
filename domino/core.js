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
                if (typeof value !== 'string') return; // files go up on their own (see upload)
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
            if (name === 'data-uploading' && uploading.has(from)) continue;
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

    // The server sends each component class's CSS ([name, css] pairs) once per page, the
    // first time a response shows one. Add what the page doesn't have yet.
    function addStyles(styles) {
        if (!styles || !styles.length) return;
        const blocks = Array.from(document.querySelectorAll('style[data-domino-css]'));
        const present = new Set(blocks.flatMap((block) => block.dataset.dominoCss.split(' ')));
        const missing = styles.filter(([name]) => !present.has(name));
        if (!missing.length) return;

        const style = document.createElement('style');
        style.dataset.dominoCss = missing.map(([name]) => name).join(' ');
        style.textContent = missing.map(([, css]) => css).join('\n');

        // With the other component CSS, before the page's own stylesheets, so those still win
        const last = blocks[blocks.length - 1];
        const firstSheet = document.head.querySelector('style, link[rel=stylesheet]');
        if (last) {
            last.after(style);
        } else if (firstSheet) {
            firstSheet.before(style);
        } else {
            document.head.appendChild(style);
        }
    }

    function apply(data, reset) {
        // Even for a stale update: the server counts its CSS as sent
        addStyles(data.css);
        if (!data.id || !data.html) return;
        // The page shows where the component's events in flight lead (see predict), which is
        // newer than this; keep the newest such update for when the last of them is answered
        if (inflight.get(data.id) > 0 && showingGuess(data.id)) {
            const kept = deferred.get(data.id);
            if (!kept || kept.version < data.version) deferred.set(data.id, data);
            return;
        }
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

        // Before morphing, which moves nodes out of the template
        const found = readGraphs(replacement);
        morph(target, replacement, reset);
        found.forEach(installGraph);

        const updated = document.getElementById(data.id);
        if (updated) {
            listen(updated);
            scheduleAfterEvents(updated);
            connect();
        }
    }

    // Every message from the server comes through here, whatever carried it (an event's HTTP
    // response, a Server-Sent Event, a WebSocket message), so each transport handles it the
    // same way. `request` is the event it answers, if any.
    async function handleMessage(data, status = 200, request = null) {
        if (status === 404) {
            // The server no longer knows this page (expired or restarted), or is told it's
            // being left for the one a navigation in flight will show
            if (!navigation) window.location.reload();
            return;
        }
        if (data.type === 'expired') {
            pageExpired();
            return;
        }
        const el = request ? request.el : null;
        if (status < 200 || status >= 300) {
            reportError(el, request ? request.eventId : null, data);
            return;
        }
        // The handler changed the session (e.g. logged in) while running over the WebSocket,
        // which can't set cookies: fetch the new cookie before going on
        if (data.session) {
            await fetch('/_domino/session/' + encodeURIComponent(data.session), { method: 'POST', credentials: 'same-origin' });
        }
        // The handler called domino.redirect(); the server only allows paths on this site
        if (data.redirect && data.redirect.startsWith('/') && !data.redirect.startsWith('//')) {
            if (navigationOn()) {
                navigate(data.redirect, true);
            } else {
                window.location.assign(data.redirect);
            }
            return;
        }
        // Unmark first, so the server's HTML decides whether the element ends up disabled
        if (request && request.unmark) request.unmark();
        apply(data, request ? request.reset : null);
    }

    // Pages served through app.asgi (marked data-domino-ws) talk to the server over one
    // WebSocket per tab: events go up, their results and pushed updates come down. Elsewhere,
    // or when the socket can't stay connected, events are POSTed and pages showing a live
    // component get pushes over Server-Sent Events.
    const RETRIES = 3;
    const CONNECT_TIMEOUT = 5000;
    const RESULT_TIMEOUT = 60000;
    // Closed by the server because another socket for this page (e.g. a duplicated tab) took over
    const CLOSE_REPLACED = 4001;

    let socket = null;
    let socketReady = null; // resolves to true once the server has bound the socket to this page
    let settleReady = null; // resolves it
    let failures = 0; // closes in a row, without a connection that lasted
    let useHttp = false; // for the rest of this page's life, and pages swapped in after it
    let nextRef = 0;
    const waiting = new Map(); // ref -> the event sent over the socket that awaits its result

    // Open what this page needs to hear from the server: the socket, or else the stream
    function connect() {
        if (useHttp || !window.WebSocket || !document.querySelector('[data-domino-ws]')) {
            openStream();
            return;
        }
        if (socket || !pageId()) return;
        if (!needsServer()) return;
        openSocket();
    }

    // Nothing to send or receive (e.g. a static page)
    function needsServer() {
        return !!document.querySelector('[data-event-id], [data-after-id], [data-live]');
    }

    // The worker process of `domino serve` that has a page ("w3" from "w3-<id>"), or "" with
    // a single process
    function workerOf(id) {
        const match = /^(w\d+)-/.exec(id || '');
        return match ? match[1] : '';
    }

    function openSocket() {
        const scheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
        // The page id in the URL tells `domino serve`'s router which worker process has the page
        const ws = new WebSocket(scheme + location.host + '/_domino/ws?page=' + encodeURIComponent(pageId()));
        let readyAt = 0;
        ws.worker = workerOf(pageId());
        socket = ws;
        socketReady = new Promise((resolve) => { settleReady = resolve; });

        // A proxy may hold the handshake forever; events wait for it, so don't wait long
        const timer = setTimeout(() => ws.close(), CONNECT_TIMEOUT);

        // For the page shown now, which may not be the one that opened it (see rebind)
        ws.onopen = () => {
            if (needsServer()) {
                ws.send(JSON.stringify({ type: 'hello', page_id: pageId() }));
            } else {
                clearTimeout(timer);
                settleReady(true);
            }
        };

        ws.onmessage = async (e) => {
            let data;
            try { data = JSON.parse(e.data); } catch (err) { return; }

            if (data.type === 'ready') {
                clearTimeout(timer);
                readyAt = Date.now();
                settleReady(true);
            } else if (data.type === 'result') {
                const request = waiting.get(data.ref);
                if (!request) return;
                waiting.delete(data.ref);
                clearTimeout(request.timer);
                request.resolve({ status: data.status, data });
                if (ws.retired) closeWhenIdle(ws);
            } else {
                // Not 'expired', which must be handled before the close that follows it
                if (data.type === 'update') await wait(latency / 2);
                handleMessage(data);
            }
        };

        ws.onclose = (e) => {
            clearTimeout(timer);
            // Retired for a page in another worker (see rebind): closed by us, once idle
            if (ws.retired) return;
            settleReady(false);
            if (socket === ws) {
                socket = null;
                socketReady = null;
            }
            // Whether these were handled is unknown, so report them rather than send them again
            for (const request of waiting.values()) {
                clearTimeout(request.timer);
                request.reject(new Error('Connection to the server lost'));
            }
            waiting.clear();

            if (useHttp) return;
            if (e.code === CLOSE_REPLACED) {
                // Don't take the page back from the other socket; send events over HTTP
                useHttp = true;
                return;
            }
            if (readyAt && Date.now() - readyAt > 30000) failures = 0;
            if (++failures > RETRIES) {
                useHttp = true;
                connect();
                return;
            }
            // Meanwhile events go over HTTP, and pushes wait on the server for the new socket
            setTimeout(connect, 250 * 2 ** (failures - 1));
        };
    }

    // The socket found that the server doesn't know this page (it expired, or the server
    // restarted). Live pages reload to get going again; others carry on over HTTP, where an
    // event the server doesn't know reloads the page (and events bound globally still work).
    function pageExpired() {
        useHttp = true;
        if (document.querySelector('[data-live]')) window.location.reload();
    }

    async function sendOverSocket(ws, eventId, payload) {
        return new Promise((resolve, reject) => {
            const ref = ++nextRef;
            const timer = setTimeout(() => {
                waiting.delete(ref);
                reject(new Error('No answer from the server'));
            }, RESULT_TIMEOUT);
            waiting.set(ref, { resolve, reject, timer, ws });
            ws.send(JSON.stringify({ type: 'event', ref, page_id: pageId(), event_id: eventId, data: payload }));
        });
    }

    // POSTs go one at a time, so the server handles events in the order they fired, as it does
    // over the socket: an event fired from a predicted state needs the events before it handled
    let posting = Promise.resolve();

    function post(eventId, payload) {
        const result = posting.then(async () => {
            const response = await fetch('/_domino/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_id: pageId(), event_id: eventId, data: payload })
            });
            const data = await response.json().catch(() => ({ error: `${response.status} ${response.statusText}` }));
            return { status: response.status, data };
        });
        posting = result.catch(() => {});
        return result;
    }

    // Send an event over the socket when it's connected (waiting for one that's connecting),
    // otherwise POST it. Resolves to the server's { status, data }.
    async function sendEvent(eventId, payload) {
        const ws = socket;
        if (ws && await socketReady && socket === ws && ws.readyState === WebSocket.OPEN) {
            return sendOverSocket(ws, eventId, payload);
        }
        return post(eventId, payload);
    }

    // Components re-rendered with refresh() arrive over Server-Sent Events when there's no
    // socket. Only pages showing a live component open the stream. EventSource reconnects by
    // itself after a dropped connection but gives up on an error status, so an expired page
    // (404) stops.
    let stream = null;

    function openStream() {
        if (stream || !document.querySelector('[data-live]')) return;
        const id = pageId();
        if (!id) return;

        stream = new EventSource('/_domino/stream?page=' + encodeURIComponent(id));
        stream.onmessage = async (e) => {
            await wait(latency / 2);
            handleMessage(JSON.parse(e.data));
        };
    }

    // Another page was swapped in (see navigate): move the socket over to it, or open what it needs
    function rebind() {
        if (stream) {
            stream.close();
            stream = null;
        }
        if (!socket) {
            connect();
            return;
        }
        // A socket still connecting says hello for whatever page is shown when it opens
        if (socket.readyState !== WebSocket.OPEN) return;
        // The new page is in another worker process of `domino serve`: a socket to that one.
        // The old one answers the events it has in flight, then closes
        if (needsServer() && workerOf(pageId()) !== socket.worker) {
            const old = socket;
            old.retired = true;
            old.send(JSON.stringify({ type: 'leave' }));
            socket = null;
            socketReady = null;
            closeWhenIdle(old);
            connect();
            return;
        }
        if (needsServer()) {
            socketReady = new Promise((resolve) => { settleReady = resolve; });
            socket.send(JSON.stringify({ type: 'hello', page_id: pageId() }));
        } else {
            socket.send(JSON.stringify({ type: 'leave' }));
            socketReady = Promise.resolve(true);
        }
    }

    function closeWhenIdle(ws) {
        for (const request of waiting.values()) {
            if (request.ws === ws) return;
        }
        ws.close(1000);
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

    // A development aid, like LiveView's latency simulator: every round trip to the server
    // takes this many ms (half each way), so you can feel the app on a slow connection.
    // Set with Domino.enableLatencySim(ms) (kept for the tab) or the domino.latency setting.
    let latency = 0;

    function readLatency() {
        try {
            const stored = parseInt(sessionStorage.getItem('domino-latency'), 10);
            if (stored >= 0) return stored;
        } catch (err) {
            // Storage can be unavailable (private windows); fall back to the page's setting
        }
        const root = document.querySelector('[data-domino-latency]');
        return root ? parseInt(root.dataset.dominoLatency, 10) || 0 : 0;
    }

    function enableLatencySim(ms) {
        latency = Math.max(0, parseInt(ms, 10) || 0);
        try { sessionStorage.setItem('domino-latency', String(latency)); } catch (err) { /* see readLatency */ }
        console.info(`Domino: simulating ${latency} ms of latency per round trip`);
    }

    function disableLatencySim() {
        enableLatencySim(0);
    }

    function wait(ms) {
        return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();
    }

    // The files an event sends: a file input's own (on_change=), or those of a submitted form
    function selectedFiles(el) {
        if (el.tagName === 'INPUT' && el.type === 'file') {
            return Array.from(el.files || []).map((file) => [el.name || 'file', file]);
        }
        const files = [];
        if (el.tagName !== 'FORM') return files;
        new FormData(el).forEach((value, name) => {
            // An empty file input still sends a nameless file
            if (typeof value !== 'string' && value.name) files.push([name, value]);
        });
        return files;
    }

    // Elements uploading now, whose data-uploading a re-render mustn't remove
    const uploading = new WeakSet();

    // Files go up in a multipart POST of their own, never through the socket, and the event
    // then carries a token per file. XMLHttpRequest because fetch has no upload progress: the
    // element (and its form) get data-uploading="<percent>" and --domino-upload-progress (0 to 1)
    // for CSS. Resolves to the server's { status, data }.
    async function upload(el, files) {
        const form = el.closest('form');
        const marked = form && form !== el ? [el, form] : [el];
        const progress = (fraction) => {
            for (const node of marked) {
                uploading.add(node);
                node.setAttribute('data-uploading', String(Math.round(fraction * 100)));
                node.style.setProperty('--domino-upload-progress', String(fraction));
            }
        };
        progress(0);

        try {
            // A round trip of its own for the latency simulator
            await wait(latency / 2);
            const result = await postFiles(files, progress);
            await wait(latency / 2);
            return result;
        } finally {
            for (const node of marked) {
                uploading.delete(node);
                node.removeAttribute('data-uploading');
                node.style.removeProperty('--domino-upload-progress');
                if (node.getAttribute('style') === '') node.removeAttribute('style');
            }
        }
    }

    function postFiles(files, progress) {
        return new Promise((resolve) => {
            const body = new FormData();
            for (const [name, file] of files) body.append(name, file);
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/_domino/upload');
            // A cross-site form can't send this header, which makes the upload CSRF-safe
            xhr.setRequestHeader('X-Domino-Page', pageId());
            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) progress(e.loaded / e.total);
            };
            xhr.onload = () => {
                let data;
                try { data = JSON.parse(xhr.responseText); } catch (err) { data = { error: `${xhr.status} ${xhr.statusText}` }; }
                resolve({ status: xhr.status, data });
            };
            xhr.onerror = () => resolve({ status: 0, data: { error: 'Upload failed: no answer from the server' } });
            xhr.send(body);
        });
    }

    // `owner`: the id of the component whose predicted states the event moved through (see predict)
    async function triggerEvent(eventId, payload = {}, reset = null, el = null, owner = null) {
        const files = el ? selectedFiles(el) : [];
        const unmark = el ? markBusy(el, reset && reset.submit) : null;
        const page = pageId();
        let answered = false;
        if (inFlight++ === 0) document.documentElement.setAttribute('data-domino-loading', '');
        try {
            if (files.length) {
                const uploaded = await upload(el, files);
                if (uploaded.status !== 200) {
                    // Shown like a failed event (and an expired page reloads)
                    await handleMessage(uploaded.data, uploaded.status, { el, eventId, reset, unmark });
                    return;
                }
                payload = Object.assign({}, payload, { files: uploaded.data.files });
            }
            await wait(latency / 2);
            const { status, data } = await sendEvent(eventId, payload);
            await wait(latency / 2);
            // Before handling, so the answer to the last event in flight is shown
            if (owner) {
                release(owner);
                answered = true;
            }
            // Another page has been swapped in meanwhile; the answer was for the old one
            if (pageId() !== page) return;
            await handleMessage(data, status, { el, eventId, reset, unmark });
        } catch (err) {
            reportError(el, eventId, { error: String(err) });
        } finally {
            if (owner) {
                if (!answered) release(owner);
                settle(owner);
            }
            if (unmark) unmark();
            if (--inFlight === 0) document.documentElement.removeAttribute('data-domino-loading');
        }
    }

    // The server renders the states a component's handlers lead to when they only change its
    // own state (domino/optimistic.py), and ships them as inert JSON inside the component:
    // {states: [html, or the index of a state with the same html], edges: [{event: state}]}.
    // State 0 is the one the server rendered. Per component id: those states, which the page
    // shows (`key`, null when unknown), and its events in flight and the newest update that
    // came meanwhile (see apply).
    const graphs = new Map();
    const inflight = new Map();
    const deferred = new Map();

    // [id, graph] for each component in `root` that ships its states, read from the server's
    // HTML (so before anything changed it), whose own HTML is state 0
    function readGraphs(root) {
        const found = [];
        for (const script of within(root, 'script[data-domino-predict]')) {
            const owner = script.parentElement;
            if (!owner || !owner.id) continue;
            let graph;
            try { graph = JSON.parse(script.textContent); } catch (err) { continue; }
            const current = owner.cloneNode(true);
            current.querySelector(':scope > script[data-domino-predict]').remove();
            graph.states[0] = current.outerHTML;
            graph.states = graph.states.map((html) => (typeof html === 'number' ? graph.states[html] : html));
            found.push([owner.id, graph]);
        }
        return found;
    }

    function installGraph([id, graph]) {
        // With events still in flight, the server's state will move on from this one
        graph.key = inflight.get(id) > 0 ? null : 0;
        graphs.set(id, graph);
    }

    function showingGuess(id) {
        const graph = graphs.get(id);
        return graph && graph.key !== null;
    }

    // `reset`: as for the server's answer, which this stands in for
    function show(node, graph, key, reset = null) {
        const template = document.createElement('template');
        template.innerHTML = graph.states[key];
        const replacement = template.content.firstElementChild;
        if (!replacement || replacement.id !== node.id) return false;
        morph(node, replacement, reset);
        listen(node);
        graph.key = key;
        return true;
    }

    // Show where the event leads right away, from the component's states, following on from
    // the states earlier events led to, so any number of clicks show at once. The event still
    // goes to the server, whose answer to the last one in flight confirms it or puts it right.
    // Returns the id of the component whose events are being followed, if any.
    function predict(el, eventId, reset) {
        for (let node = el; node && node.nodeType === Node.ELEMENT_NODE; node = node.parentElement) {
            const prefix = 'event-' + node.id + '-';
            const graph = node.id && eventId.startsWith(prefix) && graphs.get(node.id);
            if (!graph) continue;

            inflight.set(node.id, (inflight.get(node.id) || 0) + 1);
            const edges = graph.key === null ? null : graph.edges[graph.key];
            const next = edges ? edges[eventId.slice(prefix.length)] : undefined;
            if (next === undefined || !show(node, graph, next, reset)) {
                // Where this leads is up to the server, and so is everything after it
                graph.key = null;
                return node.id;
            }
            // Until the server answers (its HTML doesn't have this), for styling if wanted
            node.setAttribute('data-predicted', '');
            return node.id;
        }
        return null;
    }

    // An event of the component was answered (or failed)
    function release(id) {
        inflight.set(id, inflight.get(id) - 1);
    }

    // Once the component's last event in flight is answered, the server has the last word
    function settle(id) {
        if (inflight.get(id) > 0) return;
        inflight.delete(id);
        const data = deferred.get(id);
        deferred.delete(id);
        if (data) apply(data);

        // Nothing from the server replaced the guess (the event failed, say): go back to the
        // state the server last rendered
        const node = document.getElementById(id);
        const graph = graphs.get(id);
        if (node && graph && node.hasAttribute('data-predicted')) {
            show(node, graph, 0);
            node.removeAttribute('data-predicted');
        }
    }

    function fire(el, eventId) {
        const submit = el.tagName === 'FORM' && eventId.endsWith('-submit');
        // The event's data first: showing where it leads may change the fields
        const payload = eventData(el);
        const reset = { root: el, submit };
        const owner = predict(el, eventId, reset);
        triggerEvent(eventId, payload, reset, el, owner);
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
            // Not if another page has been swapped in meanwhile
            if (el.isConnected) fire(el, eventId);
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

    // Links to other pages of the app swap the new page in instead of loading it from scratch,
    // like a single-page app with no router to write: this script, the WebSocket and the parts of
    // the page that stay the same (the layout's navigation, say) are kept. Links inside an element
    // with data-domino-reload load as usual; {"domino": {"navigation": false}} marks pages so.
    let navigation = null; // the AbortController of the navigation in flight
    let shown = location.pathname + location.search; // the page shown, to tell #hash changes apart
    let entry = null; // the history entry shown, for its scroll position
    const scrolls = new Map();
    let announcer = null;

    function navigationOn() {
        return !!window.history.pushState && !document.querySelector('[data-domino-page][data-domino-reload]');
    }

    function onClick(e) {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        const link = e.target.closest ? e.target.closest('a[href]') : null;
        if (!link || typeof link.href !== 'string' || link.closest('[data-domino-reload]') || !navigationOn()) return;
        if ((link.target && link.target !== '_self') || link.hasAttribute('download')) return;

        // mailto: and other schemes have another origin too
        const url = new URL(link.href);
        if (url.origin !== location.origin) return;
        // A #hash on this page scrolls, as usual
        if (url.hash && url.pathname + url.search === shown) return;

        e.preventDefault();
        navigate(url.href, true, link);
    }

    function onPopState(e) {
        // Only the #hash changed, or the page's own script added this entry
        if (location.pathname + location.search === shown || !navigationOn()) return;
        if (e.state && !e.state.domino) return;

        scrolls.set(entry, [window.scrollX, window.scrollY]);
        entry = e.state ? e.state.domino : null;
        navigate(location.href, false, null, scrolls.get(entry));
    }

    // Show the page at `url` in place of this one: a new history entry (`push`), or the one
    // back/forward went to. Anything that isn't a page of this app loads as usual.
    async function navigate(url, push = true, link = null, scroll = null) {
        // With no socket to tell, the request says which page this tab leaves, so the server
        // can drop it; not while events are in flight, which still need it
        const headers = { 'X-Domino-Navigate': '1' };
        const events = inFlight - (navigation ? 1 : 0);
        if (!socket && events === 0 && pageId()) headers['X-Domino-Leave'] = pageId();

        if (navigation) navigation.abort();
        const controller = navigation = new AbortController();

        const unmark = link ? markBusy(link, false) : null;
        if (inFlight++ === 0) document.documentElement.setAttribute('data-domino-loading', '');
        try {
            await wait(latency / 2);
            const response = await fetch(url, { headers, signal: controller.signal });
            const html = (response.headers.get('Content-Type') || '').includes('text/html') ? await response.text() : null;
            await wait(latency / 2);
            if (controller.signal.aborted) return;

            // Redirects within the site are followed (e.g. to the login page)
            const target = new URL(response.url || url);
            const doc = html === null ? null : new DOMParser().parseFromString(html, 'text/html');
            if (!doc || !doc.querySelector('[data-domino-page]') || target.origin !== location.origin) {
                loadAsUsual(url, push);
                return;
            }
            if (!response.redirected) target.hash = new URL(url).hash;

            if (push) {
                if (!history.state || !history.state.domino) {
                    entry = entry || String(Math.random());
                    history.replaceState({ domino: entry }, '');
                }
                scrolls.set(entry, [window.scrollX, window.scrollY]);
                entry = String(Math.random());
                history.scrollRestoration = 'manual';
                history.pushState({ domino: entry }, '', target.href);
            } else if (response.redirected) {
                history.replaceState({ domino: entry }, '', target.href);
            }

            swap(doc);
            arrive(target.hash, scroll);
        } catch (err) {
            if (!controller.signal.aborted) loadAsUsual(url, push);
        } finally {
            if (unmark) unmark();
            if (--inFlight === 0) document.documentElement.removeAttribute('data-domino-loading');
            if (navigation === controller) navigation = null;
        }
    }

    function loadAsUsual(url, push) {
        if (push) {
            window.location.assign(url);
        } else {
            window.location.replace(url);
        }
    }

    // Do what a page load does, keeping what's the same: the whole document is morphed into the
    // new one, its fields taking the new page's values
    function swap(doc) {
        const scripts = new Set(document.scripts);
        latest.clear();
        // The new page's components and their states, read from its HTML before it's shown
        const found = readGraphs(doc.documentElement);

        morph(document.documentElement, doc.documentElement, { root: document.documentElement, submit: true });
        graphs.clear();
        deferred.clear();
        found.forEach(installGraph);
        document.documentElement.setAttribute('data-domino-loading', '');
        shown = location.pathname + location.search;

        // Scripts the new page adds run, as they would on a page load (this one only once)
        for (const old of Array.from(document.scripts)) {
            if (scripts.has(old) || !/^$|javascript|module/.test(old.type) || old.src.endsWith('/_domino/core')) continue;
            const script = document.createElement('script');
            for (const { name, value } of Array.from(old.attributes)) script.setAttribute(name, value);
            script.textContent = old.textContent;
            old.replaceWith(script);
        }

        latency = readLatency();
        listen();
        scheduleAfterEvents();
        rebind();
    }

    // Scroll as a page load would, and move focus to the new page and announce it, as a
    // screen reader would on a page load
    function arrive(hash, scroll) {
        const anchor = hash ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
        if (scroll) {
            window.scrollTo(scroll[0], scroll[1]);
        } else if (anchor) {
            anchor.scrollIntoView();
        } else {
            window.scrollTo(0, 0);
        }

        const focus = ['[autofocus]', 'main h1', 'h1', 'main'].map((selector) => document.querySelector(selector)).find(Boolean);
        if (focus) {
            if (focus.tabIndex < 0 && !focus.hasAttribute('tabindex')) focus.setAttribute('tabindex', '-1');
            focus.focus({ preventScroll: true });
        } else if (document.activeElement) {
            document.activeElement.blur();
        }

        if (!announcer) {
            announcer = document.createElement('div');
            announcer.setAttribute('aria-live', 'polite');
            announcer.style.cssText = 'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap';
        }
        announcer.textContent = '';
        document.body.appendChild(announcer);
        setTimeout(() => { announcer.textContent = document.title; }, 100);
    }

    document.addEventListener('DOMContentLoaded', () => {
        latency = readLatency();
        readGraphs(document).forEach(installGraph);
        listen();
        scheduleAfterEvents();
        connect();
        document.addEventListener('click', onClick);
        window.addEventListener('popstate', onPopState);
    });

    return { settings, listen, scheduleAfterEvents, triggerEvent, morph, bindEvents: listen, enableLatencySim, disableLatencySim, navigate };
})();
