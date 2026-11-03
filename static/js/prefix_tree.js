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
        list.replaceChildren(...prefixes.map((child) => renderNode(child.vrf ?? vrf, child.prefix, child.has_children)));
    }

    function renderNode(vrf, prefix, hasChildren, preloaded) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = mapUrl(vrf, prefix);
        link.textContent = prefix;
        if (prefix === current) link.className = "current";

        if (!hasChildren) {
            item.append(link);
            return item;
        }

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "tree-toggle";
        const list = document.createElement("ul");
        let loaded = false;

        function setOpen(open) {
            toggle.textContent = open ? "−" : "+";
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
        item.append(toggle, link, list);
        return item;
    }

    fetchNav(container.dataset.vrf === "None" ? null : container.dataset.vrf, current)
        .then((data) => {
            const root = document.createElement("ul");
            root.append(renderNode(data.vrf, data.prefix, data.child_prefixes.length > 0, data.child_prefixes));
            container.replaceChildren(root);
        })
        .catch((error) => {
            container.textContent = `Failed to load prefix tree: ${error.message}`;
        });
})();
