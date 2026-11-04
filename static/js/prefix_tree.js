(() => {
    "use strict";
    const container = document.getElementById("tree");
    const cfgNode = document.getElementById("page-config");
    if (!container || !cfgNode) return;
    const cfg = JSON.parse(cfgNode.textContent);

    const vrfKey = (vrf) => (vrf === null || vrf === undefined ? "None" : String(vrf));
    const sanitize = (prefix) => prefix.replace(/[./]/g, "_");
    const mapUrl = (vrf, prefix) => `${cfg.basePath}/map/${vrfKey(vrf)}/${sanitize(prefix)}`;
    const navUrl = (vrf, prefix) => `${cfg.basePath}/data/${vrfKey(vrf)}/${sanitize(prefix)}?nav=1`;
    const { t, fmt } = window.I18N;
    const pct = (u, total) => { const v = Math.min(100, (100 * u) / total); return v === 0 ? "0%" : v < 1 ? "<1%" : `${Math.round(v)}%`; };
    const tenantName = (id) => (id ? cfg.names.tenants[String(id)] || t("insp.tenant_n", { id }) : null);
    const statusLabel = (s) => (s && window.I18N.has(`status.${s}`) ? t(`status.${s}`) : s);
    const rows = new Map();

    function fetchNav(vrf, prefix) {
        return fetch(navUrl(vrf, prefix)).then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        });
    }

    function message(text) {
        const li = document.createElement("li");
        li.className = "msg";
        li.textContent = text;
        return li;
    }

    function chevron() {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("width", "8");
        svg.setAttribute("height", "8");
        svg.setAttribute("viewBox", "0 0 8 8");
        const path = document.createElementNS(ns, "path");
        path.setAttribute("d", "M2.5 1l3 3-3 3");
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "currentColor");
        path.setAttribute("stroke-width", "1.4");
        svg.append(path);
        return svg;
    }

    function usage(node) {
        const bar = document.createElement("span");
        bar.className = "usage";
        const label = document.createElement("span");
        label.className = "pct";
        if (!node.size || node.ip_count === undefined || node.ip_count === null) {
            bar.classList.add("na");
            bar.title = t("usage.no_data");
            return [bar, label];
        }
        const ratio = Math.min(1, node.ip_count / node.size);
        if (ratio > 0.8) bar.classList.add("hot");
        const fill = document.createElement("i");
        fill.style.width = `${Math.max(ratio > 0 ? 6 : 0, ratio * 100).toFixed(1)}%`;
        bar.append(fill);
        bar.title = t("usage.of_addresses", { used: fmt(node.ip_count), n: node.size });
        label.textContent = pct(node.ip_count, node.size);
        return [bar, label];
    }

    function renderNode(node, preloaded) {
        const { vrf, prefix } = node;
        const item = document.createElement("li");
        const row = document.createElement("div");
        row.className = prefix === cfg.prefix ? "row current" : "row";
        row.setAttribute("role", "treeitem");
        row.dataset.prefix = prefix;
        row.title = [prefix, node.description, tenantName(node.tenant), statusLabel(node.status)].filter(Boolean).join(" · ");

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "tog";
        toggle.append(chevron());
        const dot = document.createElement("span");
        dot.className = node.color ? "tdot" : "tdot none";
        if (node.color) dot.style.background = node.color;
        const link = document.createElement("a");
        link.className = "pfx";
        link.href = mapUrl(vrf, prefix);
        link.textContent = prefix;
        if (prefix === cfg.prefix) link.setAttribute("aria-current", "page");
        row.append(toggle, dot, link, ...usage(node));
        row.addEventListener("mouseenter", () => document.dispatchEvent(new CustomEvent("prefixtree:hover", { detail: { prefix } })));
        row.addEventListener("mouseleave", () => document.dispatchEvent(new CustomEvent("prefixtree:hover", { detail: { prefix: null } })));
        item.append(row);
        if (!rows.has(prefix)) rows.set(prefix, row);

        if (!node.has_children) {
            toggle.classList.add("leaf");
            toggle.tabIndex = -1;
            return item;
        }
        toggle.setAttribute("aria-label", t("tree.expand", { prefix }));
        const list = document.createElement("ul");
        list.setAttribute("role", "group");
        let loaded = false;
        const setOpen = (open) => {
            toggle.setAttribute("aria-expanded", String(open));
            list.hidden = !open;
        };
        toggle.addEventListener("click", () => {
            const open = list.hidden;
            setOpen(open);
            if (!open || loaded) return;
            loaded = true;
            list.replaceChildren(message(t("common.loading")));
            fetchNav(vrf, prefix)
                .then((data) => renderChildren(list, vrf, data.child_prefixes || []))
                .catch((error) => {
                    loaded = false;
                    list.replaceChildren(message(t("tree.failed", { error: error.message })));
                });
        });
        if (preloaded) {
            loaded = true;
            list.append(...preloaded);
            setOpen(true);
        } else {
            setOpen(false);
        }
        item.append(list);
        return item;
    }

    function renderChildren(list, vrf, prefixes, expand) {
        list.replaceChildren(...prefixes.map((child) => {
            const node = { ...child, vrf: child.vrf ?? vrf };
            return expand && expand.prefix === child.prefix ? expand.render(node) : renderNode(node);
        }));
    }

    // The path from the outermost parent to this prefix is expanded, other branches load on expand
    const path = [...cfg.parents.map((p) => p.prefix), cfg.prefix];
    const vrf = cfg.vrfKey === "None" ? null : cfg.vrfKey;
    Promise.allSettled(path.map((p) => fetchNav(vrf, p))).then((results) => {
        if (results.at(-1).status !== "fulfilled") throw results.at(-1).reason;
        // An ancestor without data starts the tree below it
        let first = 0;
        for (let i = results.length - 1; i >= 0; i--) if (results[i].status !== "fulfilled") { first = i + 1; break; }
        let expand = null;
        for (let i = results.length - 1; i >= first; i--) {
            const data = results[i].value;
            const children = data.child_prefixes || [];
            const inner = expand;
            const render = (node) => {
                const list = document.createElement("ul");
                renderChildren(list, node.vrf, children, inner);
                return renderNode({ ...data, ...node, has_children: children.length > 0 }, [...list.children]);
            };
            expand = { prefix: data.prefix, render };
        }
        const root = document.createElement("ul");
        root.setAttribute("role", "group");
        const top = results[first].value;
        root.append(expand.render({ ...top, vrf: top.vrf ?? vrf }));
        container.replaceChildren(root);
        const current = rows.get(cfg.prefix);
        if (current) current.scrollIntoView({ block: "center" });
    }).catch((error) => {
        container.replaceChildren(message(t("tree.load_failed", { error: error.message })));
    });

    let traced = null;
    document.addEventListener("prefixmap:focus", (ev) => {
        if (traced) traced.classList.remove("trace");
        traced = ev.detail.prefix ? rows.get(ev.detail.prefix) || null : null;
        if (traced) traced.classList.add("trace");
    });
})();
