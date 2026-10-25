// Client components (see domino/client.py): components with `client = True` run here, in Python,
// on MicroPython or Pyodide compiled to WebAssembly. The server renders each one's first HTML,
// marked data-domino-client, with its State in data-domino-state; core.js imports this module
// when a page shows one. It starts the runtime once, gives it Domino's client package (CONFIG.shim)
// and each component's module, and then runs the component's handlers and re-renders here, morphing
// the result into the page with core.js's morph. Nothing goes to the server unless the component
// calls self.emit(), so it keeps working offline. The server prepends CONFIG.

const islands = new Map(); // element id -> { id, el, types, timers }
const modules = new Map(); // module key -> promise of its loading
let runtime = null; // promise of the runtime's `domino` package

// Take over the client components in the page that aren't running yet
export function hydrate() {
    const found = Array.from(document.querySelectorAll('[data-domino-client]'))
        .filter((el) => el.id && !el.dominoIsland && !el.dominoMounting);
    for (const el of found) el.dominoMounting = true;
    if (!found.length) return Promise.resolve();

    if (!runtime) runtime = boot();
    return runtime
        .then((domino) => Promise.all(found.map((el) => mount(domino, el))))
        .catch((err) => {
            // Tried again with the next update that shows one
            runtime = null;
            for (const el of found) el.dominoMounting = false;
            console.error('Domino: client components failed to start', err);
        });
}

async function boot() {
    const started = performance.now();
    let python;
    if (CONFIG.python === 'pyodide') {
        const { loadPyodide } = await import(CONFIG.url + 'pyodide.mjs');
        python = await loadPyodide({ indexURL: CONFIG.url });
    } else {
        const { loadMicroPython } = await import(CONFIG.url + 'micropython.mjs');
        python = await loadMicroPython({
            url: CONFIG.url + 'micropython.wasm',
            heapsize: CONFIG.heapsize,
            stdout: (line) => console.log(line),
            stderr: (line) => console.error(line),
        });
    }

    // Domino's package for client components: State, the tags, and the functions called below
    python.FS.mkdirTree('/domino_client/domino');
    for (const [path, source] of Object.entries(CONFIG.shim)) {
        python.FS.writeFile('/domino_client/' + path, source);
    }
    python.runPython("import sys\nsys.path.insert(0, '/domino_client')");
    const domino = python.pyimport('domino');

    window.Domino.client = { python: CONFIG.python, startup: performance.now() - started, islands };
    document.dispatchEvent(new CustomEvent('domino:client-ready', { detail: window.Domino.client }));
    return domino;
}

// "components.life@<hash>": the module's source, loaded once per page
function loadModule(domino, key) {
    if (!modules.has(key)) {
        const [name, hash] = key.split('@');
        modules.set(key, fetch(CONFIG.modules + name + '.py?v=' + encodeURIComponent(hash))
            .then((response) => {
                if (!response.ok) throw new Error(`${response.status} loading ${name}`);
                return response.text();
            })
            .then((source) => { domino.load_module(key, source); }));
    }
    return modules.get(key);
}

async function mount(domino, el) {
    const [key, name] = el.getAttribute('data-domino-client').split(':');
    try {
        await loadModule(domino, key);
    } catch (err) {
        el.dominoMounting = false;
        report(el, { error: String(err) });
        return;
    }
    if (!el.isConnected) return;

    const island = { id: el.id, el, types: new Set(), timers: new Map() };
    islands.set(el.id, island);
    el.dominoIsland = true;
    el.dominoMounting = false;
    update(island, domino, domino.mount(el.id, key, name, el.getAttribute('data-domino-state') || '{}'));
}

