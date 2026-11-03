(() => {
    const view = document.getElementById("map-view");
    if (!view) return;

    const img = document.getElementById("map-image");
    const stage = document.getElementById("map-stage");
    const tooltip = document.getElementById("map-tooltip");
    const zoomLabel = document.getElementById("zoom-level");
    const cellBox = document.getElementById("hover-cell");
    const prefixBox = document.getElementById("hover-prefix");
    const netboxUrl = view.dataset.netboxUrl;
    const names = JSON.parse(document.getElementById("map-names").textContent);

    const ipToInt = (ip) => ip.split(".").reduce((acc, octet) => acc * 256 + Number(octet), 0);
    const intToIp = (n) => [24, 16, 8, 0].map((shift) => Math.floor(n / 2 ** shift) % 256).join(".");
    const sanitize = (prefix) => prefix.replace(/[./]/g, "_");
    const mapUrl = (vrf, prefix) => `${BASE_PATH}/map/${vrf ?? "None"}/${sanitize(prefix)}`;

    function parsePrefix(prefix) {
        const [address, length] = prefix.split("/");
        const len = Number(length);
        const start = ipToInt(address);
        return { start, end: start + 2 ** (32 - len) - 1, len };
    }

    // Morton (Z-order) layout; a 2:1 grid is two squares, the second half of the range on the right
    let data = null;
    let net = null;

    function interleave(x, y) {
        let offset = 0;
        for (let bit = 0; bit < 16; bit++) {
            offset += (((x >> bit) & 1) * 2 ** (2 * bit)) + (((y >> bit) & 1) * 2 ** (2 * bit + 1));
        }
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
        const [width, height] = data.grid;
        if (width === 2 * height && x >= height) return height * height + interleave(x - height, y);
        return interleave(x, y);
    }

    function offsetToCell(offset) {
        const [width, height] = data.grid;
        if (width === 2 * height && offset >= height * height) {
            const [x, y] = deinterleave(offset - height * height);
            return [x + height, y];
        }
        return deinterleave(offset);
    }

    function prefixBounds(p) {
        const [x1, y1] = offsetToCell(p.start - net.start);
        const [x2, y2] = offsetToCell(p.end - net.start);
        return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
    }

    // Zoom in whole device pixels per image pixel, so cells never get resampled
    let scale = 1;
    let userZoomed = false;

    function fitScale() {
        const available = (view.clientWidth - 2) * window.devicePixelRatio;
        return Math.max(1, Math.floor(available / img.naturalWidth));
    }

    function applyScale() {
        const dpr = window.devicePixelRatio;
        img.style.width = `${(img.naturalWidth * scale) / dpr}px`;
        img.style.height = `${(img.naturalHeight * scale) / dpr}px`;
        zoomLabel.textContent = `${scale}×`;
        hideHover();
    }

    function setScale(value, byUser) {
        scale = Math.max(1, Math.min(16, value));
        userZoomed = byUser;
        applyScale();
    }

    document.getElementById("zoom-in").addEventListener("click", () => setScale(scale + 1, true));
    document.getElementById("zoom-out").addEventListener("click", () => setScale(scale - 1, true));
    document.getElementById("zoom-fit").addEventListener("click", () => setScale(fitScale(), false));
    window.addEventListener("resize", () => { if (!userZoomed) setScale(fitScale(), false); });

    // Lookup tables
    let ipsByAddress = new Map();
    let nested = [];
    let children = [];

    function innermost(list, address) {
        let best = null;
        for (const p of list) {
            if (address >= p.start && address <= p.end && (!best || p.len > best.len)) best = p;
        }
        return best;
    }

    function tenantName(id) {
        return id ? (names.tenants[String(id)] || `Tenant ${id}`) : null;
    }

    function hitTest(event) {
        const rect = img.getBoundingClientRect();
        const px = ((event.clientX - rect.left) * img.naturalWidth) / rect.width;
        const py = ((event.clientY - rect.top) * img.naturalHeight) / rect.height;
        const x = Math.floor(px / data.cell_size);
        const y = Math.floor(py / data.cell_size);
        if (x < 0 || y < 0 || x >= data.grid[0] || y >= data.grid[1]) return null;
        const address = net.start + cellToOffset(x, y);
        return {
            x, y, address,
            ip: ipsByAddress.get(address),
            prefix: innermost(nested, address),
            child: innermost(children, address),
        };
    }

    function placeBox(box, x1, y1, x2, y2) {
        const k = img.getBoundingClientRect().width / img.naturalWidth;
        const cs = data.cell_size;
        box.style.left = `${x1 * cs * k}px`;
        box.style.top = `${y1 * cs * k}px`;
        box.style.width = `${(x2 - x1 + 1) * cs * k}px`;
        box.style.height = `${(y2 - y1 + 1) * cs * k}px`;
        box.hidden = false;
    }

    function line(text, className) {
        const div = document.createElement("div");
        div.textContent = text;
        if (className) div.className = className;
        return div;
    }

    function showTooltip(hit, event) {
        tooltip.replaceChildren();
        const address = intToIp(hit.address);
        if (hit.ip) {
            const flags = [hit.ip.status, hit.ip.role].filter(Boolean).join(", ");
            tooltip.append(line(flags ? `${address}  ${flags}` : address, "tt-title"));
            if (hit.ip.dns_name) tooltip.append(line(hit.ip.dns_name));
            if (hit.ip.description) tooltip.append(line(hit.ip.description));
            if (hit.ip.tenant) tooltip.append(line(`Tenant: ${tenantName(hit.ip.tenant)}`));
        } else {
            tooltip.append(line(`${address}  free`, "tt-title"));
        }
        if (hit.prefix) {
            const details = [tenantName(hit.prefix.p.tenant), hit.prefix.p.description].filter(Boolean).join(", ");
            tooltip.append(line(details ? `${hit.prefix.p.prefix}: ${details}` : hit.prefix.p.prefix, "tt-prefix"));
        }
        const action = clickAction(hit);
        if (action) tooltip.append(line(action.label, "tt-hint"));
        tooltip.hidden = false;
        const margin = 14;
        const { innerWidth, innerHeight } = window;
        const box = tooltip.getBoundingClientRect();
        let left = event.clientX + margin;
        let top = event.clientY + margin;
        if (left + box.width > innerWidth) left = event.clientX - box.width - margin;
        if (top + box.height > innerHeight) top = event.clientY - box.height - margin;
        tooltip.style.left = `${Math.max(0, left)}px`;
        tooltip.style.top = `${Math.max(0, top)}px`;
    }

    function clickAction(hit) {
        if (hit.child) {
            return { label: `Click: open ${hit.child.p.prefix}`, url: mapUrl(hit.child.p.vrf, hit.child.p.prefix) };
        }
        if (hit.ip) {
            return { label: "Click: open in NetBox", url: `${netboxUrl}/ipam/ip-addresses/${hit.ip.id}/`, external: true };
        }
        return null;
    }

    function hideHover() {
        tooltip.hidden = true;
        cellBox.hidden = true;
        prefixBox.hidden = true;
    }

    stage.addEventListener("mousemove", (event) => {
        if (!data) return;
        const hit = hitTest(event);
        if (!hit) { hideHover(); return; }
        placeBox(cellBox, hit.x, hit.y, hit.x, hit.y);
        if (hit.prefix) placeBox(prefixBox, ...prefixBounds(hit.prefix)); else prefixBox.hidden = true;
        stage.style.cursor = clickAction(hit) ? "pointer" : "default";
        showTooltip(hit, event);
    });
    stage.addEventListener("mouseleave", hideHover);
    stage.addEventListener("click", (event) => {
        if (!data) return;
        const hit = hitTest(event);
        const action = hit && clickAction(hit);
        if (!action) return;
        if (action.external || event.ctrlKey || event.metaKey) window.open(action.url, "_blank", "noopener");
        else window.location.href = action.url;
    });

    function swatch(color, alpha) {
        const span = document.createElement("span");
        span.className = "swatch";
        span.style.background = color;
        if (alpha !== undefined) span.style.opacity = alpha;
        return span;
    }

    function renderLegend() {
        const legend = document.getElementById("map-legend");
        const items = [
            [swatch("#000"), "In use"],
            [swatch("#000", 0.25), "Reserved"],
            [swatch("#ff0000"), "With role"],
        ];
        const tenants = new Map();
        for (const p of data.nested_prefixes) {
            if (p.tenant && p.color && !tenants.has(p.tenant)) tenants.set(p.tenant, p.color);
        }
        [...tenants.entries()]
            .sort((a, b) => tenantName(a[0]).localeCompare(tenantName(b[0])))
            .forEach(([id, color]) => items.push([swatch(color), tenantName(id)]));
        legend.replaceChildren(...items.map(([mark, text]) => {
            const item = document.createElement("span");
            item.className = "legend-item";
            item.append(mark, document.createTextNode(text));
            return item;
        }));

        const total = net.end - net.start + 1;
        const used = data.ip_addresses.length;
        const percent = ((100 * used) / total).toFixed(used && used < total / 1000 ? 2 : 1);
        document.getElementById("map-usage").textContent = `${used} of ${total} addresses (${percent}%)`;
        if (data.generated_at) {
            document.getElementById("map-updated").textContent =
                `Updated ${new Date(data.generated_at * 1000).toLocaleString()}`;
        }
    }

    function init(loaded) {
        data = loaded;
        net = parsePrefix(data.prefix);
        ipsByAddress = new Map(data.ip_addresses.map((ip) => [ipToInt(ip.address.split("/")[0]), ip]));
        nested = data.nested_prefixes.map((p) => ({ ...parsePrefix(p.prefix), p }));
        children = data.child_prefixes.map((p) => ({ ...parsePrefix(p.prefix), p }));
        renderLegend();
    }

    const imageReady = img.complete ? Promise.resolve() : new Promise((resolve) => img.addEventListener("load", resolve));
    imageReady.then(() => setScale(fitScale(), false));
    fetch(view.dataset.dataUrl)
        .then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(init)
        .catch((error) => {
            document.getElementById("map-usage").textContent = `Map data unavailable: ${error.message}`;
        });
})();
