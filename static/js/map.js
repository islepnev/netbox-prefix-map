(() => {
    "use strict";
    const cfg = JSON.parse(document.getElementById("page-config").textContent);
    const NB = cfg.netboxUrl;
    const $ = (id) => document.getElementById(id);
    const el = (tag, attrs, ...kids) => {
        const e = document.createElement(tag);
        if (attrs) for (const [k, v] of Object.entries(attrs)) {
            if (v === undefined || v === null || v === false) continue;
            if (k === "class") e.className = v;
            else if (k === "text") e.textContent = v;
            else if (k === "style") e.style.cssText = v;
            else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
            else e.setAttribute(k, v);
        }
        for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) e.append(kid);
        return e;
    };

    const ipToInt = (ip) => ip.split(".").reduce((a, o) => a * 256 + Number(o), 0);
    const intToIp = (n) => [24, 16, 8, 0].map((s) => Math.floor(n / 2 ** s) % 256).join(".");
    const parsePrefix = (prefix) => {
        const [a, l] = prefix.split("/");
        const len = Number(l), start = ipToInt(a), size = 2 ** (32 - len);
        return { start, end: start + size - 1, len, size };
    };
    const { t, fmt } = window.I18N;
    const pct = (u, total) => { const v = Math.min(100, (100 * u) / total); return v === 0 ? "0%" : v < 1 ? "<1%" : `${Math.round(v)}%`; };
    const vrfKey = (vrf) => (vrf === null || vrf === undefined ? "None" : String(vrf));
    const sanitize = (p) => p.replace(/[./]/g, "_");
    const mapUrl = (vrf, prefix) => `${cfg.basePath}/map/${vrfKey(vrf)}/${sanitize(prefix)}`;
    const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
    const tenantName = (id) => (id ? cfg.names.tenants[String(id)] || t("insp.tenant_n", { id }) : null);
    const nbLink = (path, text) => el("a", { class: "ext", href: `${NB}${path}`, target: "_blank", rel: "noopener", text });
    const top = window.PrefixMapTop;

    // ---------- clipboard: navigator.clipboard needs https or localhost; plain-http LAN hosts use the fallback ----------
    let toastTimer;
    function toast(text) {
        let box = $("toast");
        if (!box) { box = el("div", { id: "toast", role: "status" }); document.body.append(box); }
        box.textContent = text;
        box.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { box.hidden = true; }, 1600);
    }
    function legacyCopy(text) {
        const ta = el("textarea", { style: "position:fixed;top:0;left:0;opacity:0", readonly: "" });
        ta.value = text;
        document.body.append(ta);
        ta.select();
        const ok = document.execCommand("copy");
        ta.remove();
        if (!ok) throw new Error("copy refused");
    }
    function copyText(text) {
        const done = () => toast(t("copy.done", { text }));
        const fail = () => toast(t("copy.failed", { text }));
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(done, () => { try { legacyCopy(text); done(); } catch { fail(); } });
        } else {
            try { legacyCopy(text); done(); } catch { fail(); }
        }
    }
    const COPY_ICON = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M8.5 2V1.5H1.5v7H2" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';
    function copyBtn(text) {
        const b = el("button", { type: "button", class: "copy", title: t("copy.title", { text }), "aria-label": t("copy.title", { text }),
            onclick: (ev) => { ev.stopPropagation(); copyText(text); } });
        b.innerHTML = COPY_ICON;
        return b;
    }

    // ---------- panels ----------
    const PANEL_CLASS = { tree: "no-tree", insp: "no-insp" };
    const store = {
        get(k) { try { return localStorage.getItem(k); } catch { return null; } },
        set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
    };
    function setPanel(name, open) {
        document.body.classList.toggle(PANEL_CLASS[name], !open);
        store.set(`prefix-map.panel.${name}`, open ? "1" : "0");
        document.querySelectorAll(`#zoom [data-toggle-panel="${name}"]`).forEach((b) => b.setAttribute("aria-pressed", String(open)));
    }
    const panelOpen = (name) => !document.body.classList.contains(PANEL_CLASS[name]);
    for (const name of Object.keys(PANEL_CLASS)) setPanel(name, store.get(`prefix-map.panel.${name}`) !== "0");
    document.querySelectorAll("[data-toggle-panel]").forEach((b) =>
        b.addEventListener("click", () => setPanel(b.dataset.togglePanel, !panelOpen(b.dataset.togglePanel))));

    // ---------- data ----------
    const net = parsePrefix(cfg.prefix);
    const img = $("map-img");
    let data = null;
    // Data files of prefixes without an image carry no IP list, only ip_count
    let hasIps = false;
    let used = 0;
    let GW = 0, GH = 0, cs = 0;
    // Layered maps (prefixes shorter than /16): one cell per aligned /blockLen block, with IP counts per block
    let layer = null;
    let blockLen = 32, blockSize = 1;
    let blockStarts = new Float64Array(0);
    let blockCum = [0];
    const blockCounts = new Map();
    let countsKnown = false;
    const blockStart = (a) => a - ((a - net.start) % blockSize);
    let ipsByAddr = new Map();
    // Addresses with more than one IP record (several VRFs under a Global container, or NetBox duplicates)
    let dupes = new Map();
    let ipSorted = new Float64Array(0);
    let nested = [];
    let children = [];
    // NetBox IP ranges overlapping this prefix (DHCP scopes and the like)
    let ranges = [];
    const rangesAt = (a, size = 1) => ranges.filter((r) => r.start <= a + size - 1 && r.end >= a);
    const tenantColors = new Map();

    const lowerBound = (v) => {
        let lo = 0, hi = ipSorted.length;
        while (lo < hi) { const m = (lo + hi) >> 1; if (ipSorted[m] < v) lo = m + 1; else hi = m; }
        return lo;
    };
    const lowerBoundIn = (arr, v) => {
        let lo = 0, hi = arr.length;
        while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < v) lo = m + 1; else hi = m; }
        return lo;
    };
    const countIps = (s, e) => {
        if (!layer) return lowerBound(e + 1) - lowerBound(s);
        return blockCum[lowerBoundIn(blockStarts, e + 1)] - blockCum[lowerBoundIn(blockStarts, s - blockSize + 1)];
    };
    // Nested prefixes covering the whole cell at addr, outermost first
    const containing = (addr) => nested.filter((n) => addr >= n.start && addr + blockSize - 1 <= n.end);
    const inside = (addr) => nested.filter((n) => n.start >= addr && n.end <= addr + blockSize - 1 && n.size < blockSize);
    const childAt = (addr) => {
        let best = null;
        for (const c of children) if (addr >= c.start && addr + blockSize - 1 <= c.end && (!best || c.len > best.len)) best = c;
        return best;
    };
    // Prefixes that take space from a range: the outermost non-container ones inside it. Child containers are
    // transparent, so the free space inside them counts as free.
    const childrenOf = (range) => {
        const inside = nested.filter((n) => n.start >= range.start && n.end <= range.end && n.len > range.len
            && n.p.status !== "container");
        return inside.filter((n) => !inside.some((m) => m.len < n.len && n.start >= m.start && n.end <= m.end));
    };

    // Network and broadcast addresses of a subnet are not usable, as in NetBox: not for containers, pools,
    // /31 and /32. On layered maps a cell is a whole block, so the rule does not apply.
    const hasEdges = (range, status, isPool) => !layer && range.len <= 30 && status !== "container" && !isPool;
    const rangeHasEdges = (range) => (range.p ? hasEdges(range, range.p.status, range.p.is_pool)
        : hasEdges(range, data.status ?? cfg.details.status, data.is_pool ?? cfg.details.is_pool));
    // "network" / "broadcast" when the address is an edge of the innermost prefix around it
    function edgeKind(a) {
        const range = containing(a).at(-1) || net;
        if (!rangeHasEdges(range)) return null;
        return a === range.start ? "network" : a === range.end ? "broadcast" : null;
    }

    // Largest aligned blocks with no IP record and no child prefix
    const freeCache = new Map();
    function freeBlocks(range) {
        const key = `${range.start}/${range.len}`;
        if (freeCache.has(key)) return freeCache.get(key);
        const blocks = [];
        const edges = rangeHasEdges(range) ? [range.start, range.end] : [];
        (function walk(start, len, kids) {
            const size = 2 ** (32 - len), end = start + size - 1;
            const overlap = kids.filter((k) => k.start <= end && k.end >= start);
            if (overlap.some((k) => k.start <= start && k.end >= end)) return;
            const edge = edges.some((e) => e >= start && e <= end);
            if (!overlap.length && !edge && countIps(start, end) === 0) { blocks.push({ start, len, size }); return; }
            if (len >= blockLen) return;
            walk(start, len + 1, overlap);
            walk(start + size / 2, len + 1, overlap);
        })(range.start, range.len, [...childrenOf(range), ...ranges.filter((r) => r.start <= range.end && r.end >= range.start)]);
        blocks.sort((a, b) => b.size - a.size || a.start - b.start);
        const res = { blocks, total: blocks.reduce((s, b) => s + b.size, 0) };
        freeCache.set(key, res);
        return res;
    }

    // First free aligned blocks of one size, lowest address first (as NetBox "first available")
    function freeOfSize(range, len, limit) {
        const blocks = [];
        let count = 0;
        for (const b of [...freeBlocks(range).blocks].sort((x, y) => x.start - y.start)) {
            if (b.len > len) continue;
            const size = 2 ** (32 - len), n = b.size / size;
            for (let i = 0; i < n && blocks.length < limit; i++) blocks.push({ start: b.start + i * size, len, size });
            count += n;
        }
        return { blocks, count };
    }
    let freeSize = Number(store.get("prefix-map.free-size")) || null;

    function indexData(loaded) {
        data = loaded;
        const ips = data.ip_addresses || [];
        hasIps = data.rendered ?? net.len >= 16;
        used = data.ip_count ?? (hasIps ? ips.length : null);
        ipsByAddr = new Map(ips.map((ip) => [ipToInt(ip.address.split("/")[0]), ip]));
        dupes = new Map();
        for (const ip of ips) {
            const a = ipToInt(ip.address.split("/")[0]);
            if (!dupes.has(a)) dupes.set(a, []);
            dupes.get(a).push(ip);
        }
        for (const [a, list] of dupes) if (list.length < 2) dupes.delete(a);
        ipSorted = Float64Array.from(ipsByAddr.keys()).sort();
        const list = data.nested_prefixes || data.child_prefixes || [];
        nested = list.map((p) => ({ ...parsePrefix(p.prefix), p })).sort((a, b) => a.start - b.start || a.len - b.len);
        children = (data.child_prefixes || []).map((p) => ({ ...parsePrefix(p.prefix), p }));
        ranges = (data.ip_ranges || []).map((r) => ({ start: ipToInt(r.start), end: ipToInt(r.end), r }));
        for (const p of [data, ...(data.child_prefixes || []), ...(data.nested_prefixes || [])]) {
            if (p.tenant && p.color && !tenantColors.has(String(p.tenant))) tenantColors.set(String(p.tenant), p.color);
        }
        // A layered image with a data file from an older version: same block size as the renderer, counts unknown
        if (!data.layer && img && net.len < 16) data.layer = { block_len: Math.min(net.len + 16, 24), blocks: null };
        if (data.layer) {
            layer = data.layer;
            countsKnown = Array.isArray(layer.blocks);
            blockLen = layer.block_len;
            blockSize = 2 ** (32 - blockLen);
            const blocks = [...(layer.blocks || [])].sort((a, b) => a[0] - b[0]);
            blockStarts = Float64Array.from(blocks, ([i]) => net.start + i * blockSize);
            blockCum = [0];
            for (const [i, n] of blocks) { blockCounts.set(i, n); blockCum.push(blockCum.at(-1) + n); }
        }
        if (img) {
            // Data files from older versions lack grid and cell size; both follow from the prefix and the image
            const cellBits = blockLen - net.len;
            GW = 2 ** (cellBits - Math.floor(cellBits / 2));
            GH = 2 ** Math.floor(cellBits / 2);
            cs = img.naturalWidth / GW;
        }
    }

    // ---------- Morton layout; a 2:1 grid is two squares, the second half of the range on the right ----------
    function interleave(x, y) {
        let offset = 0;
        for (let bit = 0; bit < 16; bit++) offset += ((x >> bit) & 1) * 2 ** (2 * bit) + ((y >> bit) & 1) * 2 ** (2 * bit + 1);
        return offset;
    }
    function deinterleave(offset) {
        let x = 0, y = 0;
        for (let bit = 0; bit < 16; bit++) {
            x |= (Math.floor(offset / 2 ** (2 * bit)) & 1) << bit;
            y |= (Math.floor(offset / 2 ** (2 * bit + 1)) & 1) << bit;
        }
        return [x, y];
    }
    function cellToOffset(x, y) {
        if (GW === 2 * GH && x >= GH) return GH * GH + interleave(x - GH, y);
        return interleave(x, y);
    }
    function offsetToCell(offset) {
        if (GW === 2 * GH && offset >= GH * GH) { const [x, y] = deinterleave(offset - GH * GH); return [x + GH, y]; }
        return deinterleave(offset);
    }
    const cellOf = (a) => offsetToCell(Math.floor((a - net.start) / blockSize));
    function rangeBounds(start, end) {
        const [x1, y1] = cellOf(start), [x2, y2] = cellOf(end);
        return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
    }
    const cellBounds = (a) => { const [x, y] = cellOf(a); return [x, y, x, y]; };

    // ---------- state ----------
    // Zoom: device pixels per cell. The PNG has cs pixels per cell; scaled so that a cell takes a whole number of device
    // pixels, nearest-neighbour scaling repeats the same pixel pattern in every cell, so cells stay identical.
    let c = 0, fitMode = true, dpr = window.devicePixelRatio || 1;
    let hover = null, pinned = null, selected = null, freeHi = null;
    const viewport = $("viewport"), stage = $("stage");
    const ov = img && { hover: $("ov-hover"), pin: $("ov-pin"), prefix: $("ov-prefix"), select: $("ov-select"), free: $("ov-free") };

    // ---------- camera: continuous zoom and the map position, as in a map app ----------
    // c: device pixels per cell, any value. At whole multiples of the image cell size cs every cell gets the same pixel
    // pattern (nearest-neighbour); in between, cells differ by a device pixel; below 1x the image is scaled smoothly.
    // ox, oy: CSS pixels of the map's top-left corner in the viewport. The wheel and pinch zoom about the pointer,
    // dragging pans; + and - step through the crisp levels.
    const PAD = 16, MAX_SCALE = 16;
    let ox = 0, oy = 0;
    const maxC = () => cs * MAX_SCALE;
    function fitC() {
        const w = (viewport.clientWidth - 2 * PAD) * dpr, h = (viewport.clientHeight - 2 * PAD) * dpr;
        return Math.max(0.05, Math.min(maxC(), w / GW, h / GH));
    }
    const minC = () => Math.min(1, fitC()) / 2;
    // Crisp levels: 1, 2 below cs (halving), then cs, cs + 1, ... growing by about a quarter: 4, 5, 6, 7, 8, 10, 12, ...
    const stepOf = (v) => Math.max(1, 2 ** (Math.floor(Math.log2(v)) - 2));
    function crispLevels() {
        const levels = new Set();
        for (let v = cs; v > 1;) { v = Math.max(1, Math.floor(v / 2)); levels.add(v); }
        for (let v = cs; v <= maxC(); v += stepOf(v)) levels.add(v);
        return [...levels].sort((a, b) => a - b);
    }
    function zoomStep(v, dir) {
        const levels = crispLevels();
        if (dir > 0) return levels.find((l) => l > v + 1e-6) ?? maxC();
        return [...levels].reverse().find((l) => l < v - 1e-6) ?? minC();
    }
    const scaleText = (v) => `${fmt(Number((v / cs).toFixed(2)))}×`;
    const mapW = () => (GW * c) / dpr, mapH = () => (GH * c) / dpr;
    function centre() {
        ox = (viewport.clientWidth - mapW()) / 2;
        oy = (viewport.clientHeight - mapH()) / 2;
    }
    function layout() {
        if (!img || !img.naturalWidth) return;
        const vw = viewport.clientWidth, vh = viewport.clientHeight, w = mapW(), h = mapH();
        // The map may move until its edge reaches the middle of the view, so it can never be lost
        ox = Math.min(vw / 2, Math.max(vw / 2 - w, ox));
        oy = Math.min(vh / 2, Math.max(vh / 2 - h, oy));
        const snap = (v) => Math.round(v * dpr) / dpr;
        img.style.width = `${w}px`;
        img.style.height = `${h}px`;
        stage.style.left = `${snap(ox)}px`;
        stage.style.top = `${snap(oy)}px`;
        document.documentElement.style.setProperty("--hair", `${1 / dpr}px`);
        stage.classList.add("laid-out");
        $("zoom-level").textContent = scaleText(c);
        $("zoom-level").title = t(layer ? "zoom.scale_cell" : "zoom.scale_address", { px: fmt(Number(c.toFixed(2))) });
        img.classList.toggle("smooth", c < cs);
        $("zoom-out").disabled = c <= minC() + 1e-6;
        $("zoom-in").disabled = c >= maxC() - 1e-6;
        $("zoom-fit").classList.toggle("active", fitMode);
        drawOverlays();
    }
    // Zoom to v keeping the map point under anchor ([x, y] in viewport CSS pixels; default the view centre) in place
    function zoomAt(v, anchor) {
        const [ax, ay] = anchor || [viewport.clientWidth / 2, viewport.clientHeight / 2];
        const u0 = c / dpr, mx = (ax - ox) / u0, my = (ay - oy) / u0;
        c = Math.max(minC(), Math.min(maxC(), v));
        ox = ax - (mx * c) / dpr;
        oy = ay - (my * c) / dpr;
        fitMode = false;
        layout();
    }
    function setC(v, byUser, anchor) {
        if (byUser) { zoomAt(v, anchor); return; }
        c = v;
        fitMode = true;
        centre();
        layout();
    }
    function panBy(dx, dy) {
        ox += dx;
        oy += dy;
        layout();
    }
    const pointIn = (ev) => { const r = viewport.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };

    function enableGestures() {
        // A drag that starts on the image must not become the browser's image drag-and-drop (Firefox ignores
        // -webkit-user-drag; iOS starts system drag-and-drop): it would cancel the pointer and end the pan
        viewport.addEventListener("dragstart", (ev) => ev.preventDefault());
        // Wheel: zoom about the pointer. Touchpad pinch arrives as a wheel event with ctrlKey and small deltas.
        viewport.addEventListener("wheel", (ev) => {
            ev.preventDefault();
            const delta = ev.deltaY * (ev.deltaMode === 1 ? 40 : ev.deltaMode === 2 ? 800 : 1);
            zoomAt(c * Math.exp(-delta / (ev.ctrlKey ? 100 : 450)), pointIn(ev));
        }, { passive: false });
        // Safari pinch: gesture events with a scale since the gesture began
        let gesture = null;
        viewport.addEventListener("gesturestart", (ev) => { ev.preventDefault(); gesture = { c, at: pointIn(ev) }; });
        viewport.addEventListener("gesturechange", (ev) => { ev.preventDefault(); if (gesture) zoomAt(gesture.c * ev.scale, gesture.at); });
        viewport.addEventListener("gestureend", (ev) => { ev.preventDefault(); gesture = null; });
        // Pointers: one drags (mouse or finger), two pinch. A move of 4 px or more is a drag; its click does not pin.
        const pointers = new Map();
        let pinch = null, dragged = false;
        const mid = () => { const [a, b] = [...pointers.values()]; return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; };
        const dist = () => { const [a, b] = [...pointers.values()]; return Math.hypot(a[0] - b[0], a[1] - b[1]); };
        viewport.addEventListener("pointerdown", (ev) => {
            if (ev.pointerType === "mouse" && ev.button !== 0) return;
            pointers.set(ev.pointerId, pointIn(ev));
            if (pointers.size === 1) { dragged = false; pointers.get(ev.pointerId).start = pointIn(ev); }
            if (pointers.size === 2) pinch = { d: dist(), c, m: mid() };
        });
        viewport.addEventListener("pointermove", (ev) => {
            const p = pointers.get(ev.pointerId);
            if (!p) return;
            const now = pointIn(ev);
            if (pointers.size === 2 && pinch) {
                pointers.set(ev.pointerId, now);
                const m = mid();
                zoomAt(pinch.c * (dist() / pinch.d), m);
                panBy(m[0] - pinch.m[0], m[1] - pinch.m[1]);
                pinch.m = m;
                dragged = true;
                return;
            }
            if (!dragged && Math.hypot(now[0] - p.start[0], now[1] - p.start[1]) < 4) return;
            if (!dragged) { dragged = true; viewport.setPointerCapture(ev.pointerId); viewport.classList.add("dragging"); }
            const start = p.start;
            pointers.set(ev.pointerId, Object.assign(now, { start }));
            panBy(now[0] - p[0], now[1] - p[1]);
        });
        const end = (ev) => {
            pointers.delete(ev.pointerId);
            if (pointers.size < 2) pinch = null;
            if (pointers.size === 1) { const [p] = pointers.values(); p.start = [p[0], p[1]]; }
            if (!pointers.size) viewport.classList.remove("dragging");
        };
        viewport.addEventListener("pointerup", end);
        viewport.addEventListener("pointercancel", end);
        viewport.addEventListener("click", (ev) => { if (dragged) { dragged = false; ev.stopPropagation(); } }, true);
    }

    // ---------- overlays, aligned to cell edges ----------
    function place(box, b) {
        if (!b) { box.hidden = true; return; }
        const u = c / dpr;
        const [x1, y1, x2, y2] = b;
        box.style.left = `${x1 * u}px`;
        box.style.top = `${y1 * u}px`;
        box.style.width = `${(x2 - x1 + 1) * u}px`;
        box.style.height = `${(y2 - y1 + 1) * u}px`;
        box.hidden = false;
    }
    function drawOverlays() {
        if (!ov || !data) return;
        const focus = pinned ?? hover;
        place(ov.hover, hover !== null && hover !== pinned ? cellBounds(hover) : null);
        place(ov.pin, pinned !== null ? cellBounds(pinned) : null);
        const inner = focus !== null ? containing(focus).at(-1) : null;
        place(ov.prefix, inner ? rangeBounds(inner.start, inner.end) : null);
        place(ov.select, selected && !(inner && inner.start === selected.start && inner.len === selected.len)
            ? rangeBounds(selected.start, selected.end) : null);
        place(ov.free, freeHi ? rangeBounds(freeHi.start, freeHi.start + freeHi.size - 1) : null);
        drawChanges();
        drawTenant();
    }

    // ---------- changes of the last update that changed this prefix ----------
    const CHANGE_KINDS = [["added", "added"], ["removed", "removed"], ["changed", "changed"]];
    let showChanges = store.get("prefix-map.show-changes") === "1";
    // ---------- prefixes of one tenant, outlined from the legend ----------
    let tenantHi = null;
    const tenantPrefixes = (id) => {
        const own = nested.filter((n) => String(n.p.tenant) === String(id) && !(layer && n.len > blockLen));
        // Outermost only: a tenant's /24 inside its own /20 adds nothing to the outline
        return own.filter((n) => !own.some((o) => o !== n && o.start <= n.start && o.end >= n.end && o.len < n.len));
    };
    function drawTenant() {
        const box = $("ov-tenant");
        if (!box) return;
        if (tenantHi === null || !img) { box.hidden = true; return; }
        const u = c / dpr;
        box.replaceChildren(...tenantPrefixes(tenantHi).map((n) => {
            const [x1, y1, x2, y2] = rangeBounds(n.start, n.end);
            return el("div", { class: "ov-tenant", title: n.p.prefix,
                style: `left:${x1 * u}px;top:${y1 * u}px;width:${(x2 - x1 + 1) * u}px;height:${(y2 - y1 + 1) * u}px` });
        }));
        box.hidden = false;
    }
    function toggleTenant(id) {
        tenantHi = id === null || String(tenantHi) === String(id) ? null : String(id);
        drawTenant();
        document.querySelectorAll("#legend .tenant-toggle").forEach((e) => e.setAttribute("aria-pressed", String(e.dataset.tenant === tenantHi)));
        renderSummary();
        syncUrl();
    }
    // Inspector summary: the outlined tenant's prefixes with usage; a row outlines one prefix
    function tenantSection() {
        if (tenantHi === null) return null;
        const list = tenantPrefixes(tenantHi).sort((x, y) => x.start - y.start);
        const known = hasIps || countsKnown;
        const ips = list.reduce((s, n) => s + (known ? countIps(n.start, n.end) : 0), 0);
        const size = list.reduce((s, n) => s + n.size, 0);
        const shown = list.slice(0, 12);
        return sec(t("insp.tenant", { name: tenantName(tenantHi) }), known ? `${fmt(ips)} / ${fmt(size)} · ${pct(ips, size)}` : t("count.addresses", { n: size }),
            el("table", { class: "free tenant-list" }, el("tbody", null, shown.map((n) => {
                const u = known ? countIps(n.start, n.end) : null;
                return el("tr", { onclick: () => outline(n) },
                    el("td", { text: n.p.prefix }),
                    el("td", { class: "n", text: u === null ? "" : t("insp.used_pct", { used: fmt(u), pct: pct(u, n.size) }) }));
            }))),
            list.length > shown.length ? el("div", { class: "hint", text: t("common.more", { n: list.length - shown.length }) }) : null,
            el("button", { type: "button", class: "linkish", text: t("insp.clear_outline"), onclick: () => toggleTenant(null) }));
    }

    // Change shown in the summary and on the map: the last one, or an earlier one picked from the history
    let changeIndex = 0;
    const changeHistory = () => (data.changes_history && data.changes_history.length ? data.changes_history : data.changes ? [data.changes] : []);
    // The newest history record has shorter lists than data.changes, the same change in full
    const currentChange = () => (changeIndex === 0 && data.changes) || changeHistory()[changeIndex] || null;
    function changeSummary(ch) {
        const n = (key) => ch[`${key}_count`] ?? (ch[key] || []).length;
        return [
            n("added") ? t("changes.ip_added", { n: n("added") }) : null,
            n("removed") ? t("changes.ip_removed", { n: n("removed") }) : null,
            n("changed") ? t("changes.ip_changed", { n: n("changed") }) : null,
            n("prefixes_added") ? t("changes.prefixes_added", { n: n("prefixes_added") }) : null,
            n("prefixes_removed") ? t("changes.prefixes_removed", { n: n("prefixes_removed") }) : null,
        ].filter(Boolean).join(" · ");
    }

    function drawChanges() {
        const box = $("ov-changes");
        const ch = data && currentChange();
        if (!box || !ch || !showChanges || !img) { if (box) box.hidden = true; return; }
        const u = c / dpr;
        const cells = [];
        const add = (b, cls) => {
            const [x1, y1, x2, y2] = b;
            cells.push(el("div", { class: `ov-change ${cls}`,
                style: `left:${x1 * u}px;top:${y1 * u}px;width:${(x2 - x1 + 1) * u}px;height:${(y2 - y1 + 1) * u}px` }));
        };
        for (const [key, cls] of CHANGE_KINDS) {
            for (const a of ch[key] || []) {
                const n = ipToInt(a);
                if (n >= net.start && n <= net.end) add(cellBounds(blockStart(n)), cls);
            }
        }
        for (const [key, cls] of [["prefixes_added", "added prefix"], ["prefixes_removed", "removed prefix"]]) {
            for (const p of ch[key] || []) {
                const r = parsePrefix(p);
                if (r.start >= net.start && r.end <= net.end) add(rangeBounds(r.start, r.end), cls);
            }
        }
        box.replaceChildren(...cells);
        box.hidden = false;
    }
    function changesSection() {
        const ch = currentChange();
        if (!ch) return null;
        const history = changeHistory();
        const rows = [];
        for (const [key, cls] of CHANGE_KINDS) for (const a of ch[key] || []) rows.push([a, cls]);
        for (const p of ch.prefixes_added || []) rows.push([p, "added"]);
        for (const p of ch.prefixes_removed || []) rows.push([p, "removed"]);
        const toggle = el("input", { type: "checkbox", id: "show-changes" });
        toggle.checked = showChanges;
        toggle.addEventListener("change", () => {
            showChanges = toggle.checked;
            store.set("prefix-map.show-changes", showChanges ? "1" : "0");
            drawChanges();
        });
        const pick = (i) => { changeIndex = i; renderSummary(); drawChanges(); };
        const earlier = history.length > 1 ? el("div", { class: "history" },
            el("div", { class: "hint", text: t("changes.history") }),
            el("table", { class: "free changes history" }, el("tbody", null, history.map((h, i) => el("tr", {
                class: i === changeIndex ? "current" : null, onclick: () => pick(i),
                title: i === changeIndex ? null : t("changes.show_this"),
            }, el("td", { text: I18N.date(h.at * 1000) }), el("td", { class: "n", text: changeSummary(h) })))))) : null;
        return sec(changeIndex ? t("changes.earlier") : t("changes.last"), I18N.date(ch.at * 1000),
            el("div", { class: "sub" }, changeSummary(ch)),
            el("table", { class: "free changes" }, el("tbody", null, rows.slice(0, 8).map(([text, cls]) => {
                const isPrefix = text.includes("/");
                return el("tr", { onclick: img ? () => (isPrefix ? outline(parsePrefix(text)) : pin(blockStart(ipToInt(text)), true)) : null },
                    el("td", { text }), el("td", { class: `n ${cls}`, text: t(`changes.kind.${cls}`) }));
            }))),
            rows.length > 8 ? el("div", { class: "hint", text: t("common.more", { n: rows.length - 8 }) }) : null,
            img ? el("label", { class: "check" }, toggle, ` ${t("changes.show_on_map")}`) : null,
            earlier);
    }
    // Move the map so that the cells x1..x2, y1..y2 are in the middle of the view
    function scrollToBounds([x1, y1, x2, y2]) {
        const u = c / dpr;
        ox = viewport.clientWidth / 2 - ((x1 + x2 + 1) / 2) * u;
        oy = viewport.clientHeight / 2 - ((y1 + y2 + 1) / 2) * u;
        layout();
    }

    function hitTest(ev) {
        const r = img.getBoundingClientRect();
        const x = Math.floor(((ev.clientX - r.left) * img.naturalWidth) / r.width / cs);
        const y = Math.floor(((ev.clientY - r.top) * img.naturalHeight) / r.height / cs);
        if (x < 0 || y < 0 || x >= GW || y >= GH) return null;
        return net.start + cellToOffset(x, y) * blockSize;
    }

    let focusedPrefix;
    function emitFocus() {
        const f = pinned ?? hover;
        const inner = f !== null ? containing(f).at(-1) : null;
        const prefix = inner ? inner.p.prefix : null;
        if (prefix === focusedPrefix) return;
        focusedPrefix = prefix;
        document.dispatchEvent(new CustomEvent("prefixmap:focus", { detail: { prefix } }));
    }
    function update() { drawOverlays(); renderInspector(); emitFocus(); }
    function setHover(a) { if (a === hover) return; hover = a; drawOverlays(); if (pinned === null) renderInspector(); emitFocus(); }
    // The pinned address or outlined prefix goes to ?focus=, so the URL is a permalink to it
    function syncUrl() {
        const url = new URL(window.location.href);
        const focus = pinned !== null ? intToIp(pinned) : selected ? `${intToIp(selected.start)}/${selected.len}` : null;
        if (focus) url.searchParams.set("focus", focus);
        else url.searchParams.delete("focus");
        if (tenantHi !== null) url.searchParams.set("tenant", tenantHi);
        else url.searchParams.delete("tenant");
        if (url.href !== window.location.href) history.replaceState(history.state, "", url);
    }
    function pin(a, scroll) {
        pinned = a;
        update();
        syncUrl();
        if (scroll && a !== null) scrollToBounds(cellBounds(a));
    }

    // What double-click opens: the child prefix map, else the IP in NetBox
    function openAction(a) {
        const child = childAt(a) || (layer ? inside(a)[0] : null);
        if (child) return { label: t("action.open_map", { prefix: child.p.prefix }), url: mapUrl(child.p.vrf ?? data.vrf, child.p.prefix) };
        const ip = ipsByAddr.get(a);
        if (ip && ip.id) return { label: t("action.open_ip"), url: `${NB}/ipam/ip-addresses/${ip.id}/`, external: true };
        return null;
    }
    function navigate(url, external, newTab) {
        if (external || newTab) window.open(url, "_blank", "noopener");
        else window.location.href = url;
    }

    // ---------- inspector ----------
    const sec = (title, right, ...kids) =>
        el("section", { class: "sec" }, el("h3", null, title, right ? el("span", { class: "right" }, right) : null), ...kids);
    const kv = (pairs) => el("dl", { class: "kv" }, pairs.flatMap(([key, v]) => [
        el("dt", { text: key }),
        v === null || v === undefined || v === "" ? el("dd", { class: "none", text: "—" }) : el("dd", null, v),
    ]));
    // Mirrors IP_STATUS_STYLES in app/plot_map.py
    const IP_KINDS = {
        role: { color: "#ff0000", svg: ["#ff0000", 1], label: t("kind.role") },
        active: { color: "#000", svg: ["#000", 1], label: t("kind.active") },
        dhcp: { color: "rgba(0,0,0,.55)", svg: ["#000", 0.55], label: t("kind.dhcp") },
        reserved: { color: "rgba(0,0,0,.25)", svg: ["#000", 0.25], label: t("kind.reserved") },
        inactive: { color: "rgba(0,0,0,.1)", svg: ["#000", 0.1], label: t("kind.inactive") },
    };
    const STRIPED_STATUS = new Set(["reserved", "deprecated"]);  // prefix statuses drawn with stripes
    const STATUS_KIND = { dhcp: "dhcp", slaac: "dhcp", reserved: "reserved", deprecated: "reserved", inactive: "inactive" };
    const ipKind = (ip) => (ip.role ? "role" : STATUS_KIND[ip.status] || "active");
    const ipColor = (ip) => IP_KINDS[ipKind(ip)].color;
    const statusLabel = (s) => (s && I18N.has(`status.${s}`) ? t(`status.${s}`) : capital(s));
    const swatchStyle = (c) => `background:linear-gradient(${c},${c}),#fff`;
    const tenantNode = (id) => (id ? el("span", null,
        el("span", { class: "tswatch", style: `background:${tenantColors.get(String(id)) || "transparent"}` }),
        nbLink(`/tenancy/tenants/${id}/`, tenantName(id))) : null);

    function freeSizeSelect(range) {
        const maxLen = layer ? blockLen : 32;
        const select = el("select", { "aria-label": t("free.size_label"), title: t("free.size_title") },
            el("option", { value: "", text: t("free.largest") }),
            Array.from({ length: Math.max(0, maxLen - range.len) }, (_, i) => range.len + 1 + i)
                .map((len) => el("option", { value: String(len), text: `/${len}` })));
        select.value = freeSize && freeSize > range.len && freeSize <= maxLen ? String(freeSize) : "";
        select.addEventListener("change", () => {
            freeSize = Number(select.value) || null;
            store.set("prefix-map.free-size", freeSize ? String(freeSize) : "");
            if ((pinned ?? hover) !== null) renderInspector();
            renderSummary();
        });
        return select;
    }

    function freeSection(range, label) {
        const title = el("span", null, ...I18N.nodes("free.title", { prefix: el("span", { class: "mono", text: label }) }));
        if (range.len >= blockLen) {
            return sec(title, null,
                el("div", { class: "empty", text: t("free.smaller_than_cell", { prefix: label }) }));
        }
        const fb = freeBlocks(range);
        const bySize = freeSize && freeSize > range.len && freeSize <= (layer ? blockLen : 32);
        const list = bySize ? freeOfSize(range, freeSize, 8) : { blocks: fb.blocks.slice(0, 8), count: fb.blocks.length };
        const shown = list.blocks;
        const body = shown.length
            ? el("table", { class: "free" }, el("tbody", null, shown.map((b) => {
                const prefix = `${intToIp(b.start)}/${b.len}`;
                return el("tr", {
                    onmouseenter: () => { freeHi = b; drawOverlays(); },
                    onmouseleave: () => { freeHi = null; drawOverlays(); },
                    onclick: img ? () => scrollToBounds(rangeBounds(b.start, b.start + b.size - 1)) : null,
                }, el("td", { text: prefix }),
                    el("td", { class: "n", text: t("free.block_size", { n: b.size }) }),
                    el("td", { class: "c" }, copyBtn(prefix)));
            })))
            : el("div", { class: "empty", text: bySize ? t("free.none_of_size", { len: freeSize }) : t("free.none") });
        const rest = list.count - shown.length;
        const more = rest > 0 ? el("div", { class: "hint", text: bySize ? t("free.more_of_size", { n: rest, len: freeSize }) : t("free.more_smaller", { n: rest }) }) : null;
        const right = bySize ? `${fmt(list.count)} × /${freeSize}` : t("free.total", { n: fb.total });
        return sec(title, right, el("div", { class: "fsize" }, el("label", null, `${t("free.size")} `, freeSizeSelect(range))), body, more);
    }

    const vlanName = (id) => {
        const v = id ? (cfg.names.vlans || {})[String(id)] : null;
        return id ? (v ? `VLAN ${v.vid}` : `VLAN #${id}`) : null;
    };
    const vrfLabel = (vrf) => (vrf === null || vrf === undefined ? t("vrf.global") : cfg.vrf && String(cfg.vrf.id) === String(vrf) ? cfg.vrf.name : `VRF #${vrf}`);
    function dupeSection(list) {
        return sec(t("insp.all_records"), `${list.length}`, el("table", { class: "free dupes" }, el("tbody", null, list.map((ip) =>
            el("tr", null,
                el("td", { text: vrfLabel(ip.vrf) }),
                el("td", { text: [statusLabel(ip.status), ip.role, ip.dns_name].filter(Boolean).join(" · ") }),
                el("td", { class: "n" }, ip.id ? nbLink(`/ipam/ip-addresses/${ip.id}/`, "NetBox") : null))))),
            el("div", { class: "hint", text: t("insp.records_hint") }));
    }
    const roleName = (id) => (id ? cfg.names.roles[String(id)] || t("insp.role_n", { id }) : null);
    function rangeSection(list) {
        return sec(t("insp.ip_ranges", { n: list.length }), list.length > 1 ? `${list.length}` : null, ...list.slice(0, 4).map(({ r }) =>
            el("div", { class: "range-item" },
                el("div", { class: "mono" }, `${r.start} – ${r.end}`, copyBtn(`${r.start}-${r.end}`)),
                kv([
                    ["NetBox", r.id ? nbLink(`/ipam/ip-ranges/${r.id}/`, t("insp.ip_range")) : null],
                    [t("field.size"), t("count.addresses", { n: r.size })],
                    [t("field.status"), statusLabel(r.status)],
                    [t("field.role"), roleName(r.role)],
                    [t("field.description"), r.description || null],
                ]))));
    }

    function chainSection(chainNodes) {
        const chain = [
            ...cfg.parents.map((p) => ({ prefix: p.prefix, id: p.id, vrf: cfg.vrfKey, desc: p.description, tenant: p.tenant, pool: p.is_pool, vlan: p.vlan, status: p.status })),
            { prefix: cfg.prefix, id: cfg.prefixId, vrf: cfg.vrfKey, desc: cfg.details.description, tenant: cfg.details.tenant_id, here: true,
                pool: data.is_pool ?? cfg.details.is_pool, vlan: cfg.details.vlan_id, status: data.status ?? cfg.details.status },
            ...chainNodes.map((n) => ({ prefix: n.p.prefix, id: n.p.id, vrf: n.p.vrf ?? data.vrf, desc: n.p.description, tenant: n.p.tenant, pool: n.p.is_pool, vlan: n.p.vlan, status: n.p.status })),
        ];
        const innerPrefix = chain.at(-1).prefix;
        return sec(t("insp.chain"), null, el("ol", { class: "chain" }, chain.map((c) => {
            const desc = [STRIPED_STATUS.has(c.status) ? statusLabel(c.status).toLowerCase() : null, c.pool ? t("insp.pool_lc") : null, c.desc, tenantName(c.tenant), vlanName(c.vlan)].filter(Boolean).join(" · ");
            return el("li", { class: [c.here ? "here" : "", c.prefix === innerPrefix ? "inner" : ""].join(" ").trim() || null },
                el("span", { class: "p", text: c.prefix }),
                el("span", { class: "l" },
                    c.here ? el("span", { text: t("insp.this_map") }) : el("a", { href: mapUrl(c.vrf, c.prefix), text: t("insp.map") }),
                    c.id ? nbLink(`/ipam/prefixes/${c.id}/`, "NetBox") : null, copyBtn(c.prefix)),
                desc ? el("span", { class: "d", text: desc, title: desc }) : null);
        })));
    }

    // Inspector of a layered map cell: an aligned block with its IP count
    function renderBlock(a) {
        const count = countsKnown ? blockCounts.get((a - net.start) / blockSize) || 0 : null;
        const chainNodes = containing(a);
        const inner = chainNodes.at(-1);
        const smaller = inside(a);
        const action = openAction(a);
        const out = [el("section", { class: "sec" },
            el("div", { class: "big" }, intToIp(a), el("span", { class: "mask", text: `/${blockLen}` }), copyBtn(`${intToIp(a)}/${blockLen}`)),
            el("div", { class: "sub" },
                count === null ? el("span", { class: "pill", text: t("block.ips_unknown") })
                    : count ? el("span", { class: "pill", text: t("block.used", { n: count }) }) : el("span", { class: "pill free", text: t("block.no_ips") }),
                el("span", { class: "mono", text: count === null ? t("count.addresses", { n: blockSize }) : t("block.pct_of", { pct: pct(count, blockSize), total: fmt(blockSize) }) })),
            action ? el("div", { class: "hint", text: t("insp.dblclick", { action: action.label }) })
                : el("div", { class: "hint", text: t("block.no_prefix") }))];
        const blockRanges = rangesAt(a, blockSize);
        if (blockRanges.length) out.push(rangeSection(blockRanges));
        out.push(chainSection(chainNodes));
        if (smaller.length) {
            const shown = smaller.slice(0, 8);
            out.push(sec(t("block.prefixes_inside"), `${fmt(smaller.length)}`, el("ol", { class: "chain" }, shown.map((n) =>
                el("li", null, el("span", { class: "p", text: n.p.prefix }),
                    el("span", { class: "l" }, el("a", { href: mapUrl(n.p.vrf ?? data.vrf, n.p.prefix), text: t("insp.map") }),
                        n.p.id ? nbLink(`/ipam/prefixes/${n.p.id}/`, "NetBox") : null),
                    n.p.description ? el("span", { class: "d", text: n.p.description, title: n.p.description }) : null)))));
        }
        if (countsKnown) out.push(freeSection(inner || net, inner ? inner.p.prefix : cfg.prefix));
        $("insp-detail").replaceChildren(...out);
        $("insp-summary").hidden = true;
        $("insp-detail").hidden = false;
    }

    function setBadge(node) { $("insp-badge").replaceWith(node); node.id = "insp-badge"; }

    function renderInspector() {
        const a = pinned ?? hover;
        const detail = $("insp-detail"), summary = $("insp-summary");
        // Re-rendering removes the hovered free-block row without a mouseleave
        if (freeHi) { freeHi = null; drawOverlays(); }
        if (a === null || !data) {
            detail.hidden = true;
            summary.hidden = false;
            if (img) setBadge(el("span", { class: "badge", text: t("insp.hover_hint") }));
            return;
        }
        setBadge(pinned !== null
            ? el("span", { class: "pin-badge" }, t("insp.pinned"), el("button", {
                type: "button", title: `${t("insp.unpin")} (Esc)`, "aria-label": t("insp.unpin"), text: "×", onclick: () => pin(null),
            }))
            : el("span", { class: "badge", text: t("insp.click_hint") }));
        if (layer) { renderBlock(a); return; }
        const ip = ipsByAddr.get(a);
        const edge = ip ? null : edgeKind(a);
        const inRange = rangesAt(a);
        const chainNodes = containing(a);
        const inner = chainNodes.at(-1);
        const pool = (inner ? inner.p.is_pool : data.is_pool ?? cfg.details.is_pool) ? (inner ? inner.p.prefix : cfg.prefix) : null;
        const mask = ip ? ip.address.split("/")[1] : inner ? inner.len : net.len;
        const action = openAction(a);
        const out = [];
        out.push(el("section", { class: "sec" },
            el("div", { class: "big" }, intToIp(a), el("span", { class: "mask", text: `/${mask}` }), copyBtn(intToIp(a))),
            el("div", { class: "sub" },
                ip ? el("span", { class: "pill" }, el("span", { class: "sw", style: swatchStyle(ipColor(ip)) }), statusLabel(ip.status) || "IP")
                    : edge ? el("span", { class: "pill", text: t(`edge.${edge}`) })
                        : inRange.length ? el("span", { class: "pill" }, el("span", { class: "sw range" }), t("insp.ip_range"))
                            : el("span", { class: "pill free", text: t("insp.free") }),
                dupes.has(a) ? el("span", { class: "pill warn", text: t("insp.records", { n: dupes.get(a).length }) }) : null,
                pool ? el("span", { class: "pill", text: t("insp.pool"), title: t("insp.pool_title", { prefix: pool }) }) : null,
                el("span", { class: "mono", text: t("insp.offset", { n: a - net.start }) })),
            action ? el("div", { class: "hint", text: t("insp.dblclick", { action: action.label }) }) : null));
        if (ip) {
            out.push(sec(t("insp.ip_address"), ip.id ? nbLink(`/ipam/ip-addresses/${ip.id}/`, "NetBox") : null, kv([
                [t("field.status"), statusLabel(ip.status)],
                [t("field.role"), capital(ip.role)],
                [t("field.dns_name"), ip.dns_name ? el("span", { class: "mono", text: ip.dns_name }) : null],
                [t("field.description"), ip.description || null],
                [t("field.tenant"), tenantNode(ip.tenant)],
            ])));
        } else if (edge) {
            out.push(sec(t("insp.ip_address"), null, el("div", { class: "empty",
                text: t(`edge.${edge}_of`, { prefix: inner ? inner.p.prefix : cfg.prefix }) })));
        } else {
            const vrfParam = cfg.vrf ? `&vrf=${encodeURIComponent(cfg.vrf.id)}` : "";
            out.push(sec(t("insp.ip_address"), null, el("div", { class: "empty" }, `${t("insp.no_record")} `,
                nbLink(`/ipam/ip-addresses/add/?address=${intToIp(a)}/${mask}${vrfParam}`, t("insp.add_in_netbox")))));
        }
        if (dupes.has(a)) out.push(dupeSection(dupes.get(a)));
        if (inRange.length) out.push(rangeSection(inRange));
        out.push(chainSection(chainNodes));
        const innerPrefix = inner ? inner.p.prefix : cfg.prefix;
        out.push(freeSection(inner || net, innerPrefix));
        detail.replaceChildren(...out);
        summary.hidden = true;
        detail.hidden = false;
    }

    function renderSummary() {
        const total = net.size;
        const counts = { active: hasIps ? 0 : used || 0, role: 0, dhcp: 0, reserved: 0, inactive: 0 };
        for (const ip of hasIps ? data.ip_addresses || [] : []) counts[ipKind(ip)]++;
        const seg = (n, color, label) => (n ? el("i", { style: `width:${(100 * n) / total}%;background:${color}`, title: `${label}: ${fmt(n)}` }) : null);
        const barColor = { active: "var(--text)", role: "#ff0000", dhcp: "var(--muted)", reserved: "var(--faint)", inactive: "var(--line)" };
        $("sum-usage").replaceChildren(
            el("div", { class: "bigbar" }, Object.keys(counts).map((kind) => seg(counts[kind], barColor[kind], IP_KINDS[kind].label))),
            el("div", { class: "stats" },
                el("div", { class: "stat" }, el("b", { text: used === null ? "—" : fmt(used) }),
                    el("span", { text: used === null ? t("summary.ips") : `${t("summary.ips")} · ${pct(used, total)}` })),
                el("div", { class: "stat" }, el("b", { text: fmt((data.child_prefixes || []).length) }),
                    el("span", { text: t("summary.child_prefixes", { n: (data.child_prefixes || []).length }) })),
                el("div", { class: "stat" }, el("b", { text: fmt(total) }), el("span", { text: t("summary.addresses", { n: total }) }))));
        const sections = [tenantSection()];
        if (hasIps || countsKnown) sections.push(freeSection(net, cfg.prefix));
        sections.push(changesSection());
        if (dupes.size) {
            const shown = [...dupes.keys()].sort((x, y) => x - y).slice(0, 8);
            sections.push(sec(t("insp.several_records"), `${fmt(dupes.size)}`, el("table", { class: "free" }, el("tbody", null,
                shown.map((a) => el("tr", { onclick: () => pin(a, true) },
                    el("td", { text: intToIp(a) }),
                    el("td", { class: "n", text: dupes.get(a).map((ip) => vrfLabel(ip.vrf)).join(", ") }))))),
                dupes.size > shown.length ? el("div", { class: "hint", text: t("common.more", { n: dupes.size - shown.length }) }) : null));
        }
        $("sum-free").replaceChildren(...sections.filter(Boolean));
        const big = document.querySelector("#insp-summary .big");
        if (big && !big.querySelector(".copy")) big.append(copyBtn(cfg.prefix));
    }

    const usageText = () => (used === null ? t("count.addresses", { n: net.size })
        : t("usage.used_of", { used: fmt(used), total: fmt(net.size), pct: I18N.fixed((100 * used) / net.size, used && used < net.size / 1000 ? 2 : 1) }));

    function renderLegend() {
        const sw = (c) => el("span", { class: "sw", style: swatchStyle(c) });
        const tenants = new Map();
        for (const p of data.nested_prefixes || data.child_prefixes || []) {
            if (p.tenant && p.color && !tenants.has(p.tenant)) tenants.set(p.tenant, p.color);
        }
        const keys = layer
            ? el("span", { class: "lg-group" },
                el("span", { class: "lg-label", text: t("legend.ips_per_block") }),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.25)"), t("legend.few")),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.575)"), "25%"),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.9)"), t("legend.all")),
                el("span", { class: "lg" }, el("span", { class: "sw checker" }), t("legend.prefixes_inside")))
            : el("span", { class: "lg-group" }, ["active", "dhcp", "reserved", "inactive", "role"]
                .filter((kind) => !hasIps || kind === "active" || kind === "role" || (data.ip_addresses || []).some((ip) => ipKind(ip) === kind))
                .map((kind) => el("span", { class: "lg" }, sw(IP_KINDS[kind].color), IP_KINDS[kind].label)),
                ranges.length ? el("span", { class: "lg" }, el("span", { class: "sw range" }), t("insp.ip_range")) : null);
        const striped = nested.some((n) => STRIPED_STATUS.has(n.p.status) && !(layer && n.len > blockLen))
            ? el("span", { class: "lg" }, el("span", { class: "sw striped" }), t("legend.striped")) : null;
        if (striped) keys.append(striped);
        // replaceChildren() would print null as text
        $("legend").replaceChildren(...[
            keys,
            tenants.size ? el("span", { class: "vsep" }) : null,
            tenants.size ? el("span", { class: "lg-group tenants" }, el("span", { class: "lg-label", text: t("legend.tenants") }),
                [...tenants].sort((a, b) => tenantName(a[0]).localeCompare(tenantName(b[0])))
                    .map(([id, c]) => el("span", { class: "lg tenant-toggle", role: "button", tabindex: "0",
                        "data-tenant": String(id), "aria-pressed": String(String(tenantHi) === String(id)),
                        title: t("legend.tenant_title"),
                        onclick: () => toggleTenant(id), onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleTenant(id); } } },
                    sw(c), tenantName(id)))) : null,
            el("span", { class: "right", id: "usage-total" },
                usageText(),
                img ? el("span", { class: "cellnote", text: ` · ${layer ? t("legend.cell_block", { len: blockLen }) : t("legend.cell_address")}` }) : null),
        ].filter(Boolean));
    }

    // ---------- search within this map ----------
    const IPV4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
    // Queries inside this map are answered here, others go to the server search
    function parseQuery(q) {
        const [addrPart, lenPart] = q.split("/");
        const len = lenPart === undefined ? null : Number(lenPart);
        if (!IPV4.test(addrPart) || (len !== null && !(len >= 0 && len <= 32))) return null;
        const addr = ipToInt(addrPart);
        if (addr < net.start || addr > net.end || (len !== null && len < net.len)) return null;
        return { addr, len };
    }

    function localSearch(q, commit, ui) {
        const parsed = img && parseQuery(q);
        if (!parsed) return false;
        const { addr, len } = parsed;
        if (len === null && layer) {
            const a = blockStart(addr);
            pin(a, true);
            const count = countsKnown ? ` · ${t("search.block_ips", { n: blockCounts.get((a - net.start) / blockSize) || 0 })}` : "";
            ui.say(`${t("search.in_block", { ip: intToIp(addr), block: `${intToIp(a)}/${blockLen}` })}${count}`);
            return true;
        }
        if (len === null) {
            const ip = ipsByAddr.get(addr);
            pin(addr, true);
            const edge = ip ? null : edgeKind(addr);
            ui.say(`${intToIp(addr)} · ${ip ? statusLabel(ip.status) + (ip.dns_name ? ` · ${ip.dns_name}` : "") : edge ? t(`edge.${edge}`).toLowerCase() : t("search.free")}`);
            return true;
        }
        const start = addr - (addr % 2 ** (32 - len));
        const prefix = `${intToIp(start)}/${len}`;
        if (prefix === cfg.prefix) { ui.say(t("search.this_map")); return true; }
        const node = nested.find((n) => n.p.prefix === prefix);
        outline(parsePrefix(prefix));
        if (node) {
            ui.say(t("search.prefix_found", { prefix: `${prefix}${node.p.description ? ` · ${node.p.description}` : ""}` }));
            if (commit) navigate(mapUrl(node.p.vrf ?? data.vrf, prefix));
        } else {
            ui.say(t("search.not_a_prefix", { prefix }));
        }
        return true;
    }

    function outline(range) {
        selected = range;
        drawOverlays();
        syncUrl();
        scrollToBounds(rangeBounds(range.start, range.end));
    }

    // ?focus=<address or prefix> from search results
    function applyFocus() {
        const focus = new URLSearchParams(window.location.search).get("focus");
        const parsed = focus && parseQuery(focus);
        if (!parsed) return;
        if (parsed.len === null) pin(blockStart(parsed.addr), true);
        else if (parsed.len > net.len) outline(parsePrefix(`${intToIp(parsed.addr - (parsed.addr % 2 ** (32 - parsed.len)))}/${parsed.len}`));
    }

    // ---------- events ----------
    // A non-Latin layout (Russian) gives "с", "х", "ъ" for the c, [, ] keys: fall back to the physical key
    const CODE_KEY = { KeyC: "c", BracketLeft: "[", BracketRight: "]" };
    const keyOf = (ev) => (ev.key.length === 1 && ev.key > "~" && CODE_KEY[ev.code]) || ev.key;
    document.addEventListener("keydown", (ev) => {
        if (ev.target.closest?.("input, select, textarea") || ev.ctrlKey || ev.metaKey || ev.altKey) return;
        if (img && img.naturalWidth && data && moveKey(ev)) return;
        const key = keyOf(ev);
        if (key === "Escape") {
            if (pinned !== null) pin(null);
            else if (selected) { selected = null; drawOverlays(); syncUrl(); }
        } else if (key === "[") setPanel("tree", !panelOpen("tree"));
        else if (key === "]") setPanel("insp", !panelOpen("insp"));
        else if (!img || !img.naturalWidth) return;
        else if (key === "+" || key === "=") setC(zoomStep(c, 1), true);
        else if (key === "-") setC(zoomStep(c, -1), true);
        else if (key === "0") setC(fitC(), false);
    });
    // Arrows move the pinned cell (Shift: 16 cells), Enter opens it, c copies it
    const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    function ensureVisible([x1, y1, x2, y2]) {
        const u = c / dpr, m = 24, vw = viewport.clientWidth, vh = viewport.clientHeight;
        const l = ox + x1 * u, t = oy + y1 * u, r = ox + (x2 + 1) * u, b = oy + (y2 + 1) * u;
        const dx = l < m ? m - l : r > vw - m ? vw - m - r : 0, dy = t < m ? m - t : b > vh - m ? vh - m - b : 0;
        if (dx || dy) panBy(dx, dy);
    }
    function moveKey(ev) {
        if (ARROWS[ev.key]) {
            ev.preventDefault();
            const from = pinned ?? hover ?? net.start;
            const step = ev.shiftKey ? 16 : 1;
            let [x, y] = cellOf(from);
            x = Math.max(0, Math.min(GW - 1, x + ARROWS[ev.key][0] * step));
            y = Math.max(0, Math.min(GH - 1, y + ARROWS[ev.key][1] * step));
            pin(net.start + cellToOffset(x, y) * blockSize);
            ensureVisible(cellBounds(pinned));
            return true;
        }
        if (ev.key === "Enter" && pinned !== null && !ev.target.closest?.("a, button")) {
            const action = openAction(pinned);
            if (action) navigate(action.url, action.external, ev.shiftKey);
            return true;
        }
        if (keyOf(ev) === "c") {
            const a = pinned ?? hover;
            if (a !== null) copyText(layer ? `${intToIp(a)}/${blockLen}` : intToIp(a));
            else if (selected) copyText(`${intToIp(selected.start)}/${selected.len}`);
            else copyText(cfg.prefix);
            return true;
        }
        return false;
    }

    document.addEventListener("prefixtree:hover", (ev) => {
        const p = ev.detail.prefix ? parsePrefix(ev.detail.prefix) : null;
        selected = p && p.start >= net.start && p.end <= net.end && p.len > net.len ? p : null;
        drawOverlays();
    });

    function startMap() {
        c = fitC();
        centre();
        layout();
        $("zoom-in").addEventListener("click", () => setC(zoomStep(c, 1), true));
        $("zoom-out").addEventListener("click", () => setC(zoomStep(c, -1), true));
        $("zoom-fit").addEventListener("click", () => setC(fitC(), false));
        let size = [viewport.clientWidth, viewport.clientHeight];
        new ResizeObserver(() => {
            // Fit follows the view; otherwise the map point in the middle of the view stays there
            if (fitMode) { c = fitC(); centre(); } else { ox += (viewport.clientWidth - size[0]) / 2; oy += (viewport.clientHeight - size[1]) / 2; }
            size = [viewport.clientWidth, viewport.clientHeight];
            layout();
        }).observe(viewport);
        enableGestures();
        const watchDpr = () => matchMedia(`(resolution: ${dpr}dppx)`).addEventListener("change", () => {
            dpr = window.devicePixelRatio || 1;
            if (fitMode) { c = fitC(); centre(); }
            layout();
            watchDpr();
        }, { once: true });
        watchDpr();
        stage.addEventListener("mousemove", (ev) => setHover(hitTest(ev)));
        stage.addEventListener("mouseleave", () => setHover(null));
        stage.addEventListener("click", (ev) => {
            const a = hitTest(ev);
            if (a !== null) pin(pinned === a ? null : a);
        });
        stage.addEventListener("dblclick", (ev) => {
            const a = hitTest(ev);
            if (a === null) return;
            pin(a);
            const action = openAction(a);
            if (action) navigate(action.url, action.external, ev.ctrlKey || ev.metaKey);
        });
    }

    // ---------- export and print (static/js/map_export.js) ----------
    function initExport() {
        const exp = window.PrefixMapExport;
        if (!exp) return;
        exp.init({
            cfg, data, net, layer, blockLen, blockSize, blockCounts, GW, GH, nested, children, ranges, ipsByAddr,
            cellOf, rangeBounds, intToIp, ipToInt, ipKind, IP_KINDS, tenantName, usageText,
        });
        const bw = el("input", { type: "checkbox", id: "export-bw" });
        bw.checked = store.get("prefix-map.export-bw") === "1";
        bw.addEventListener("change", () => store.set("prefix-map.export-bw", bw.checked ? "1" : "0"));
        exp.setMono(bw.checked);
        bw.addEventListener("change", () => exp.setMono(bw.checked));
        const action = (text, fn) => el("button", { type: "button", class: "linkish", text, onclick: fn });
        $("sum-export").replaceChildren(sec(t("export.title"), null, el("div", { class: "links" },
            action(t("export.print"), () => exp.print(bw.checked)),
            action(t("export.download"), () => exp.download(bw.checked)),
            el("label", { class: "check" }, bw, ` ${t("export.bw")}`))));
    }

    const imageReady = !img || img.complete ? Promise.resolve() : new Promise((resolve, reject) => {
        img.addEventListener("load", resolve);
        img.addEventListener("error", () => reject(new Error("image failed to load")));
    });
    const dataReady = fetch(cfg.dataUrl).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    });
    Promise.all([dataReady, imageReady])
        .then(([loaded]) => {
            indexData(loaded);
            if (top) {
                top.setGeneratedAt(data.generated_at);
                top.setSearchHandler(localSearch);
            }
            renderLegend();
            renderSummary();
            if (img) {
                startMap();
                // ?tenant=<id>: outline that tenant, when it has prefixes on this map. Read before applying ?focus=,
                // which rewrites the URL; applied after it, so that both end up in the URL again.
                const tenant = new URLSearchParams(window.location.search).get("tenant");
                applyFocus();
                if (tenant && tenantPrefixes(tenant).length) toggleTenant(tenant);
                initExport();
            }
            document.body.dataset.ready = "1";
        })
        .catch((error) => {
            $("legend").textContent = t("map.data_unavailable", { error: error.message });
            document.body.dataset.ready = "error";
        });

    window.__prefixMap = { get k() { return c / cs; }, get c() { return c; }, get dpr() { return dpr; },
        get camera() { return [ox, oy]; }, centreCell: (x, y) => scrollToBounds([x, y, x, y]), cellToOffset, offsetToCell, freeBlocks: (p) => freeBlocks(parsePrefix(p)), cellOf };
})();