// Apply what the runtime answered (JSON): the new HTML, events to listen to, timers, events for
// the server, or an error. `started`: when the handler started (performance.now())
function update(island, domino, answer, started = performance.now()) {
    const result = JSON.parse(answer);
    if (result.error) {
        report(island.el, result);
        return;
    }

    if (result.html) {
        const template = document.createElement('template');
        template.innerHTML = domino.html(island.id);
        const replacement = template.content.firstElementChild;
        if (replacement) window.Domino.morph(island.el, replacement, null);
    }

    for (const type of result.events) {
        if (island.types.has(type)) continue;
        island.types.add(type);
        // Capturing, so events that don't bubble (focus, mouseenter) are seen too
        island.el.addEventListener(type, (e) => onEvent(island, domino, e), true);
    }

    // One pending timer per after() in render(): rendering again doesn't start a second one. The
    // delay counts from when the handler started, so after(33, self.tick) ticks 30 times a second
    // as long as a tick takes less than 33 ms
    for (const [index, delay] of result.after) {
        if (island.timers.has(index)) continue;
        island.timers.set(index, setTimeout(() => {
            island.timers.delete(index);
            run(island, domino, 'after', index, null);
        }, Math.max(0, delay - (performance.now() - started))));
    }

    for (const [name, value] of result.emit) emit(island, name, value);
}

function run(island, domino, kind, index, data) {
    // Gone from the page (the server re-rendered what was around it, say)
    if (!island.el.isConnected) {
        islands.delete(island.id);
        for (const timer of island.timers.values()) clearTimeout(timer);
        domino.unmount(island.id);
        return;
    }
    const started = performance.now();
    update(island, domino, domino.dispatch(island.id, kind, index, data === null ? '' : JSON.stringify(data)), started);
}

function onEvent(island, domino, e) {
    for (let el = e.target; el && el.nodeType === Node.ELEMENT_NODE; el = el.parentElement) {
        const bound = el.getAttribute('data-domino-on');
        if (bound) {
            for (const item of bound.split(' ')) {
                const [type, index] = item.split(':');
                if (type !== e.type) continue;
                if (type === 'submit') e.preventDefault();
                run(island, domino, 'event', parseInt(index, 10), eventData(el, e));
            }
        }
        if (el === island.el || !e.bubbles) return;
    }
}

const FIELDS = ['INPUT', 'SELECT', 'TEXTAREA'];

// What the handler's Event gets: like core.js sends the server, plus the element's data-*
// attributes, the pointer's position in the element and the key
function eventData(el, e) {
    const data = { type: e.type, data: {} };
    if (el.type === 'checkbox' || el.type === 'radio') {
        data.value = el.checked;
    } else if (FIELDS.includes(el.tagName)) {
        data.value = el.value;
    }
    const form = el.tagName === 'FORM' ? el : el.closest('form');
    if (form) {
        data.form = {};
        new FormData(form).forEach((value, name) => {
            if (typeof value !== 'string') return;
            data.form[name] = name in data.form ? [].concat(data.form[name], value) : value;
        });
    }
    for (const [name, value] of Object.entries(el.dataset)) {
        if (name !== 'dominoOn') data.data[name.replace(/[A-Z]/g, (c) => '_' + c.toLowerCase())] = value;
    }
    if (typeof e.clientX === 'number') {
        const box = el.getBoundingClientRect();
        data.x = e.clientX - box.left;
        data.y = e.clientY - box.top;
    }
    if (typeof e.key === 'string') data.key = e.key;
    return data;
}

// self.emit(name, value): the event the server component bound with on_<name>=..., sent like
// any other Domino event, with the value as event.value
function emit(island, name, value) {
    const ids = (island.el.getAttribute('data-event-id') || '').split(' ').filter((id) => id.endsWith('-' + name));
    if (!ids.length) {
        console.warn(`Domino: ${island.el.getAttribute('data-domino-client')} emitted "${name}", but the server gave it no on_${name}=`);
        return;
    }
    for (const id of ids) window.Domino.triggerEvent(id, { value }, null, island.el);
}

// Like a failed server event: a cancelable domino:error on the element, else the console
function report(el, result) {
    const detail = { error: result.error, traceback: result.traceback || null, eventId: null };
    const target = el && el.isConnected ? el : document;
    const event = new CustomEvent('domino:error', { bubbles: true, cancelable: true, detail });
    if (target.dispatchEvent(event)) console.error('Domino client component error:', result.traceback || result.error);
}
