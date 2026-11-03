(() => {
    const container = document.getElementById("prefix-tree");
    if (!container || !container.dataset.prefix) return;

    const sanitize = (prefix) => prefix.replace(/[./]/g, "_");
    const vrfKey = (vrf) => (vrf === null || vrf === undefined ? "None" : String(vrf));
    const mapUrl = (vrf, prefix) => `${BASE_PATH}/map/${vrfKey(vrf)}/${sanitize(prefix)}`;
    const navUrl = (vrf, prefix) => `${BASE_PATH}/data/${vrfKey(vrf)}/${sanitize(prefix)}?nav=1`;
    const current = container.dataset.prefix;

    function fetchNav(vrf, prefix) {
        return fetch(navUrl(vrf, prefix)).then((response) => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        });
    }

    function renderChildren(list, vrf, prefixes) {
        list.replaceChildren(...prefixes.map((child) => renderNode({ ...child, vrf: child.vrf ?? vrf })));
    }

    function usageBar(node) {
        const bar = document.createElement("span");
        bar.className = "tree-usage";
        if (node.size) {
            const fill = document.createElement("span");
            const ratio = Math.min(1, (node.ip_count || 0) / node.size);
            fill.style.width = `${(ratio * 100).toFixed(1)}%`;
            bar.append(fill);
            bar.title = `${node.ip_count || 0} of ${node.size} addresses`;
        }
        return bar;
    }

    function renderNode(node, preloaded) {
        const { vrf, prefix } = node;
        const item = document.createElement("li");
        const row = document.createElement("div");
        row.className = prefix === current ? "tree-row current" : "tree-row";
        const dot = document.createElement("span");
        dot.className = "tree-dot";
        if (node.color) dot.style.background = node.color;
        const link = document.createElement("a");
        link.href = mapUrl(vrf, prefix);
        link.textContent = prefix;
        if (node.description) link.title = node.description;
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "tree-toggle";
        row.append(toggle, dot, link, usageBar(node));
        item.append(row);

        if (!node.has_children) {
            toggle.disabled = true;
            return item;
        }

        const list = document.createElement("ul");
        let loaded = false;

        function setOpen(open) {
            toggle.textContent = open ? "▾" : "▸";
            toggle.setAttribute("aria-expanded", String(open));
            list.hidden = !open;
        }

        toggle.addEventListener("click", () => {
            const open = list.hidden;
            setOpen(open);
            if (!open || loaded) return;
            loaded = true;
            list.replaceChildren(Object.assign(document.createElement("li"), { textContent: "Loading…" }));
            fetchNav(vrf, prefix)
                .then((data) => renderChildren(list, vrf, data.child_prefixes))
                .catch((error) => {
                    loaded = false;
                    list.replaceChildren(Object.assign(document.createElement("li"), { textContent: `Failed: ${error.message}` }));
                });
        });

        if (preloaded) {
            loaded = true;
            renderChildren(list, vrf, preloaded);
            setOpen(true);
        } else {
            setOpen(false);
        }
        item.append(list);
        return item;
    }

    fetchNav(container.dataset.vrf === "None" ? null : container.dataset.vrf, current)
        .then((data) => {
            const root = document.createElement("ul");
            const children = data.child_prefixes || [];
            root.append(renderNode({ ...data, has_children: children.length > 0 }, children));
            container.replaceChildren(root);
        })
        .catch((error) => {
            container.textContent = `Failed to load prefix tree: ${error.message}`;
        });
})();
