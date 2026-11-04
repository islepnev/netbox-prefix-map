// Vector export of the map page: an SVG drawn from the same data file as the PNG (cells, prefix outlines,
// labels, title and legend). Used for "Download SVG" and for printing: the print stylesheet shows only #print-sheet.
window.PrefixMapExport = (() => {
    "use strict";
    const U = 10;          // one cell, in SVG units
    const GAP = 1.5;       // gap at the left and top of a cell, as on the PNG
    const BODY = U - GAP;
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    // Black-and-white hatches for tenants, in order of first appearance on the map. They are drawn as vector lines and
    // dots clipped to each prefix rectangle, not as SVG patterns: Chromium prints patterns as bitmaps. Each hatch is a set
    // of line families on a lattice of pitch P (about 1.6 mm on paper) and dots; "2" halves the pitch.
    const HATCHES = [
        ["d1"], ["d2"], ["h"], ["v"], ["dots"], ["d1", "d2"], ["h", "v"], ["dots2"],
        ["d1/2"], ["d2/2"], ["h/2"], ["v/2"], ["bigdots"], ["rings"], ["d1", "h"], ["d2", "v"],
    ];
    const r2 = (v) => Math.round(v * 100) / 100;
    const STRIPED = new Set(["reserved", "deprecated"]);  // prefix statuses drawn with stripes
    // Path data of one line family or dot lattice inside the rectangle (x0, y0)-(x1, y1); the lattice is anchored at 0,
    // so neighbouring rectangles of one tenant continue each other
    function hatchPart(kind, x0, y0, x1, y1, P) {
        const [name, half] = kind.split("/");
        const p = half ? P / 2 : P;
        const d = [];
        if (name === "h" || name === "v") {
            const [a0, a1, b0, b1] = name === "h" ? [y0, y1, x0, x1] : [x0, x1, y0, y1];
            for (let a = Math.ceil((a0 - p / 2) / p) * p + p / 2; a < a1; a += p) {
                if (a <= a0) continue;
                d.push(name === "h" ? `M${r2(b0)} ${r2(a)}H${r2(b1)}` : `M${r2(a)} ${r2(b0)}V${r2(b1)}`);
            }
        } else if (name === "d1") {  // x + y = c
            for (let c = Math.ceil((x0 + y0) / p) * p; c < x1 + y1; c += p) {
                const xa = Math.max(x0, c - y1), xb = Math.min(x1, c - y0);
                if (xb > xa) d.push(`M${r2(xa)} ${r2(c - xa)}L${r2(xb)} ${r2(c - xb)}`);
            }
        } else if (name === "d2") {  // x - y = c
            for (let c = Math.ceil((x0 - y1) / p) * p; c < x1 - y0; c += p) {
                const xa = Math.max(x0, y0 + c), xb = Math.min(x1, y1 + c);
                if (xb > xa) d.push(`M${r2(xa)} ${r2(xa - c)}L${r2(xb)} ${r2(xb - c)}`);
            }
        } else {
            const q = name === "dots2" ? P / 2 : P;
            const r = { dots: 0.12, dots2: 0.08, bigdots: 0.24, rings: 0.26 }[name] * P;
            for (let cy = Math.ceil((y0 - q / 2) / q) * q + q / 2; cy < y1; cy += q) {
                for (let cx = Math.ceil((x0 - q / 2) / q) * q + q / 2; cx < x1; cx += q) {
                    if (cx - r < x0 || cy - r < y0 || cx + r > x1 || cy + r > y1) continue;
                    d.push(`M${r2(cx - r)} ${r2(cy)}a${r2(r)} ${r2(r)} 0 1 0 ${r2(2 * r)} 0a${r2(r)} ${r2(r)} 0 1 0 ${r2(-2 * r)} 0`);
                }
            }
        }
        return d.join("");
    }
    // Checkerboard of squares of side s anchored at 0, clipped to the rectangle; a path, not a pattern, for the same reason
    function checkerPath(x0, y0, x1, y1, s) {
        const d = [];
        for (let b = Math.floor(y0 / s); b * s < y1; b++) {
            for (let a = Math.floor(x0 / s); a * s < x1; a++) {
                if ((a + b) % 2) continue;
                const xa = Math.max(x0, a * s), xb = Math.min(x1, (a + 1) * s), ya = Math.max(y0, b * s), yb = Math.min(y1, (b + 1) * s);
                if (xb > xa && yb > ya) d.push(`M${r2(xa)} ${r2(ya)}h${r2(xb - xa)}v${r2(yb - ya)}h${r2(xa - xb)}z`);
            }
        }
        return d.join("");
    }
    // SVG of hatch number n over the rectangle: lines are stroked, dots filled, rings stroked
    // A rectangle too small for the pitch gets a finer one, so that a small prefix is not left looking untenanted.
    function hatchSvg(n, x, y, w, h, P) {
        let svg = "";
        for (let p = P; !svg && p >= Math.min(w, h) / 8; p /= 2) svg = hatchAt(n, x, y, w, h, p);
        return svg;
    }
    function hatchAt(n, x, y, w, h, P) {
        return HATCHES[n].map((kind) => {
            const d = hatchPart(kind, x, y, x + w, y + h, P);
            if (!d) return "";
            if (kind === "dots" || kind === "dots2" || kind === "bigdots") return `<path class="hatch-${n}" d="${d}" fill="#000"/>`;
            const sw = kind === "rings" ? 0.09 * P : kind.endsWith("/2") ? 0.07 * P : 0.1 * P;
            return `<path class="hatch-${n}" d="${d}" fill="none" stroke="#000" stroke-width="${r2(sw)}"/>`;
        }).join("");
    }
    let ctx = null;

    function init(context) { ctx = context; }

    // Usage darkness of a layered-map block; mirrors layer_usage_alpha() in app/plot_map.py
    const layerAlpha = (count, size) => (count ? 0.25 + 0.65 * Math.sqrt(Math.min(1, count / size)) : 0);

    function build({ mono = false } = {}) {
        if (!ctx || !ctx.GW) return null;
        const { cfg, data, net, GW, GH, layer, blockLen, blockSize, cellOf, rangeBounds, intToIp } = ctx;
        const W = GW * U, H = GH * U;
        const vrfName = cfg.vrf ? cfg.vrf.name : "Global";
        const title = [`${cfg.prefix}`, `VRF ${vrfName}`, cfg.details.description].filter(Boolean).join(" · ");
        const sub = [ctx.usageText(), layer ? `1 cell = /${blockLen}` : "1 cell = 1 address",
            data.generated_at ? `data of ${new Date(data.generated_at * 1000).toLocaleString()}` : null].filter(Boolean).join(" · ");
        // Font size follows the map width; a drawing wider than the map holds the title and subtitle of small maps
        const fs = Math.max(11, Math.round(W / 55));
        const SW = Math.ceil(Math.max(W, title.length * fs * 0.62 * 1.3, sub.length * fs * 0.6));
        const defs = [];
        const body = [];
        const box = (start, end) => { const [x1, y1, x2, y2] = rangeBounds(start, end); return [x1 * U, y1 * U, (x2 - x1 + 1) * U, (y2 - y1 + 1) * U]; };

        // Tenant fills: color, or one hatch per tenant in black and white
        const tenantFill = new Map();  // colour, or hatch number in black and white
        const tenantLook = new Map();  // equal looks are named in the legend
        const tenantOrder = [];
        // Hatch pitch: about 1.6 mm with the drawing printed 190 mm wide (A4 portrait). A pitch close to the cell size
        // would read as the cell grid.
        const P = (1.6 * SW) / 190;
        const fillOf = (p) => {
            if (!p.tenant || !p.color) return null;
            const key = String(p.tenant);
            if (!tenantFill.has(key)) {
                tenantOrder.push(key);
                if (mono) {
                    tenantLook.set(key, tenantFill.size % HATCHES.length);
                    tenantFill.set(key, tenantFill.size % HATCHES.length);
                } else {
                    tenantLook.set(key, p.color);
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
            const hatched = mono && fill !== null;
            body.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${hatched ? "#fff" : fill || "none"}" stroke="#000" stroke-width="${U / 16}" stroke-dasharray="${U / 5} ${U / 5}"><title>${esc(n.p.prefix)}</title></rect>`);
            if (hatched) body.push(hatchSvg(fill, x, y, w, h, P));
            // Reserved and deprecated prefixes: diagonal stripes every two cells, as on the PNG
            if (STRIPED.has(n.p.status)) body.push(`<path class="striped" d="${hatchPart("d2", x, y, x + w, y + h, 2 * U)}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="${U / 10}"/>`);
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
            for (const [first, color] of partial) {
                const c = mono ? "#999" : color || "#b0b0b0";
                const [x, y] = cellOf(first);
                const x0 = x * U + GAP, y0 = y * U + GAP;
                if (!checks.has(c)) checks.set(c, []);
                checks.get(c).push(`<rect x="${x0}" y="${y0}" width="${BODY}" height="${BODY}"/>`, `<path d="${checkerPath(x0, y0, x0 + BODY, y0 + BODY, U / 8)}" fill="${c}"/>`);
            }
            for (const items of checks.values()) body.push(`<g fill="#fff">${items.join("")}</g>`);
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
            // IP ranges: a dot in the middle of each address cell, under the IP cells
            const dots = [], D = BODY / 3;
            for (const { start, end } of ctx.ranges || []) {
                for (let a = Math.max(start, net.start); a <= Math.min(end, net.end); a++) {
                    if (ctx.ipsByAddr.has(a)) continue;  // drawn as an IP cell
                    const [x, y] = cellOf(a);
                    dots.push(`<rect x="${x * U + GAP + D}" y="${y * U + GAP + D}" width="${D}" height="${D}"/>`);
                }
            }
            if (dots.length) body.push(`<g fill="#555">${dots.join("")}</g>`);
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
            if ((ctx.ranges || []).length) items.push({ fill: "#fff", opacity: 1, dot: true, label: "IP range" });
        }
        if (ctx.nested.some((n) => STRIPED.has(n.p.status) && !(layer && n.len > blockLen))) items.push({ fill: "#fff", opacity: 1, striped: true, label: "Reserved, deprecated prefix" });
        const sameAs = (key) => {
            const same = tenantOrder.filter((o) => o !== key && tenantLook.get(o) === tenantLook.get(key)).map(ctx.tenantName);
            return same.length ? ` (same ${mono ? "pattern" : "colour"} as ${same.join(", ")})` : "";
        };
        const tenantItems = tenantOrder.map((key) => ({ ...(mono ? { fill: "#fff", hatch: tenantFill.get(key) } : { fill: tenantFill.get(key) }),
            opacity: 1, label: ctx.tenantName(key) + sameAs(key), name: ctx.tenantName(key), outline: true }))
            .sort((a, b) => a.name.localeCompare(b.name));
        const rows = [];
        let row = [], used = 0;
        const sw = fs, itemW = (it) => sw + fs * 0.5 + it.label.length * fs * 0.62 + fs * 1.6;
        for (const it of [...items, ...(tenantItems.length ? [{ label: "Tenants:", heading: true }] : []), ...tenantItems]) {
            const w = it.heading ? it.label.length * fs * 0.62 + fs : itemW(it);
            if (used + w > SW && row.length) { rows.push(row); row = []; used = 0; }
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
                ? `<rect x="${it.x}" y="${y}" width="${sw}" height="${sw}" fill="#fff" stroke="#999" stroke-width="${fs / 12}"/><path d="${checkerPath(it.x, y, it.x + sw, y + sw, sw / 8)}" fill="#999"/>`
                : `<rect x="${it.x}" y="${y}" width="${sw}" height="${sw}" fill="${it.fill}" fill-opacity="${it.opacity}" stroke="#999" stroke-width="${fs / 12}"/>`
                    + (it.hatch !== undefined ? hatchSvg(it.hatch, it.x, y, sw, sw, P) : "")
                    + (it.striped ? `<path d="${hatchPart("d2", it.x, y, it.x + sw, y + sw, sw / 3)}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="${fs / 12}"/>` : "")
                    + (it.hollow ? `<rect x="${it.x + sw / 3}" y="${y + sw / 3}" width="${sw / 3}" height="${sw / 3}" fill="#fff"/>` : "")
                    + (it.dot ? `<rect x="${it.x + sw / 3}" y="${y + sw / 3}" width="${sw / 3}" height="${sw / 3}" fill="#555"/>` : "");
            return swatch + text;
        }));
        const totalH = legendY + rows.length * fs * 1.7 + pad / 2;

        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SW} ${Math.ceil(totalH)}" width="${SW}" height="${Math.ceil(totalH)}" shape-rendering="crispEdges">`
            + `<title>${esc(title)}</title><defs>${defs.join("")}</defs>`
            + `<rect width="${SW}" height="${Math.ceil(totalH)}" fill="#fff"/>`
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
