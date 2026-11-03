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
    const pct = (u, t) => { const v = (100 * u) / t; return v === 0 ? "0%" : v < 1 ? "<1%" : `${Math.round(v)}%`; };
    const vrfKey = (vrf) => (vrf === null || vrf === undefined ? "None" : String(vrf));
    const sanitize = (p) => p.replace(/[./]/g, "_");
    const mapUrl = (vrf, prefix) => `${cfg.basePath}/map/${vrfKey(vrf)}/${sanitize(prefix)}`;
    const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
    const tenantName = (id) => (id ? cfg.names.tenants[String(id)] || `Tenant ${id}` : null);
    const nbLink = (path, text) => el("a", { class: "ext", href: `${NB}${path}`, target: "_blank", rel: "noopener", text });
    const top = window.PrefixMapTop;

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
    let ipsByAddr = new Map();
    let ipSorted = new Float64Array(0);
    let nested = [];
    let children = [];
    const tenantColors = new Map();

    const lowerBound = (v) => {
        let lo = 0, hi = ipSorted.length;
        while (lo < hi) { const m = (lo + hi) >> 1; if (ipSorted[m] < v) lo = m + 1; else hi = m; }
        return lo;
    };
    const countIps = (s, e) => lowerBound(e + 1) - lowerBound(s);
    const containing = (addr) => nested.filter((n) => addr >= n.start && addr <= n.end);
    const childAt = (addr) => {
        let best = null;
        for (const c of children) if (addr >= c.start && addr <= c.end && (!best || c.len > best.len)) best = c;
        return best;
    };
    const childrenOf = (range) => {
        const inside = nested.filter((n) => n.start >= range.start && n.end <= range.end && n.len > range.len);
        return inside.filter((n) => !inside.some((m) => m.len < n.len && n.start >= m.start && n.end <= m.end));
    };

    // Largest aligned blocks with no IP record and no child prefix
    const freeCache = new Map();
    function freeBlocks(range) {
        const key = `${range.start}/${range.len}`;
        if (freeCache.has(key)) return freeCache.get(key);
        const blocks = [];
        (function walk(start, len, kids) {
            const size = 2 ** (32 - len), end = start + size - 1;
            const overlap = kids.filter((k) => k.start <= end && k.end >= start);
            if (overlap.some((k) => k.start <= start && k.end >= end)) return;
            if (!overlap.length && countIps(start, end) === 0) { blocks.push({ start, len, size }); return; }
            if (len >= 32) return;
            walk(start, len + 1, overlap);
            walk(start + size / 2, len + 1, overlap);
        })(range.start, range.len, childrenOf(range));
        blocks.sort((a, b) => b.size - a.size || a.start - b.start);
        const res = { blocks, total: blocks.reduce((s, b) => s + b.size, 0) };
        freeCache.set(key, res);
        return res;
    }

    function indexData(loaded) {
        data = loaded;
        const ips = data.ip_addresses || [];
        hasIps = data.rendered ?? net.len >= 16;
        used = data.ip_count ?? ips.length;
        ipsByAddr = new Map(ips.map((ip) => [ipToInt(ip.address.split("/")[0]), ip]));
        ipSorted = Float64Array.from(ipsByAddr.keys()).sort();
        const list = data.nested_prefixes || data.child_prefixes || [];
        nested = list.map((p) => ({ ...parsePrefix(p.prefix), p })).sort((a, b) => a.start - b.start || a.len - b.len);
        children = (data.child_prefixes || []).map((p) => ({ ...parsePrefix(p.prefix), p }));
        for (const p of [data, ...(data.child_prefixes || []), ...(data.nested_prefixes || [])]) {
            if (p.tenant && p.color && !tenantColors.has(String(p.tenant))) tenantColors.set(String(p.tenant), p.color);
        }
        if (img) {
            // Data files from older versions lack grid and cell size; both follow from the prefix and the image
            const hostBits = 32 - net.len;
            GW = 2 ** (hostBits - Math.floor(hostBits / 2));
            GH = 2 ** Math.floor(hostBits / 2);
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
    function rangeBounds(start, end) {
        const [x1, y1] = offsetToCell(start - net.start), [x2, y2] = offsetToCell(end - net.start);
        return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
    }
    const cellBounds = (a) => { const [x, y] = offsetToCell(a - net.start); return [x, y, x, y]; };

    // ---------- state ----------
    let k = 1, fitMode = true, dpr = window.devicePixelRatio || 1;
    let hover = null, pinned = null, selected = null, freeHi = null;
    const viewport = $("viewport"), stage = $("stage"), wrap = $("stage-wrap");
    const ov = img && { hover: $("ov-hover"), pin: $("ov-pin"), prefix: $("ov-prefix"), select: $("ov-select"), free: $("ov-free") };

    // ---------- zoom: whole device pixels per image pixel, so the PNG is never resampled ----------
    const PAD = 16, MAX_K = 16;
    function fitK() {
        const w = (viewport.clientWidth - 2 * PAD) * dpr, h = (viewport.clientHeight - 2 * PAD) * dpr;
        return Math.max(1, Math.min(MAX_K, Math.floor(w / img.naturalWidth), Math.floor(h / img.naturalHeight)));
    }
    function layout(keepCenter) {
        if (!img || !img.naturalWidth) return;
        const vw = viewport.clientWidth, vh = viewport.clientHeight;
        const oldW = stage.offsetWidth || 1, oldH = stage.offsetHeight || 1;
        const cx = (viewport.scrollLeft + vw / 2 - stage.offsetLeft) / oldW;
        const cy = (viewport.scrollTop + vh / 2 - stage.offsetTop) / oldH;
        const w = (img.naturalWidth * k) / dpr, h = (img.naturalHeight * k) / dpr;
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
        $("zoom-level").textContent = `${k}×`;
        $("zoom-level").title = `${k} device px per image px · 1 address = ${cs * k} device px`;
        $("zoom-out").disabled = k <= 1;
        $("zoom-in").disabled = k >= MAX_K;
        $("zoom-fit").classList.toggle("active", fitMode);
        drawOverlays();
    }
    function setK(v, byUser) {
        k = Math.max(1, Math.min(MAX_K, v));
        fitMode = !byUser;
        layout(true);
    }

    // ---------- overlays, aligned to cell edges ----------
    function place(box, b) {
        if (!b) { box.hidden = true; return; }
        const u = (cs * k) / dpr;
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
    }
    function scrollToBounds([x1, y1, x2, y2]) {
        const u = (cs * k) / dpr;
        const cx = stage.offsetLeft + ((x1 + x2 + 1) / 2) * u, cy = stage.offsetTop + ((y1 + y2 + 1) / 2) * u;
        viewport.scrollTo({ left: cx - viewport.clientWidth / 2, top: cy - viewport.clientHeight / 2 });
    }

    function hitTest(ev) {
        const r = img.getBoundingClientRect();
        const x = Math.floor(((ev.clientX - r.left) * img.naturalWidth) / r.width / cs);
        const y = Math.floor(((ev.clientY - r.top) * img.naturalHeight) / r.height / cs);
        if (x < 0 || y < 0 || x >= GW || y >= GH) return null;
        return net.start + cellToOffset(x, y);
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
    function pin(a, scroll) {
        pinned = a;
        update();
        if (scroll && a !== null) scrollToBounds(cellBounds(a));
    }

    // What double-click opens: the child prefix map, else the IP in NetBox
    function openAction(a) {
        const child = childAt(a);
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
    const ipColor = (ip) => (ip.role ? "#ff0000" : ip.status === "reserved" ? "rgba(0,0,0,.25)" : "#000");
    const swatchStyle = (c) => `background:linear-gradient(${c},${c}),#fff`;
    const tenantNode = (id) => (id ? el("span", null,
        el("span", { class: "tswatch", style: `background:${tenantColors.get(String(id)) || "transparent"}` }),
        nbLink(`/tenancy/tenants/${id}/`, tenantName(id))) : null);

    function freeSection(range, label) {
        const fb = freeBlocks(range);
        const shown = fb.blocks.slice(0, 8);
        const body = shown.length
            ? el("table", { class: "free" }, el("tbody", null, shown.map((b) => el("tr", {
                onmouseenter: () => { freeHi = b; drawOverlays(); },
                onmouseleave: () => { freeHi = null; drawOverlays(); },
                onclick: img ? () => scrollToBounds(rangeBounds(b.start, b.start + b.size - 1)) : null,
            }, el("td", { text: `${intToIp(b.start)}/${b.len}` }),
                el("td", { class: "n", text: b.size === 1 ? "1 address" : `${fmt(b.size)} addr` })))))
            : el("div", { class: "empty", text: "No free addresses." });
        const more = fb.blocks.length > shown.length ? el("div", { class: "hint", text: `${fmt(fb.blocks.length - shown.length)} smaller blocks not shown` }) : null;
        return sec(el("span", null, "Free blocks in ", el("span", { class: "mono", text: label })), `${fmt(fb.total)} free`, body, more);
    }

    function setBadge(node) { $("insp-badge").replaceWith(node); node.id = "insp-badge"; }

    function renderInspector() {
        const a = pinned ?? hover;
        const detail = $("insp-detail"), summary = $("insp-summary");
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
        const ip = ipsByAddr.get(a);
        const chainNodes = containing(a);
        const inner = chainNodes.at(-1);
        const mask = ip ? ip.address.split("/")[1] : inner ? inner.len : net.len;
        const action = openAction(a);
        const out = [];
        out.push(el("section", { class: "sec" },
            el("div", { class: "big" }, intToIp(a), el("span", { class: "mask", text: `/${mask}` })),
            el("div", { class: "sub" },
                ip ? el("span", { class: "pill" }, el("span", { class: "sw", style: swatchStyle(ipColor(ip)) }), capital(ip.status) || "IP")
                    : el("span", { class: "pill free", text: "Free" }),
                el("span", { class: "mono", text: `offset ${fmt(a - net.start)}` })),
            action ? el("div", { class: "hint", text: `Double-click to ${action.label}` }) : null));
        if (ip) {
            out.push(sec("IP address", ip.id ? nbLink(`/ipam/ip-addresses/${ip.id}/`, "NetBox") : null, kv([
                ["Status", capital(ip.status)],
                ["Role", capital(ip.role)],
                ["DNS name", ip.dns_name ? el("span", { class: "mono", text: ip.dns_name }) : null],
                ["Description", ip.description || null],
                ["Tenant", tenantNode(ip.tenant)],
            ])));
        } else {
            const vrfParam = cfg.vrf ? `&vrf=${encodeURIComponent(cfg.vrf.id)}` : "";
            out.push(sec("IP address", null, el("div", { class: "empty" }, "No IP record. ",
                nbLink(`/ipam/ip-addresses/add/?address=${intToIp(a)}/${mask}${vrfParam}`, "Add in NetBox"))));
        }
        const chain = [
            ...cfg.parents.map((p) => ({ prefix: p.prefix, id: p.id, vrf: cfg.vrfKey, desc: p.description, tenant: p.tenant })),
            { prefix: cfg.prefix, id: cfg.prefixId, vrf: cfg.vrfKey, desc: cfg.details.description, tenant: cfg.details.tenant_id, here: true },
            ...chainNodes.map((n) => ({ prefix: n.p.prefix, id: n.p.id, vrf: n.p.vrf ?? data.vrf, desc: n.p.description, tenant: n.p.tenant })),
        ];
        const innerPrefix = chain.at(-1).prefix;
        out.push(sec("Prefix chain", `${chain.length} levels`, el("ol", { class: "chain" }, chain.map((c) => {
            const desc = [c.desc, tenantName(c.tenant)].filter(Boolean).join(" · ");
            return el("li", { class: [c.here ? "here" : "", c.prefix === innerPrefix ? "inner" : ""].join(" ").trim() || null },
                el("span", { class: "p", text: c.prefix }),
                el("span", { class: "l" },
                    c.here ? el("span", { text: "this map" }) : el("a", { href: mapUrl(c.vrf, c.prefix), text: "map" }),
                    c.id ? nbLink(`/ipam/prefixes/${c.id}/`, "NetBox") : null),
                desc ? el("span", { class: "d", text: desc, title: desc }) : null);
        }))));
        out.push(freeSection(inner || net, innerPrefix));
        detail.replaceChildren(...out);
        summary.hidden = true;
        detail.hidden = false;
    }

    function renderSummary() {
        const total = net.size;
        const counts = { role: 0, active: hasIps ? 0 : used, reserved: 0 };
        for (const ip of hasIps ? data.ip_addresses || [] : []) {
            if (ip.role) counts.role++;
            else if (ip.status === "reserved") counts.reserved++;
            else counts.active++;
        }
        const seg = (n, color, label) => (n ? el("i", { style: `width:${(100 * n) / total}%;background:${color}`, title: `${label}: ${fmt(n)}` }) : null);
        $("sum-usage").replaceChildren(
            el("div", { class: "bigbar" },
                seg(counts.active, "var(--text)", "In use"), seg(counts.role, "#ff0000", "With role"), seg(counts.reserved, "var(--faint)", "Reserved")),
            el("div", { class: "stats" },
                el("div", { class: "stat" }, el("b", { text: fmt(used) }), el("span", { text: `IPs · ${pct(used, total)}` })),
                el("div", { class: "stat" }, el("b", { text: fmt((data.child_prefixes || []).length) }), el("span", { text: "child prefixes" })),
                el("div", { class: "stat" }, el("b", { text: fmt(total) }), el("span", { text: "addresses" }))));
        if (hasIps) $("sum-free").replaceChildren(freeSection(net, cfg.prefix));
    }

    function renderLegend() {
        const sw = (c) => el("span", { class: "sw", style: swatchStyle(c) });
        const tenants = new Map();
        for (const p of data.nested_prefixes || data.child_prefixes || []) {
            if (p.tenant && p.color && !tenants.has(p.tenant)) tenants.set(p.tenant, p.color);
        }
        $("legend").replaceChildren(
            el("span", { class: "lg-group" },
                el("span", { class: "lg" }, sw("#000"), "In use"),
                el("span", { class: "lg" }, sw("rgba(0,0,0,.25)"), "Reserved"),
                el("span", { class: "lg" }, sw("#ff0000"), "With role")),
            tenants.size ? el("span", { class: "vsep" }) : null,
            tenants.size ? el("span", { class: "lg-group tenants" }, el("span", { class: "lg-label", text: "Tenants" }),
                [...tenants].sort((a, b) => tenantName(a[0]).localeCompare(tenantName(b[0])))
                    .map(([id, c]) => el("span", { class: "lg" }, sw(c), tenantName(id)))) : null,
            el("span", { class: "right", id: "usage-total" },
                `${fmt(used)} / ${fmt(net.size)} used · ${((100 * used) / net.size).toFixed(used && used < net.size / 1000 ? 2 : 1)}%`,
                img ? el("span", { class: "cellnote", text: " · 1 cell = 1 address" }) : null));
    }

    // ---------- search within this map ----------
    const IPV4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
    function localSearch(q, commit, ui) {
        const [addrPart, lenPart] = q.split("/");
        const len = lenPart === undefined ? null : Number(lenPart);
        if (!IPV4.test(addrPart) || (lenPart !== undefined && !(/^\d{1,2}$/.test(lenPart) && len <= 32))) {
            if (commit) { ui.bad(); ui.say("Enter an IPv4 address or prefix, e.g. 10.20.0.1 or 10.20.36.0/24"); } else ui.say(null);
            return;
        }
        const addr = ipToInt(addrPart);
        if (addr < net.start || addr > net.end || (len !== null && len < net.len)) {
            ui.say(`${q} is outside this map.`);
            return;
        }
        if (len === null) {
            const ip = ipsByAddr.get(addr);
            if (img) pin(addr, true);
            ui.say(`${intToIp(addr)} · ${ip ? capital(ip.status) + (ip.dns_name ? ` · ${ip.dns_name}` : "") : "free"}${img ? " — pinned" : ""}`);
            return;
        }
        const start = addr - (addr % 2 ** (32 - len));
        const prefix = `${intToIp(start)}/${len}`;
        const node = nested.find((n) => n.p.prefix === prefix);
        if (prefix === cfg.prefix) { ui.say("This map."); return; }
        selected = parsePrefix(prefix);
        if (img) { drawOverlays(); scrollToBounds(rangeBounds(selected.start, selected.end)); }
        if (node) {
            ui.say(`${prefix}${node.p.description ? ` · ${node.p.description}` : ""} — outlined. Enter opens its map.`);
            if (commit) navigate(mapUrl(node.p.vrf ?? data.vrf, prefix));
        } else {
            ui.say(`${prefix} is not a NetBox prefix; outlined as a range.`);
        }
    }

    // ---------- events ----------
    document.addEventListener("keydown", (ev) => {
        if (ev.target instanceof HTMLInputElement || ev.ctrlKey || ev.metaKey || ev.altKey) return;
        if (ev.key === "Escape") {
            if (pinned !== null) pin(null);
            else if (selected) { selected = null; drawOverlays(); }
        } else if (ev.key === "[") setPanel("tree", !panelOpen("tree"));
        else if (ev.key === "]") setPanel("insp", !panelOpen("insp"));
        else if (!img || !img.naturalWidth) return;
        else if (ev.key === "+" || ev.key === "=") setK(k + 1, true);
        else if (ev.key === "-") setK(k - 1, true);
        else if (ev.key === "0") setK(fitK(), false);
    });
    document.addEventListener("prefixtree:hover", (ev) => {
        const p = ev.detail.prefix ? parsePrefix(ev.detail.prefix) : null;
        selected = p && p.start >= net.start && p.end <= net.end && p.len > net.len ? p : null;
        drawOverlays();
    });

    function startMap() {
        k = fitK();
        layout(false);
        $("zoom-in").addEventListener("click", () => setK(k + 1, true));
        $("zoom-out").addEventListener("click", () => setK(k - 1, true));
        $("zoom-fit").addEventListener("click", () => setK(fitK(), false));
        new ResizeObserver(() => { if (fitMode) k = fitK(); layout(!fitMode); }).observe(viewport);
        const watchDpr = () => matchMedia(`(resolution: ${dpr}dppx)`).addEventListener("change", () => {
            dpr = window.devicePixelRatio || 1;
            if (fitMode) k = fitK();
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
            if (img) startMap();
            document.body.dataset.ready = "1";
        })
        .catch((error) => {
            $("legend").textContent = `Map data unavailable: ${error.message}`;
            document.body.dataset.ready = "error";
        });

    window.__prefixMap = { get k() { return k; }, get dpr() { return dpr; }, cellToOffset, offsetToCell, freeBlocks: (p) => freeBlocks(parsePrefix(p)) };
})();
