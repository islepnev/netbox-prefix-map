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
    const fmt = (n) => n.toLocaleString("en-US");
    const pct = (u, t) => { const v = Math.min(100, (100 * u) / t); return v === 0 ? "0%" : v < 1 ? "<1%" : `${Math.round(v)}%`; };
    const vrfKey = (vrf) => (vrf === null || vrf === undefined ? "None" : String(vrf));
    const sanitize = (p) => p.replace(/[./]/g, "_");
    const mapUrl = (vrf, prefix) => `${cfg.basePath}/map/${vrfKey(vrf)}/${sanitize(prefix)}`;
    const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
    const tenantName = (id) => (id ? cfg.names.tenants[String(id)] || `Tenant ${id}` : null);
    const nbLink = (path, text) => el("a", { class: "ext", href: `${NB}${path}`, target: "_blank", rel: "noopener", text });
    const top = window.PrefixMapTop;

    // ---------- clipboard: navigator.clipboard needs https or localhost; plain-http LAN hosts use the fallback ----------
    let toastTimer;
    function toast(text) {
        let t = $("toast");
        if (!t) { t = el("div", { id: "toast", role: "status" }); document.body.append(t); }
        t.textContent = text;
        t.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { t.hidden = true; }, 1600);
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
        const done = () => toast(`Copied ${text}`);
        const fail = () => toast(`Copy failed: ${text}`);
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(done, () => { try { legacyCopy(text); done(); } catch { fail(); } });
        } else {
            try { legacyCopy(text); done(); } catch { fail(); }
        }
    }
    const COPY_ICON = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M8.5 2V1.5H1.5v7H2" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';
    function copyBtn(text) {
        const b = el("button", { type: "button", class: "copy", title: `Copy ${text}`, "aria-label": `Copy ${text}`,
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
    const viewport = $("viewport"), stage = $("stage"), wrap = $("stage-wrap");
    const ov = img && { hover: $("ov-hover"), pin: $("ov-pin"), prefix: $("ov-prefix"), select: $("ov-select"), free: $("ov-free") };

    // ---------- zoom ----------
    const PAD = 16, MAX_SCALE = 16;
    const maxC = () => cs * MAX_SCALE;
    // Below 1x the cell size halves down to 1 device pixel (2, 1 with the default cell size); the gaps cannot be kept
    // there, so the image is scaled smoothly instead of nearest-neighbour.
    function lowSteps() {
        const steps = [];
        for (let v = cs; v > 1;) { v = Math.max(1, Math.floor(v / 2)); steps.push(v); }
        return steps;
    }
    const minC = () => lowSteps().at(-1) ?? cs;
    function fitC() {
        const w = (viewport.clientWidth - 2 * PAD) * dpr, h = (viewport.clientHeight - 2 * PAD) * dpr;
        const f = Math.min(maxC(), Math.floor(w / GW), Math.floor(h / GH));
        return f >= cs ? f : lowSteps().find((v) => v <= f) ?? minC();
    }
    // Zoom steps grow by about a quarter: 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, ...
    const stepOf = (v) => Math.max(1, 2 ** (Math.floor(Math.log2(v)) - 2));
    function zoomStep(v, dir) {
        if (dir > 0 && v < cs) return lowSteps().reverse().find((s) => s > v) ?? cs;
        if (dir < 0 && v <= cs) return lowSteps().find((s) => s < v) ?? minC();
        if (dir > 0) return Math.min(maxC(), Math.floor(v / stepOf(v)) * stepOf(v) + stepOf(v));
        const down = v - stepOf(v - 1);
        return Math.max(cs, Math.ceil(down / stepOf(down)) * stepOf(down));
    }
    const scaleText = (v) => `${Number((v / cs).toFixed(2))}×`;
    function layout(keepCenter) {
        if (!img || !img.naturalWidth) return;
        const vw = viewport.clientWidth, vh = viewport.clientHeight;
        const oldW = stage.offsetWidth || 1, oldH = stage.offsetHeight || 1;
        const cx = (viewport.scrollLeft + vw / 2 - stage.offsetLeft) / oldW;
        const cy = (viewport.scrollTop + vh / 2 - stage.offsetTop) / oldH;
        const w = (GW * c) / dpr, h = (GH * c) / dpr;
        img.style.width = `${w}px`;
        img.style.height = `${h}px`;
        const snap = (v) => Math.floor(v * dpr) / dpr;
        const left = snap(Math.max(PAD, (vw - w) / 2)), topPx = snap(Math.max(PAD, (vh - h) / 2));
        stage.style.left = `${left}px`;
        stage.style.top = `${topPx}px`;
        wrap.style.width = `${left + w + PAD}px`;
        wrap.style.height = `${topPx + h + PAD}px`;
        if (keepCenter) {
            viewport.scrollLeft = cx * w + left - vw / 2;
            viewport.scrollTop = cy * h + topPx - vh / 2;
        }
        document.documentElement.style.setProperty("--hair", `${1 / dpr}px`);
        stage.classList.add("laid-out");
        $("zoom-level").textContent = scaleText(c);
        $("zoom-level").title = `1 ${layer ? "cell" : "address"} = ${c} device px`;
        img.classList.toggle("smooth", c < cs);
        $("zoom-out").disabled = c <= minC();
        $("zoom-in").disabled = c >= maxC();
        $("zoom-fit").classList.toggle("active", fitMode);
        drawOverlays();
    }
    function setC(v, byUser) {
        c = Math.max(minC(), Math.min(maxC(), v));
        fitMode = !byUser;
        layout(true);
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
    }

    // ---------- changes of the last update that changed this prefix ----------
    const CHANGE_KINDS = [["added", "added"], ["removed", "removed"], ["changed", "changed"]];
    let showChanges = store.get("prefix-map.show-changes") === "1";
    function drawChanges() {
        const box = $("ov-changes");
        const ch = data && data.changes;
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
        const ch = data.changes;
        if (!ch) return null;
        const n = (key) => ch[`${key}_count`] ?? (ch[key] || []).length;
        const parts = [
            n("added") ? `${fmt(n("added"))} IP added` : null,
            n("removed") ? `${fmt(n("removed"))} removed` : null,
            n("changed") ? `${fmt(n("changed"))} changed` : null,
            n("prefixes_added") ? `${fmt(n("prefixes_added"))} prefix${n("prefixes_added") > 1 ? "es" : ""} added` : null,
            n("prefixes_removed") ? `${fmt(n("prefixes_removed"))} prefix${n("prefixes_removed") > 1 ? "es" : ""} removed` : null,
        ].filter(Boolean);
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
        return sec("Last change", new Date(ch.at * 1000).toLocaleString(),
            el("div", { class: "sub" }, parts.join(" · ")),
            el("table", { class: "free changes" }, el("tbody", null, rows.slice(0, 8).map(([text, cls]) => {
                const isPrefix = text.includes("/");
                return el("tr", { onclick: img ? () => (isPrefix ? outline(parsePrefix(text)) : pin(blockStart(ipToInt(text)), true)) : null },
                    el("td", { text }), el("td", { class: `n ${cls}`, text: cls }));
            }))),
            rows.length > 8 ? el("div", { class: "hint", text: `${fmt(rows.length - 8)} more` }) : null,
            img ? el("label", { class: "check" }, toggle, " Show on the map") : null);
    }
    function scrollToBounds([x1, y1, x2, y2]) {
        const u = c / dpr;
        const cx = stage.offsetLeft + ((x1 + x2 + 1) / 2) * u, cy = stage.offsetTop + ((y1 + y2 + 1) / 2) * u;
        viewport.scrollTo({ left: cx - viewport.clientWidth / 2, top: cy - viewport.clientHeight / 2 });
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
        if (child) return { label: `open map of ${child.p.prefix}`, url: mapUrl(child.p.vrf ?? data.vrf, child.p.prefix) };
        const ip = ipsByAddr.get(a);
        if (ip && ip.id) return { label: "open the IP in NetBox", url: `${NB}/ipam/ip-addresses/${ip.id}/`, external: true };
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
        role: { color: "#ff0000", svg: ["#ff0000", 1], label: "With role" },
        active: { color: "#000", svg: ["#000", 1], label: "In use" },
        dhcp: { color: "rgba(0,0,0,.55)", svg: ["#000", 0.55], label: "DHCP" },
        reserved: { color: "rgba(0,0,0,.25)", svg: ["#000", 0.25], label: "Reserved, deprecated" },
        inactive: { color: "rgba(0,0,0,.1)", svg: ["#000", 0.1], label: "Inactive" },
    };
    const STATUS_KIND = { dhcp: "dhcp", slaac: "dhcp", reserved: "reserved", deprecated: "reserved", inactive: "inactive" };
    const ipKind = (ip) => (ip.role ? "role" : STATUS_KIND[ip.status] || "active");
    const ipColor = (ip) => IP_KINDS[ipKind(ip)].color;
    const STATUS_LABEL = { dhcp: "DHCP", slaac: "SLAAC" };
    const statusLabel = (s) => STATUS_LABEL[s] || capital(s);
    const swatchStyle = (c) => `background:linear-gradient(${c},${c}),#fff`;
    const tenantNode = (id) => (id ? el("span", null,
        el("span", { class: "tswatch", style: `background:${tenantColors.get(String(id)) || "transparent"}` }),
        nbLink(`/tenancy/tenants/${id}/`, tenantName(id))) : null);

    function freeSizeSelect(range) {
        const maxLen = layer ? blockLen : 32;
        const select = el("select", { "aria-label": "Free block size", title: "Size of the free blocks to list" },
            el("option", { value: "", text: "largest" }),
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
        const title = el("span", null, "Free blocks in ", el("span", { class: "mono", text: label }));
        if (range.len >= blockLen) {
            return sec(title, null,
                el("div", { class: "empty", text: `Smaller than a cell of this map; see the map of ${label}.` }));
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
                    el("td", { class: "n", text: b.size === 1 ? "1 address" : `${fmt(b.size)} addr` }),
                    el("td", { class: "c" }, copyBtn(prefix)));
            })))
            : el("div", { class: "empty", text: bySize ? `No free /${freeSize}.` : "No free addresses." });
        const rest = list.count - shown.length;
        const more = rest > 0 ? el("div", { class: "hint", text: bySize ? `${fmt(rest)} more free /${freeSize}` : `${fmt(rest)} smaller blocks not shown` }) : null;
        const right = bySize ? `${fmt(list.count)} × /${freeSize}` : `${fmt(fb.total)} free`;
        return sec(title, right, el("div", { class: "fsize" }, el("label", null, "Size ", freeSizeSelect(range))), body, more);
    }

    const vlanName = (id) => {
        const v = id ? (cfg.names.vlans || {})[String(id)] : null;
        return id ? (v ? `VLAN ${v.vid}` : `VLAN #${id}`) : null;
    };
    const vrfLabel = (vrf) => (vrf === null || vrf === undefined ? "Global" : cfg.vrf && String(cfg.vrf.id) === String(vrf) ? cfg.vrf.name : `VRF #${vrf}`);
    function dupeSection(list) {
        return sec("All records of this address", `${list.length}`, el("table", { class: "free dupes" }, el("tbody", null, list.map((ip) =>
            el("tr", null,
                el("td", { text: vrfLabel(ip.vrf) }),
                el("td", { text: [statusLabel(ip.status), ip.role, ip.dns_name].filter(Boolean).join(" · ") }),
                el("td", { class: "n" }, ip.id ? nbLink(`/ipam/ip-addresses/${ip.id}/`, "NetBox") : null))))),
            el("div", { class: "hint", text: "The map shows one: with a role first, then active, reserved, inactive." }));
    }
    const roleName = (id) => (id ? cfg.names.roles[String(id)] || `Role ${id}` : null);
    function rangeSection(list) {
        return sec(list.length > 1 ? `IP ranges` : "IP range", list.length > 1 ? `${list.length}` : null, ...list.slice(0, 4).map(({ r }) =>
            el("div", { class: "range-item" },
                el("div", { class: "mono" }, `${r.start} – ${r.end}`, copyBtn(`${r.start}-${r.end}`)),
                kv([
                    ["NetBox", r.id ? nbLink(`/ipam/ip-ranges/${r.id}/`, "IP range") : null],
                    ["Size", `${fmt(r.size)} addresses`],
                    ["Status", statusLabel(r.status)],
                    ["Role", roleName(r.role)],
                    ["Description", r.description || null],
                ]))));
    }

    function chainSection(chainNodes) {
        const chain = [
            ...cfg.parents.map((p) => ({ prefix: p.prefix, id: p.id, vrf: cfg.vrfKey, desc: p.description, tenant: p.tenant, pool: p.is_pool, vlan: p.vlan })),
            { prefix: cfg.prefix, id: cfg.prefixId, vrf: cfg.vrfKey, desc: cfg.details.description, tenant: cfg.details.tenant_id, here: true,
                pool: data.is_pool ?? cfg.details.is_pool, vlan: cfg.details.vlan_id },
            ...chainNodes.map((n) => ({ prefix: n.p.prefix, id: n.p.id, vrf: n.p.vrf ?? data.vrf, desc: n.p.description, tenant: n.p.tenant, pool: n.p.is_pool, vlan: n.p.vlan })),
        ];
        const innerPrefix = chain.at(-1).prefix;
        return sec("Prefix chain", `${chain.length} levels`, el("ol", { class: "chain" }, chain.map((c) => {
            const desc = [c.pool ? "pool" : null, c.desc, tenantName(c.tenant), vlanName(c.vlan)].filter(Boolean).join(" · ");
            return el("li", { class: [c.here ? "here" : "", c.prefix === innerPrefix ? "inner" : ""].join(" ").trim() || null },
                el("span", { class: "p", text: c.prefix }),
                el("span", { class: "l" },
                    c.here ? el("span", { text: "this map" }) : el("a", { href: mapUrl(c.vrf, c.prefix), text: "map" }),
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
                count === null ? el("span", { class: "pill", text: "IPs unknown" })
                    : count ? el("span", { class: "pill", text: `${fmt(count)} used` }) : el("span", { class: "pill free", text: "No IPs" }),
                el("span", { class: "mono", text: count === null ? `${fmt(blockSize)} addresses` : `${pct(count, blockSize)} of ${fmt(blockSize)}` })),
            action ? el("div", { class: "hint", text: `Double-click to ${action.label}` })
                : el("div", { class: "hint", text: "No prefix in this block" }))];
        const blockRanges = rangesAt(a, blockSize);
        if (blockRanges.length) out.push(rangeSection(blockRanges));
        out.push(chainSection(chainNodes));
        if (smaller.length) {
            const shown = smaller.slice(0, 8);
            out.push(sec("Prefixes in this block", `${fmt(smaller.length)}`, el("ol", { class: "chain" }, shown.map((n) =>
                el("li", null, el("span", { class: "p", text: n.p.prefix }),
                    el("span", { class: "l" }, el("a", { href: mapUrl(n.p.vrf ?? data.vrf, n.p.prefix), text: "map" }),
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
            if (img) setBadge(el("span", { class: "badge", text: "hover the map" }));
            return;
        }
        setBadge(pinned !== null
            ? el("span", { class: "pin-badge" }, "Pinned", el("button", {
                type: "button", title: "Unpin (Esc)", "aria-label": "Unpin", text: "×", onclick: () => pin(null),
            }))
            : el("span", { class: "badge", text: "click to pin" }));
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
                    : edge ? el("span", { class: "pill", text: `${capital(edge)} address` })
                        : inRange.length ? el("span", { class: "pill" }, el("span", { class: "sw range" }), "IP range")
                            : el("span", { class: "pill free", text: "Free" }),
                dupes.has(a) ? el("span", { class: "pill warn", text: `${dupes.get(a).length} records` }) : null,
                pool ? el("span", { class: "pill", text: "Pool", title: `${pool} is a pool: all its addresses are usable, network and broadcast included` }) : null,
                el("span", { class: "mono", text: `offset ${fmt(a - net.start)}` })),
            action ? el("div", { class: "hint", text: `Double-click to ${action.label}` }) : null));
        if (ip) {
            out.push(sec("IP address", ip.id ? nbLink(`/ipam/ip-addresses/${ip.id}/`, "NetBox") : null, kv([
                ["Status", statusLabel(ip.status)],
                ["Role", capital(ip.role)],
                ["DNS name", ip.dns_name ? el("span", { class: "mono", text: ip.dns_name }) : null],
                ["Description", ip.description || null],
                ["Tenant", tenantNode(ip.tenant)],
            ])));
        } else if (edge) {
            out.push(sec("IP address", null, el("div", { class: "empty",
                text: `${capital(edge)} address of ${(inner ? inner.p.prefix : cfg.prefix)}: not usable for hosts.` })));
        } else {
            const vrfParam = cfg.vrf ? `&vrf=${encodeURIComponent(cfg.vrf.id)}` : "";
            out.push(sec("IP address", null, el("div", { class: "empty" }, "No IP record. ",
                nbLink(`/ipam/ip-addresses/add/?address=${intToIp(a)}/${mask}${vrfParam}`, "Add in NetBox"))));
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
                    el("span", { text: used === null ? "IPs" : `IPs · ${pct(used, total)}` })),
                el("div", { class: "stat" }, el("b", { text: fmt((data.child_prefixes || []).length) }), el("span", { text: "child prefixes" })),
                el("div", { class: "stat" }, el("b", { text: fmt(total) }), el("span", { text: "addresses" }))));
        const sections = [];
        if (hasIps || countsKnown) sections.push(freeSection(net, cfg.prefix));
        sections.push(changesSection());
        if (dupes.size) {
            const shown = [...dupes.keys()].sort((x, y) => x - y).slice(0, 8);
            sections.push(sec("Addresses with several records", `${fmt(dupes.size)}`, el("table", { class: "free" }, el("tbody", null,
                shown.map((a) => el("tr", { onclick: () => pin(a, true) },
                    el("td", { text: intToIp(a) }),
                    el("td", { class: "n", text: dupes.get(a).map((ip) => vrfLabel(ip.vrf)).join(", ") }))))),
                dupes.size > shown.length ? el("div", { class: "hint", text: `${fmt(dupes.size - shown.length)} more` }) : null));
        }
        $("sum-free").replaceChildren(...sections.filter(Boolean));
        const big = document.querySelector("#insp-summary .big");
        if (big && !big.querySelector(".copy")) big.append(copyBtn(cfg.prefix));
    }

    const usageText = () => (used === null ? `${fmt(net.size)} addresses`
        : `${fmt(used)} / ${fmt(net.size)} used · ${((100 * used) / net.size).toFixed(used && used < net.size / 1000 ? 2 : 1)}%`);

    function renderLegend() {
        const sw = (c) => el("span", { class: "sw", style: swatchStyle(c) });
        const tenants = new Map();
        for (const p of data.nested_prefixes || data.child_prefixes || []) {
            if (p.tenant && p.color && !tenants.has(p.tenant)) tenants.set(p.tenant, p.color);
        }
        const keys = layer
            ? el("span", { class: "lg-group" },
                el("span", { class: "lg-label", text: "IPs per block" }),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.25)"), "few"),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.575)"), "25%"),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.9)"), "all"),
                el("span", { class: "lg" }, el("span", { class: "sw checker" }), "prefixes inside"))
            : el("span", { class: "lg-group" }, ["active", "dhcp", "reserved", "inactive", "role"]
                .filter((kind) => !hasIps || kind === "active" || kind === "role" || (data.ip_addresses || []).some((ip) => ipKind(ip) === kind))
                .map((kind) => el("span", { class: "lg" }, sw(IP_KINDS[kind].color), IP_KINDS[kind].label)),
                ranges.length ? el("span", { class: "lg" }, el("span", { class: "sw range" }), "IP range") : null);
        // replaceChildren() would print null as text
        $("legend").replaceChildren(...[
            keys,
            tenants.size ? el("span", { class: "vsep" }) : null,
            tenants.size ? el("span", { class: "lg-group tenants" }, el("span", { class: "lg-label", text: "Tenants" }),
                [...tenants].sort((a, b) => tenantName(a[0]).localeCompare(tenantName(b[0])))
                    .map(([id, c]) => {
                        // Colours come from a 16-colour palette by tenant id: tenants 1 and 17 look the same
                        const same = [...tenants].filter(([o, oc]) => o !== id && oc === c).map(([o]) => tenantName(o));
                        return el("span", { class: same.length ? "lg same-color" : "lg", title: same.length ? `Same colour as ${same.join(", ")}` : null },
                            sw(c), tenantName(id), same.length ? el("span", { class: "same-mark", text: "=" }) : null);
                    })) : null,
            el("span", { class: "right", id: "usage-total" },
                usageText(),
                img ? el("span", { class: "cellnote", text: layer ? ` · 1 cell = /${blockLen}` : " · 1 cell = 1 address" }) : null),
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
            const count = countsKnown ? ` · ${fmt(blockCounts.get((a - net.start) / blockSize) || 0)} IPs` : "";
            ui.say(`${intToIp(addr)} is in block ${intToIp(a)}/${blockLen}${count} — pinned`);
            return true;
        }
        if (len === null) {
            const ip = ipsByAddr.get(addr);
            pin(addr, true);
            const edge = ip ? null : edgeKind(addr);
            ui.say(`${intToIp(addr)} · ${ip ? statusLabel(ip.status) + (ip.dns_name ? ` · ${ip.dns_name}` : "") : edge ? `${edge} address` : "free"} — pinned`);
            return true;
        }
        const start = addr - (addr % 2 ** (32 - len));
        const prefix = `${intToIp(start)}/${len}`;
        if (prefix === cfg.prefix) { ui.say("This map."); return true; }
        const node = nested.find((n) => n.p.prefix === prefix);
        outline(parsePrefix(prefix));
        if (node) {
            ui.say(`${prefix}${node.p.description ? ` · ${node.p.description}` : ""} — outlined. Enter opens its map.`);
            if (commit) navigate(mapUrl(node.p.vrf ?? data.vrf, prefix));
        } else {
            ui.say(`${prefix} is not a NetBox prefix; outlined as a range.`);
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
    document.addEventListener("keydown", (ev) => {
        if (ev.target.closest?.("input, select, textarea") || ev.ctrlKey || ev.metaKey || ev.altKey) return;
        if (img && img.naturalWidth && data && moveKey(ev)) return;
        if (ev.key === "Escape") {
            if (pinned !== null) pin(null);
            else if (selected) { selected = null; drawOverlays(); syncUrl(); }
        } else if (ev.key === "[") setPanel("tree", !panelOpen("tree"));
        else if (ev.key === "]") setPanel("insp", !panelOpen("insp"));
        else if (!img || !img.naturalWidth) return;
        else if (ev.key === "+" || ev.key === "=") setC(zoomStep(c, 1), true);
        else if (ev.key === "-") setC(zoomStep(c, -1), true);
        else if (ev.key === "0") setC(fitC(), false);
    });
    // Arrows move the pinned cell (Shift: 16 cells), Enter opens it, c copies it
    const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    function ensureVisible([x1, y1, x2, y2]) {
        const u = c / dpr, m = 24;
        const l = stage.offsetLeft + x1 * u, t = stage.offsetTop + y1 * u, r = stage.offsetLeft + (x2 + 1) * u, b = stage.offsetTop + (y2 + 1) * u;
        if (l < viewport.scrollLeft + m) viewport.scrollLeft = l - m;
        else if (r > viewport.scrollLeft + viewport.clientWidth - m) viewport.scrollLeft = r - viewport.clientWidth + m;
        if (t < viewport.scrollTop + m) viewport.scrollTop = t - m;
        else if (b > viewport.scrollTop + viewport.clientHeight - m) viewport.scrollTop = b - viewport.clientHeight + m;
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
        if (ev.key === "c") {
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
        layout(false);
        $("zoom-in").addEventListener("click", () => setC(zoomStep(c, 1), true));
        $("zoom-out").addEventListener("click", () => setC(zoomStep(c, -1), true));
        $("zoom-fit").addEventListener("click", () => setC(fitC(), false));
        new ResizeObserver(() => { if (fitMode) c = fitC(); layout(!fitMode); }).observe(viewport);
        const watchDpr = () => matchMedia(`(resolution: ${dpr}dppx)`).addEventListener("change", () => {
            dpr = window.devicePixelRatio || 1;
            if (fitMode) c = fitC();
            layout(false);
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
        $("sum-export").replaceChildren(sec("Export", null, el("div", { class: "links" },
            action("Print map with legend", () => exp.print(bw.checked)),
            action("Download SVG", () => exp.download(bw.checked)),
            el("label", { class: "check" }, bw, " Black and white (hatched tenants)"))));
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
                applyFocus();
                initExport();
            }
            document.body.dataset.ready = "1";
        })
        .catch((error) => {
            $("legend").textContent = `Map data unavailable: ${error.message}`;
            document.body.dataset.ready = "error";
        });

    window.__prefixMap = { get k() { return c / cs; }, get c() { return c; }, get dpr() { return dpr; }, cellToOffset, offsetToCell, freeBlocks: (p) => freeBlocks(parsePrefix(p)), cellOf };
})();
