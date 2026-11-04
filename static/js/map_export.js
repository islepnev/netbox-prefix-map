// Vector export of the map page: an SVG drawn from the same data file as the PNG (cells, prefix outlines,
// labels, title and legend). Used for "Download SVG" and for printing: the print stylesheet shows only #print-sheet.
window.PrefixMapExport = (() => {
    "use strict";
    const U = 10;          // one cell, in SVG units
    const GAP = 1.5;       // gap at the left and top of a cell, as on the PNG
    const BODY = U - GAP;
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    // Black-and-white hatches for tenants, in order of first appearance on the map
    const HATCHES = [
        '<path d="M0 8L8 0" stroke="#000" stroke-width=".9"/>',
        '<path d="M0 0L8 8" stroke="#000" stroke-width=".9"/>',
        '<path d="M0 4H8" stroke="#000" stroke-width=".9"/>',
        '<path d="M4 0V8" stroke="#000" stroke-width=".9"/>',
        '<circle cx="4" cy="4" r="1.1" fill="#000"/>',
        '<path d="M0 8L8 0M0 0L8 8" stroke="#000" stroke-width=".6"/>',
        '<path d="M0 4H8M4 0V8" stroke="#000" stroke-width=".6"/>',
        '<circle cx="2" cy="2" r=".9" fill="#000"/><circle cx="6" cy="6" r=".9" fill="#000"/>',
    ];
    let ctx = null;

    function init(context) { ctx = context; }

    // Usage darkness of a layered-map block; mirrors layer_usage_alpha() in app/plot_map.py
    const layerAlpha = (count, size) => (count ? 0.25 + 0.65 * Math.sqrt(Math.min(1, count / size)) : 0);

    function build({ mono = false } = {}) {
        if (!ctx || !ctx.GW) return null;
        const { cfg, data, net, GW, GH, layer, blockLen, blockSize, cellOf, rangeBounds, intToIp } = ctx;
        const W = GW * U, H = GH * U;
        const fs = Math.max(11, Math.round(W / 55));
        const defs = [];
        const body = [];
        const box = (start, end) => { const [x1, y1, x2, y2] = rangeBounds(start, end); return [x1 * U, y1 * U, (x2 - x1 + 1) * U, (y2 - y1 + 1) * U]; };

        // Tenant fills: color, or one hatch per tenant in black and white
        const tenantFill = new Map();
        const tenantOrder = [];
        const fillOf = (p) => {
            if (!p.tenant || !p.color) return null;
            const key = String(p.tenant);
            if (!tenantFill.has(key)) {
                tenantOrder.push(key);
                if (mono) {
                    const id = `t${tenantFill.size}`;
                    defs.push(`<pattern id="${id}" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#fff"/>${HATCHES[tenantFill.size % HATCHES.length]}</pattern>`);
                    tenantFill.set(key, `url(#${id})`);
                } else {
                    tenantFill.set(key, p.color);
                }
            }
            return tenantFill.get(key);
        };

        body.push(`<rect width="${W}" height="${H}" fill="#fff"/>`);
        // Grid every 16 cells, inner lines only
        const grid = [];
        for (let x = 16; x < GW; x += 16) grid.push(`M${x * U} 0V${H}`);
        for (let y = 16; y < GH; y += 16) grid.push(`M0 ${y * U}H${W}`);
        if (grid.length) body.push(`<path d="${grid.join("")}" stroke="#ccc" stroke-width="${U / 10}" stroke-dasharray="${U / 5} ${U / 5}" fill="none"/>`);

        // Nested prefixes, longer ones on top; on layered maps only those of a block or larger form a rectangle
        const nested = [...ctx.nested].sort((a, b) => a.len - b.len);
        const partial = new Map();
        for (const n of nested) {
            if (layer && n.len > blockLen) {
                const first = n.start - ((n.start - net.start) % blockSize);
                const color = n.p.tenant && n.p.color ? n.p.color : null;
                if (!partial.has(first) || (!partial.get(first) && color)) partial.set(first, color);
                continue;
            }
            const fill = fillOf(n.p);
            const [x, y, w, h] = box(n.start, n.end);
            body.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill || "none"}" stroke="#000" stroke-width="${U / 16}" stroke-dasharray="${U / 5} ${U / 5}"><title>${esc(n.p.prefix)}</title></rect>`);
        }

        // Labels: the octet that tells the 16 x 16-cell groups apart; mirrors block_labels() in app/plot_map.py
        const groupLen = blockLen - 8;
        if (groupLen >= net.len && groupLen >= 8 && Math.floor(net.len / 8) === Math.floor((groupLen - 1) / 8)) {
            const octet = Math.floor((groupLen - 1) / 8), step = 2 ** (32 - groupLen);
            const labels = [];
            for (let a = net.start; a <= net.end; a += step) {
                const [x1, y1, x2, y2] = rangeBounds(a, a + step - 1);
                const text = intToIp(a).split(".")[octet];
                labels.push(`<text x="${((x1 + x2 + 1) / 2) * U}" y="${((y1 + y2 + 1) / 2) * U}">${text}</text>`);
            }
            body.push(`<g font-family="monospace" font-size="${4 * U}" fill="#000" fill-opacity=".14" text-anchor="middle" dominant-baseline="central">${labels.join("")}</g>`);
        }

        if (layer) {
            // Blocks with smaller prefixes inside: checkerboard in the tenant color, gray without one
            const checks = new Map();
            const checkOf = (color) => {
                const c = mono ? "#999" : color || "#b0b0b0";
                if (!checks.has(c)) {
                    const id = `c${checks.size}`;
                    defs.push(`<pattern id="${id}" width="${U / 4}" height="${U / 4}" patternUnits="userSpaceOnUse"><rect width="${U / 4}" height="${U / 4}" fill="#fff"/><rect width="${U / 8}" height="${U / 8}" fill="${c}"/><rect x="${U / 8}" y="${U / 8}" width="${U / 8}" height="${U / 8}" fill="${c}"/></pattern>`);
                    checks.set(c, `url(#${id})`);
                }
                return checks.get(c);
            };
            for (const [first, color] of partial) {
                const [x, y] = cellOf(first);
                body.push(`<rect x="${x * U + GAP}" y="${y * U + GAP}" width="${BODY}" height="${BODY}" fill="${checkOf(color)}"/>`);
            }
            const cells = [];
            for (const [index, count] of ctx.blockCounts) {
                const [x, y] = cellOf(net.start + index * blockSize);
                cells.push(`<rect x="${x * U + GAP}" y="${y * U + GAP}" width="${BODY}" height="${BODY}" fill-opacity="${layerAlpha(count, blockSize).toFixed(3)}"/>`);
            }
            body.push(`<g fill="#000">${cells.join("")}</g>`);
            const outlines = ctx.children.filter((c) => c.len <= blockLen).map((c) => {
                const [x, y, w, h] = box(c.start, c.end);
                return `<rect x="${x}" y="${y}" width="${w}" height="${h}"/>`;
            });
            body.push(`<g fill="none" stroke="#444" stroke-width="${U / 8}">${outlines.join("")}</g>`);
        } else {
            // One cell per IP record, grouped by kind
            const byKind = new Map();
            for (const ip of data.ip_addresses || []) {
                const a = ctx.ipToInt(ip.address.split("/")[0]);
                if (a < net.start || a > net.end) continue;
                const kind = ctx.ipKind(ip);
                if (!byKind.has(kind)) byKind.set(kind, []);
                const [x, y] = cellOf(a);
                byKind.get(kind).push(`<rect x="${x * U + GAP}" y="${y * U + GAP}" width="${BODY}" height="${BODY}"/>`);
                // In black and white a role reads as a hollow black cell
                if (mono && kind === "role") byKind.get(kind).push(`<rect x="${x * U + GAP + BODY / 3}" y="${y * U + GAP + BODY / 3}" width="${BODY / 3}" height="${BODY / 3}" fill="#fff"/>`);
            }
            for (const [kind, rects] of byKind) {
                const k = ctx.IP_KINDS[kind];
                const fill = mono && kind === "role" ? "#000" : k.svg[0];
                body.push(`<g fill="${fill}" fill-opacity="${mono && kind === "role" ? 1 : k.svg[1]}">${rects.join("")}</g>`);
            }
        }

        // Title above the map, legend below it
        const pad = fs;
        const vrfName = cfg.vrf ? cfg.vrf.name : "Global";
        const title = [`${cfg.prefix}`, `VRF ${vrfName}`, cfg.details.description].filter(Boolean).join(" · ");
        const sub = [ctx.usageText(), layer ? `1 cell = /${blockLen}` : "1 cell = 1 address",
            data.generated_at ? `data of ${new Date(data.generated_at * 1000).toLocaleString()}` : null].filter(Boolean).join(" · ");
        const titleH = pad + fs * 1.3 + fs * 1.4;
        const items = [];
        if (layer) {
            items.push({ fill: "#000", opacity: 0.25, label: "few IPs" }, { fill: "#000", opacity: 0.575, label: "25%" },
                { fill: "#000", opacity: 0.9, label: "all used" }, { check: true, label: "prefixes inside" });
        } else {
            const kinds = new Set((data.ip_addresses || []).map(ctx.ipKind));
            for (const kind of ["active", "dhcp", "reserved", "inactive", "role"]) {
                if (!kinds.has(kind)) continue;
                const k = ctx.IP_KINDS[kind];
                items.push({ fill: mono && kind === "role" ? "#000" : k.svg[0], opacity: mono && kind === "role" ? 1 : k.svg[1], hollow: mono && kind === "role", label: k.label });
            }
        }
        const tenantItems = tenantOrder.map((key) => ({ fill: tenantFill.get(key), opacity: 1, label: ctx.tenantName(key), outline: true }))
            .sort((a, b) => a.label.localeCompare(b.label));
        const rows = [];
        let row = [], used = 0;
        const sw = fs, itemW = (it) => sw + fs * 0.5 + it.label.length * fs * 0.62 + fs * 1.6;
        for (const it of [...items, ...(tenantItems.length ? [{ label: "Tenants:", heading: true }] : []), ...tenantItems]) {
            const w = it.heading ? it.label.length * fs * 0.62 + fs : itemW(it);
            if (used + w > W && row.length) { rows.push(row); row = []; used = 0; }
            row.push({ ...it, x: used });
            used += w;
        }
        if (row.length) rows.push(row);
        const legendY = titleH + H + pad;
        const legend = rows.flatMap((r, i) => r.map((it) => {
            const y = legendY + i * fs * 1.7;
            const text = `<text x="${it.x + (it.heading ? 0 : sw + fs * 0.5)}" y="${y + sw * 0.85}">${esc(it.label)}</text>`;
            if (it.heading) return text;
            const swatch = it.check
                ? `<rect x="${it.x}" y="${y}" width="${sw}" height="${sw}" fill="url(#legend-check)" stroke="#999" stroke-width="${fs / 12}"/>`
                : `<rect x="${it.x}" y="${y}" width="${sw}" height="${sw}" fill="${it.fill}" fill-opacity="${it.opacity}" stroke="#999" stroke-width="${fs / 12}"/>`
                    + (it.hollow ? `<rect x="${it.x + sw / 3}" y="${y + sw / 3}" width="${sw / 3}" height="${sw / 3}" fill="#fff"/>` : "");
            return swatch + text;
        }));
        if (layer) defs.push(`<pattern id="legend-check" width="${sw / 4}" height="${sw / 4}" patternUnits="userSpaceOnUse"><rect width="${sw / 4}" height="${sw / 4}" fill="#fff"/><rect width="${sw / 8}" height="${sw / 8}" fill="#999"/><rect x="${sw / 8}" y="${sw / 8}" width="${sw / 8}" height="${sw / 8}" fill="#999"/></pattern>`);
        const totalH = legendY + rows.length * fs * 1.7 + pad / 2;

        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${Math.ceil(totalH)}" width="${W}" height="${Math.ceil(totalH)}" shape-rendering="crispEdges">`
            + `<title>${esc(title)}</title><defs>${defs.join("")}</defs>`
            + `<rect width="${W}" height="${Math.ceil(totalH)}" fill="#fff"/>`
            + `<g font-family="sans-serif" fill="#000"><text x="0" y="${pad + fs * 0.3}" font-size="${fs * 1.3}" font-weight="bold">${esc(title)}</text>`
            + `<text x="0" y="${pad + fs * 1.9}" font-size="${fs}" fill="#444">${esc(sub)}</text></g>`
            + `<g transform="translate(0 ${titleH})">${body.join("")}<rect width="${W}" height="${H}" fill="none" stroke="#000" stroke-width="${U / 8}"/></g>`
            + `<g font-family="sans-serif" font-size="${fs}" fill="#000">${legend.join("")}</g>`
            + `</svg>`;
    }

    function fileName(mono) {
        const vrf = ctx.cfg.vrfKey;
        return `prefix-map-${vrf}-${ctx.cfg.prefix.replace(/[./]/g, "_")}${mono ? "-bw" : ""}.svg`;
    }

    function download(mono) {
        const svg = build({ mono });
        if (!svg) return;
        const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = fileName(mono);
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    // Print: the print stylesheet hides the page and shows only this sheet
    let mono = false;
    function preparePrint() {
        const svg = build({ mono });
        if (!svg) return;
        let sheet = document.getElementById("print-sheet");
        if (!sheet) { sheet = document.createElement("div"); sheet.id = "print-sheet"; document.body.append(sheet); }
        sheet.innerHTML = svg;
        // Wide maps (two squares side by side) print in landscape
        let page = document.getElementById("print-page");
        if (!page) { page = document.createElement("style"); page.id = "print-page"; document.head.append(page); }
        page.textContent = `@page { size: ${ctx.GW > ctx.GH ? "landscape" : "portrait"}; margin: 10mm; }`;
    }
    window.addEventListener("beforeprint", preparePrint);

    return {
        init,
        build,
        download,
        preparePrint,
        print(bw) { mono = !!bw; preparePrint(); window.print(); mono = false; },
        setMono(bw) { mono = !!bw; },
    };
})();
