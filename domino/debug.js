// Domino's developer tools, served at /_domino/debug.js and loaded only by pages rendered in debug
// mode (see domino/devtools.py); production pages never load it, and the URL answers 404 there.
// - The error overlay for a failed event: the frames with their source (the app's own open,
//   libraries' folded), the component stack, hints, and which element and handler fired.
// - The component inspector: Domino.inspect() in the console, or Alt+Shift+D, then hover a
//   component to outline it and click to pin a panel with its State (kept up to date), events,
//   whether they're predicted and why not, what it subscribed to, and its ancestors.
// - The event log, in the panel's second tab: the page's last events with their timings, sizes
//   and whether a prediction was shown and matched the server's answer.
// Text from the server always goes in as textContent, never as HTML.
(() => {
    const Domino = window.Domino;
    if (!Domino || Domino.devtools) return;

    const LOG_SIZE = 50;
    const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
    const IS_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

    const CSS = `
.domino-dt, .domino-dt * { all: revert; box-sizing: border-box; }
.domino-dt { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
.domino-dt code, .domino-dt .dt-mono { font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.domino-dt button { font: inherit; cursor: pointer; }
#domino-error.domino-dt { position: fixed; left: 1rem; right: 1rem; bottom: 1rem; z-index: 2147483647; max-height: 70vh; overflow: auto;
    background: #fff; color: #1d1d1f; border: 2px solid #c4302b; border-radius: 8px; padding: 1rem 1.25rem; box-shadow: 0 8px 32px rgba(0,0,0,.3); font-size: 14px; }
#domino-error .dt-close { float: right; font-size: 1.4rem; line-height: 1; border: 0; background: none; color: #6b6b70; padding: 0 .25rem; }
#domino-error .dt-title { display: block; color: #c4302b; font-size: 1.15rem; font-weight: 700; margin-right: 2rem; overflow-wrap: anywhere; white-space: pre-wrap; }
#domino-error .dt-meta { color: #6b6b70; margin: .3rem 0 0; }
#domino-error .dt-meta code { color: #1d1d1f; background: #f2f2f0; border-radius: 3px; padding: 0 .3rem; }
#domino-error h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: #6b6b70; margin: 1rem 0 .4rem; }
#domino-error .dt-hint { background: #fff8e6; border-left: 4px solid #d29922; border-radius: 4px; padding: .5rem .75rem; margin: .5rem 0 0; }
#domino-error .dt-path { display: flex; flex-wrap: wrap; gap: .25rem; list-style: none; margin: 0; padding: 0; }
#domino-error .dt-path li { border: 1px solid #e3e3e0; border-radius: 4px; padding: 0 .45rem; font: 12px ui-monospace, monospace; }
#domino-error .dt-path li { position: relative; }
#domino-error .dt-path li + li { margin-left: 1rem; }
#domino-error .dt-path li + li::before { content: "›"; color: #9a9aa2; position: absolute; left: -.8rem; }
#domino-error .dt-path li.dt-failed { border-color: #c4302b; color: #c4302b; font-weight: 600; }
#domino-error .dt-frame { border: 1px solid #e3e3e0; border-radius: 6px; margin: 0 0 .4rem; overflow: hidden; }
#domino-error .dt-frame.dt-app { border-left: 4px solid #1f6feb; }
#domino-error .dt-frame-head { display: flex; justify-content: space-between; gap: 1rem; padding: .3rem .6rem; font: 12px ui-monospace, monospace; }
#domino-error .dt-frame-head b { font-weight: 600; }
#domino-error .dt-frame-head span { color: #6b6b70; overflow-wrap: anywhere; text-align: right; }
#domino-error .dt-source { background: #fafaf8; border-top: 1px solid #e3e3e0; padding: .25rem 0; overflow-x: auto; }
#domino-error .dt-source div { white-space: pre; padding: 0 .6rem; font: 12px/1.55 ui-monospace, monospace; }
#domino-error .dt-source .dt-current { background: #fff4d6; }
#domino-error .dt-number { display: inline-block; width: 3.2em; color: #9a9aa2; user-select: none; }
#domino-error details { margin: 0 0 .4rem; }
#domino-error summary { cursor: pointer; color: #6b6b70; padding: .15rem 0; }
#domino-error pre { font: 12px/1.5 ui-monospace, monospace; white-space: pre-wrap; margin: .4rem 0 0; }
#domino-highlight, #domino-selected { position: fixed; z-index: 2147483646; pointer-events: none; display: none; }
#domino-highlight { outline: 2px solid #7aa2f7; background: rgba(122, 162, 247, .12); }
#domino-selected { outline: 2px dashed #e0af68; }
#domino-highlight .dt-label { position: absolute; left: -2px; bottom: 100%; margin-bottom: 2px; white-space: nowrap; background: #1f2335; color: #c0caf5;
    border-radius: 3px; padding: 1px 6px; font: 600 11px/1.5 ui-monospace, monospace; }
#domino-highlight .dt-label.dt-below { bottom: auto; top: 100%; margin: 2px 0 0; }
#domino-highlight .dt-label span { color: #7f88a8; font-weight: 400; }
html[data-domino-inspecting], html[data-domino-inspecting] * { cursor: crosshair !important; }
#domino-inspector.domino-dt { position: fixed; right: 12px; bottom: 12px; z-index: 2147483647; width: min(480px, calc(100vw - 24px)); max-height: min(70vh, 640px);
    display: flex; flex-direction: column; background: #16161e; color: #c8cbd9; border: 1px solid #2a2b3d; border-radius: 10px; box-shadow: 0 12px 40px rgba(0,0,0,.45); overflow: hidden; }
#domino-inspector .dt-bar { display: flex; align-items: center; gap: .25rem; padding: .35rem .5rem; background: #1a1b26; border-bottom: 1px solid #2a2b3d; }
#domino-inspector .dt-brand { font-weight: 700; color: #7aa2f7; margin-right: .5rem; letter-spacing: .02em; }
#domino-inspector .dt-tab, #domino-inspector .dt-tool { border: 0; background: none; color: #9aa0b8; padding: .2rem .55rem; border-radius: 5px; }
#domino-inspector .dt-tab[aria-selected=true] { background: #292e42; color: #fff; }
#domino-inspector .dt-tool:hover, #domino-inspector .dt-tab:hover { color: #fff; }
#domino-inspector .dt-tool[aria-pressed=true] { color: #7aa2f7; }
#domino-inspector .dt-spacer { flex: 1; }
#domino-inspector .dt-body { overflow: auto; padding: .6rem .75rem .9rem; }
#domino-inspector .dt-empty { color: #737aa2; margin: .5rem 0; }
#domino-inspector .dt-name { font-size: 15px; font-weight: 700; color: #fff; margin: 0; }
#domino-inspector .dt-name code { color: #7f88a8; font-weight: 400; margin-left: .4rem; }
#domino-inspector .dt-where { color: #737aa2; margin: .1rem 0 .5rem; }
#domino-inspector .dt-crumbs { display: flex; flex-wrap: wrap; gap: .2rem; margin: 0 0 .25rem; }
#domino-inspector .dt-crumb { border: 1px solid #2a2b3d; background: #1a1b26; color: #9aa0b8; border-radius: 4px; padding: 0 .4rem; font: 11px/1.6 ui-monospace, monospace; }
#domino-inspector .dt-crumb:hover { border-color: #7aa2f7; color: #fff; }
#domino-inspector .dt-crumb.dt-self { border-color: #e0af68; color: #e0af68; cursor: default; }
#domino-inspector h4 { font-size: 10.5px; text-transform: uppercase; letter-spacing: .09em; color: #737aa2; margin: .85rem 0 .3rem; font-weight: 600; }
#domino-inspector table { width: 100%; border-collapse: collapse; }
#domino-inspector td, #domino-inspector th { text-align: left; vertical-align: top; padding: .15rem .4rem .15rem 0; border-top: 1px solid #222336; overflow-wrap: anywhere; }
#domino-inspector th { color: #737aa2; font-weight: 500; font-size: 11px; }
#domino-inspector td.dt-key { color: #bb9af7; width: 34%; font: 12px ui-monospace, monospace; }
#domino-inspector td.dt-value { color: #c3e88d; font: 12px ui-monospace, monospace; }
#domino-inspector .dt-event { border-top: 1px solid #222336; padding: .3rem 0; }
#domino-inspector .dt-event code { color: #c8cbd9; }
#domino-inspector .dt-yes { color: #9ece6a; }
#domino-inspector .dt-no { color: #e0af68; }
#domino-inspector .dt-bad { color: #f7768e; }
#domino-inspector .dt-reason { color: #737aa2; margin: .1rem 0 0 1rem; }
#domino-inspector ul { margin: 0; padding-left: 1.1rem; }
#domino-inspector li { font: 12px/1.6 ui-monospace, monospace; }
#domino-inspector .dt-log td { font: 11.5px/1.5 ui-monospace, monospace; white-space: nowrap; }
#domino-inspector .dt-log td.dt-wrap { white-space: normal; }
#domino-inspector .dt-num { text-align: right; padding-right: .6rem; color: #c8cbd9; }
#domino-inspector .dt-type { color: #7dcfff; }
#domino-inspector .dt-handler { color: #9aa0b8; }
#domino-inspector .dt-handler.dt-bad { color: #f7768e; }
`;

    function pageId() {
        const root = document.querySelector('[data-domino-page]');
        return root ? root.dataset.dominoPage : null;
    }

    // Build an element; strings become text nodes, so nothing from the server is parsed as HTML
    function h(tag, props, ...children) {
        const el = document.createElement(tag);
        for (const [name, value] of Object.entries(props || {})) {
            if (value === null || value === undefined || value === false) continue;
            if (name.startsWith('on')) el.addEventListener(name.slice(2), value);
            else if (name === 'text') el.textContent = value;
            else el.setAttribute(name, value === true ? '' : value);
        }
        for (const child of children.flat(Infinity)) {
            if (child === null || child === undefined || child === false) continue;
            el.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
        return el;
    }

    function addStyles() {
        if (document.getElementById('domino-devtools-css')) return;
        document.head.appendChild(h('style', { id: 'domino-devtools-css', text: CSS }));
    }

    // Our own elements, which the inspector never picks and whose changes it ignores
    function ours(node) {
        const el = node && node.nodeType === Node.ELEMENT_NODE ? node : node && node.parentElement;
        return !!(el && el.closest('.domino-dt, #domino-highlight, #domino-selected, #domino-devtools-css'));
    }

    // "button.save "Save"": what an element is, for people
    function describe(el) {
        if (!el || !el.tagName) return '(none)';
        let text = el.tagName.toLowerCase();
        if (el.id && !IS_UUID.test(el.id)) text += '#' + el.id;
        const classes = Array.from(el.classList).slice(0, 2);
        if (classes.length) text += '.' + classes.join('.');
        if (el.getAttribute('name')) text += `[name=${el.getAttribute('name')}]`;
        const words = (el.textContent || '').trim().replace(/\s+/g, ' ');
        if (words && !['FORM', 'BODY', 'HTML'].includes(el.tagName)) text += ` "${words.length > 24 ? words.slice(0, 23) + '…' : words}"`;
        return text;
    }

    function eventType(eventId) {
        if (!eventId) return '?';
        return eventId.startsWith('after-') ? 'after' : eventId.split('-').pop();
    }

    function bytes(value) {
        try { return new Blob([JSON.stringify(value)]).size; } catch (err) { return 0; }
    }

    function formatBytes(n) {
        return n >= 1024 ? (n / 1024).toFixed(1) + ' KB' : n + ' B';
    }

    // ---- The error overlay ------------------------------------------------------------------

    function sourceBlock(context, current) {
        if (!context || !context.length) return null;
        return h('div', { class: 'dt-source' }, context.map(([number, text]) => h('div', { class: number === current ? 'dt-current' : null },
            h('span', { class: 'dt-number', text: String(number) }), text)));
    }

    function frameBlock(frame) {
        return h('div', { class: 'dt-frame' + (frame.app ? ' dt-app' : ''), 'data-app': String(!!frame.app) },
            h('div', { class: 'dt-frame-head' },
                h('b', { text: frame.function + (frame.template ? ' (template)' : '') }),
                h('span', { text: `${frame.file}:${frame.line}` })),
            sourceBlock(frame.context, frame.line));
    }

    // The app's frames open, each run of library frames folded
    function frameList(frames) {
        const out = [];
        let run = [];
        const flush = () => {
            if (!run.length) return;
            const where = Array.from(new Set(run.map((frame) => frame.file.split('/')[0])));
            out.push(h('details', { class: 'dt-library' },
                h('summary', { text: `${run.length} library frame${run.length > 1 ? 's' : ''} (${where.slice(0, 3).join(', ')}${where.length > 3 ? ', …' : ''})` }),
                run.map(frameBlock)));
            run = [];
        };
        for (const frame of frames) {
            if (frame.app) {
                flush();
                out.push(frameBlock(frame));
            } else {
                run.push(frame);
            }
        }
        flush();
        return out;
    }

    function closeError() {
        const old = document.getElementById('domino-error');
        if (old) old.remove();
    }

    function showError(el, detail, data) {
        addStyles();
        closeError();

        const meta = [];
        if (detail.eventId) {
            meta.push(h('code', { text: eventType(detail.eventId) }), ' on ', h('code', { text: describe(el) }));
            if (data.handler) meta.push(' → ', h('code', { text: data.handler }));
        }

        const sections = [];
        if (data.hints && data.hints.length) {
            sections.push(data.hints.map((hint) => h('p', { class: 'dt-hint', text: hint })));
        }
        if (data.components && data.components.length) {
            sections.push(h('h3', { text: 'Component stack' }), h('ol', { class: 'dt-path' },
                data.components.map((name, index) => h('li', { class: index === data.components.length - 1 ? 'dt-failed' : null, text: name }))));
        }
        if (data.template) {
            const where = data.template.relative ? `line ${data.template.line} of the template string in ${data.template.file}` : `${data.template.file}, line ${data.template.line}`;
            sections.push(h('h3', { text: 'Template' }), h('div', { class: 'dt-frame dt-app' },
                h('div', { class: 'dt-frame-head' }, h('b', { text: where })), sourceBlock(data.template.context, data.template.line)));
        }
        if (data.frames && data.frames.length) {
            sections.push(h('h3', { text: 'Traceback (most recent call last)' }), frameList(data.frames));
        }

        const overlay = h('div', { id: 'domino-error', class: 'domino-dt', role: 'alert' },
            h('button', { type: 'button', class: 'dt-close', 'aria-label': 'Close', text: '×', onclick: closeError }),
            h('strong', { class: 'dt-title', text: detail.error }),
            meta.length ? h('p', { class: 'dt-meta' }, meta) : null,
            sections,
            detail.traceback ? h('details', {}, h('summary', { text: 'Plain traceback' }), h('pre', { text: detail.traceback })) : null);
        document.body.appendChild(overlay);
    }

    // ---- The event log ----------------------------------------------------------------------

    const log = [];
    let logPage = null;
    let counter = 0;

    // The predicted HTML and the server's, compared without what differs between renders anyway:
    // whitespace, random ids (of components a render makes anew) and prediction markers
    function normalize(html) {
        const template = document.createElement('template');
        template.innerHTML = html;
        const root = template.content.firstElementChild;
        if (!root) return String(html);
        root.querySelectorAll('script[data-domino-predict]').forEach((script) => script.remove());
        root.removeAttribute('data-predicted');
        return root.outerHTML.replace(UUID, '#').replace(/\s+/g, ' ').replace(/> </g, '><').trim();
    }

    // Called by core.js when an event is sent, with the component's predicted states if it has
    // any; returns what it calls with the answer
    function watchEvent(eventId, el, payload, graph) {
        if (pageId() !== logPage) {
            log.length = 0;
            logPage = pageId();
        }
        const guess = graph && graph.key !== null && graph.key !== undefined ? graph.states[graph.key] : null;
        const entry = {
            n: ++counter,
            event: eventType(eventId),
            eventId,
            element: describe(el),
            handler: null,
            serverMs: null,
            roundTrip: null,
            sent: bytes(payload),
            received: null,
            predicted: guess !== null,
            matched: null,
            status: null,
        };
        const started = performance.now();
        log.unshift(entry);
        if (log.length > LOG_SIZE) log.length = LOG_SIZE;
        renderPanel();

        let done = false;
        return (status, data) => {
            if (done) return;
            done = true;
            entry.roundTrip = Math.round(performance.now() - started);
            entry.status = status;
            entry.received = bytes(data);
            if (data) {
                entry.handler = data.debug_handler || data.handler || null;
                entry.serverMs = typeof data.debug_ms === 'number' ? data.debug_ms : null;
                if (guess !== null && status === 200 && data.html) entry.matched = normalize(guess) === normalize(data.html);
            }
            renderPanel();
            refreshSoon();
        };
    }

    // ---- The inspector ----------------------------------------------------------------------

    const inspector = {
        picking: false,
        open: false,
        tab: 'component',
        selected: null, // the id of the pinned component
        data: null, // its data from the server
        error: null,
        components: new Map(), // id -> class name, of the page's components
        componentsPage: null,
    };

    let panel = null;
    let highlight = null;
    let selectedBox = null;

    async function getJSON(what, params) {
        const query = params ? '?' + new URLSearchParams(params) : '';
        const response = await fetch('/_domino/debug/' + what + query, { headers: { 'X-Domino-Page': pageId() || '' } });
        const data = await response.json().catch(() => ({ error: `${response.status} ${response.statusText}` }));
        if (!response.ok) throw new Error(data.error || response.statusText);
        return data;
    }

    async function loadComponents() {
        try {
            const data = await getJSON('components');
            inspector.components = new Map(data.components.map((item) => [item.id, item.class]));
            inspector.componentsPage = pageId();
        } catch (err) {
            inspector.components = new Map();
        }
    }

    // The innermost component around `node`, as [element, class name]
    function componentAt(node) {
        for (let el = node && node.nodeType === Node.ELEMENT_NODE ? node : node && node.parentElement; el; el = el.parentElement) {
            if (el.id && inspector.components.has(el.id)) return [el, inspector.components.get(el.id)];
        }
        return null;
    }

    function place(box, el) {
        const rect = el.getBoundingClientRect();
        box.style.display = 'block';
        box.style.left = rect.left + 'px';
        box.style.top = rect.top + 'px';
        box.style.width = rect.width + 'px';
        box.style.height = rect.height + 'px';
        return rect;
    }

    function showHighlight(el, name) {
        if (!highlight || !highlight.isConnected) {
            highlight = h('div', { id: 'domino-highlight' }, h('div', { class: 'dt-label' }));
            document.body.appendChild(highlight);
        }
        const rect = place(highlight, el);
        const label = highlight.firstChild;
        label.textContent = name + ' ';
        label.append(h('span', { text: `${el.tagName.toLowerCase()} ${Math.round(rect.width)}×${Math.round(rect.height)}` }));
        label.classList.toggle('dt-below', rect.top < 22);
    }

    function hideHighlight() {
        if (highlight) highlight.style.display = 'none';
    }

    function placeSelected() {
        const el = inspector.selected && inspector.open ? document.getElementById(inspector.selected) : null;
        if (!el) {
            if (selectedBox) selectedBox.style.display = 'none';
            return;
        }
        if (!selectedBox || !selectedBox.isConnected) {
            selectedBox = h('div', { id: 'domino-selected' });
            document.body.appendChild(selectedBox);
        }
        place(selectedBox, el);
    }

    function onMove(e) {
        if (!inspector.picking) return;
        if (ours(e.target)) {
            hideHighlight();
            return;
        }
        const found = componentAt(e.target);
        if (found) showHighlight(found[0], found[1]); else hideHighlight();
    }

    // While picking, clicks pick instead of reaching the page (and its events)
    function onPointer(e) {
        if (!inspector.picking || ours(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        if (e.type !== 'click') return;
        const found = componentAt(e.target);
        if (!found) return;
        stopPicking();
        select(found[0].id);
    }

    function startPicking() {
        addStyles();
        inspector.picking = true;
        document.documentElement.setAttribute('data-domino-inspecting', '');
        openPanel();
        loadComponents();
    }

    function stopPicking() {
        inspector.picking = false;
        document.documentElement.removeAttribute('data-domino-inspecting');
        hideHighlight();
        renderPanel();
    }

    // Domino.inspect(): turn picking on or off. Domino.inspect(element or id) inspects that component.
    function inspect(target) {
        if (target !== undefined) {
            const el = typeof target === 'string' ? document.getElementById(target) : target;
            const run = async () => {
                await loadComponents();
                const found = componentAt(el);
                if (found) select(found[0].id);
            };
            addStyles();
            openPanel();
            run();
            return true;
        }
        if (inspector.picking) {
            stopPicking();
            return false;
        }
        startPicking();
        return true;
    }

    async function select(id) {
        if (!inspector.picking) hideHighlight();
        inspector.selected = id;
        inspector.tab = 'component';
        openPanel();
        await refresh();
    }

    async function refresh() {
        if (!inspector.selected || !inspector.open) return;
        const id = inspector.selected;
        try {
            const data = await getJSON('inspect', { id });
            if (inspector.selected !== id) return;
            inspector.data = data;
            inspector.error = null;
        } catch (err) {
            if (inspector.selected !== id) return;
            inspector.error = String(err.message || err);
        }
        renderPanel();
    }

    let refreshTimer = null;

    function refreshSoon() {
        if (!inspector.open || !inspector.selected) return;
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(refresh, 80);
    }

    function openPanel() {
        addStyles();
        inspector.open = true;
        renderPanel();
    }

    function closePanel() {
        inspector.open = false;
        inspector.selected = null;
        inspector.data = null;
        if (inspector.picking) stopPicking();
        if (panel) panel.remove();
        panel = null;
        placeSelected();
    }

    function crumb(item, self) {
        return h('button', {
            type: 'button',
            class: 'dt-crumb' + (self ? ' dt-self' : ''),
            text: item.class,
            onclick: self ? null : () => select(item.id),
            onmouseenter: () => {
                const el = document.getElementById(item.id);
                if (el) showHighlight(el, item.class);
            },
            onmouseleave: () => { if (!inspector.picking) hideHighlight(); },
        });
    }

    function rows(items) {
        if (!items.length) return h('p', { class: 'dt-empty', text: 'None' });
        return h('table', {}, h('tbody', {}, items.map((item) => h('tr', {},
            h('td', { class: 'dt-key', text: item.name }), h('td', { class: 'dt-value', text: item.value })))));
    }

    function componentView() {
        if (inspector.error) return [h('p', { class: 'dt-empty', text: `Can't inspect it: ${inspector.error}. It may have been re-rendered away; pick it again.` })];
        const data = inspector.data;
        if (!data) {
            return [h('p', { class: 'dt-empty', text: inspector.picking
                ? 'Hover a component to outline it, click to inspect it. Esc stops.'
                : 'Pick a component (the crosshair, Alt+Shift+D or Domino.inspect()) to inspect it.' })];
        }

        const out = [
            h('p', { class: 'dt-name' }, data.class, h('code', { text: `<${data.tag}>${data.live ? ' live' : ''}` })),
            h('p', { class: 'dt-where dt-mono', text: data.file ? `${data.file}:${data.line}` : data.module }),
            h('div', { class: 'dt-crumbs' }, data.ancestors.map((item) => crumb(item, false)), crumb(data, true)),
            h('h4', { text: 'State' }), rows(data.state),
            h('h4', { text: 'Events' }),
        ];

        if (!data.events.length) out.push(h('p', { class: 'dt-empty', text: 'None bound by its render' }));
        for (const event of data.events) {
            out.push(h('div', { class: 'dt-event' },
                h('div', {}, h('code', { text: event.event }), ' on ', h('code', { text: event.element }), ' → ', h('code', { text: event.handler }), ' ',
                    event.predicted ? h('span', { class: 'dt-yes', text: '⚡ instant' }) : h('span', { class: 'dt-no', text: 'waits for the server' })),
                event.reason ? h('div', { class: 'dt-reason', text: event.reason }) : null));
        }

        out.push(h('h4', { text: 'Subscribed to (last render)' }));
        out.push(data.subscriptions.length ? h('ul', {}, data.subscriptions.map((item) => h('li', { text: item }))) : h('p', { class: 'dt-empty', text: 'Nothing reactive' }));
        if (data.children.length) {
            out.push(h('h4', { text: 'Child components' }), h('div', { class: 'dt-crumbs' }, data.children.map((item) => crumb(item, false))));
        }
        out.push(h('h4', { text: 'Attributes' }), rows(data.attributes));
        if (data.fields.length) out.push(h('h4', { text: 'Instance attributes' }), rows(data.fields));
        return out;
    }

    function instantCell(entry) {
        if (!entry.predicted) return h('td', { class: 'dt-no', text: 'no' });
        if (entry.matched === true) return h('td', { class: 'dt-yes', text: '✓ matched' });
        if (entry.matched === false) return h('td', { class: 'dt-bad', text: '✗ differed' });
        return h('td', { class: 'dt-yes', text: entry.status === null ? 'shown…' : 'shown' });
    }

    function logView() {
        if (!log.length) return [h('p', { class: 'dt-empty', text: 'No events yet on this page. Click around.' })];
        const ms = (value) => (value === null ? '…' : `${value} ms`);
        return [h('table', { class: 'dt-log' },
            h('thead', {}, h('tr', {}, ['#', 'Event → handler', 'Server', 'Round trip', 'Size ↑/↓', 'Instant'].map((name) => h('th', { text: name })))),
            h('tbody', {}, log.map((entry) => h('tr', { 'data-status': entry.status === null ? 'pending' : String(entry.status) },
                h('td', { class: 'dt-num', text: String(entry.n) }),
                h('td', { class: 'dt-wrap', title: entry.eventId },
                    h('div', {}, h('code', { class: 'dt-type', text: entry.event }), ' ', entry.element),
                    h('div', { class: 'dt-handler ' + (entry.status && entry.status !== 200 ? 'dt-bad' : ''),
                        text: '→ ' + (entry.handler || (entry.status && entry.status !== 200 ? `failed (${entry.status})` : '…')) })),
                h('td', { class: 'dt-num dt-server', text: ms(entry.serverMs) }),
                h('td', { class: 'dt-num dt-rtt', text: ms(entry.roundTrip) }),
                h('td', { class: 'dt-num', text: `${formatBytes(entry.sent)} / ${entry.received === null ? '…' : formatBytes(entry.received)}` }),
                instantCell(entry)))))];
    }

    function renderPanel() {
        if (!inspector.open) return;
        if (!panel || !panel.isConnected) {
            panel = h('div', { id: 'domino-inspector', class: 'domino-dt', role: 'dialog', 'aria-label': 'Domino inspector' });
            document.body.appendChild(panel);
        }
        const scroll = panel.querySelector('.dt-body') ? panel.querySelector('.dt-body').scrollTop : 0;
        const tab = (name, text) => h('button', { type: 'button', class: 'dt-tab', role: 'tab', 'aria-selected': String(inspector.tab === name), text,
            onclick: () => { inspector.tab = name; renderPanel(); } });
        const body = h('div', { class: 'dt-body' }, inspector.tab === 'component' ? componentView() : logView());
        panel.replaceChildren(
            h('div', { class: 'dt-bar' },
                h('span', { class: 'dt-brand', text: 'Domino' }),
                tab('component', 'Component'),
                tab('events', `Events (${log.length})`),
                h('span', { class: 'dt-spacer' }),
                h('button', { type: 'button', class: 'dt-tool dt-pick', title: 'Pick a component (Alt+Shift+D)', 'aria-label': 'Pick a component',
                    'aria-pressed': String(inspector.picking), text: '⌖', onclick: () => (inspector.picking ? stopPicking() : startPicking()) }),
                h('button', { type: 'button', class: 'dt-tool', title: 'Close', 'aria-label': 'Close inspector', text: '×', onclick: closePanel })),
            body);
        body.scrollTop = scroll;
        placeSelected();
    }

    // Re-render the panel when the pinned component changes in the page (an event's answer, a
    // push, a prediction), and keep the list of components fresh while picking
    let componentsTimer = null;
    const observer = new MutationObserver((mutations) => {
        if (mutations.every((mutation) => ours(mutation.target))) return;
        if (panel && !panel.isConnected && inspector.open) {
            // Another page was swapped in: its components are others
            inspector.selected = null;
            inspector.data = null;
            panel = null;
            renderPanel();
        }
        const el = inspector.selected ? document.getElementById(inspector.selected) : null;
        if (inspector.selected && (!el || mutations.some((mutation) => el.contains(mutation.target) || mutation.target.contains(el)))) refreshSoon();
        placeSelected();
        if (inspector.picking || inspector.componentsPage !== pageId()) {
            clearTimeout(componentsTimer);
            componentsTimer = setTimeout(loadComponents, 100);
        }
    });

    function start() {
        observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
        window.addEventListener('mousemove', onMove, true);
        for (const type of ['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'dblclick', 'auxclick']) window.addEventListener(type, onPointer, true);
        window.addEventListener('scroll', placeSelected, { passive: true, capture: true });
        window.addEventListener('resize', placeSelected);
        window.addEventListener('keydown', (e) => {
            if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyD') {
                e.preventDefault();
                inspect();
            } else if (e.key === 'Escape') {
                if (inspector.picking) stopPicking(); else closeError();
            }
        }, true);
        console.info('Domino debug mode: Alt+Shift+D or Domino.inspect() opens the component inspector.');
    }

    Domino.devtools = { showError, event: watchEvent, log, inspector };
    Domino.inspect = inspect;

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
