window.PrefixMapTop = (() => {
    const fresh = document.getElementById("fresh");
    const freshText = document.getElementById("fresh-text");
    const search = document.getElementById("search");
    const msg = document.getElementById("search-msg");
    const STALE_SECONDS = 24 * 3600;
    let generatedAt = fresh && Number(fresh.dataset.generatedAt) || null;
    let health = null;
    let healthError = null;
    let searchHandler = null;

    function formatTime(seconds) {
        const t = new Date(seconds * 1000);
        const sameDay = t.toDateString() === new Date().toDateString();
        return sameDay
            ? t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : t.toLocaleDateString([], { month: "short", day: "numeric" });
    }

    function renderFresh() {
        if (!fresh) return;
        const last = (health && health.last_success_at) || generatedAt;
        const age = last ? Date.now() / 1000 - last : null;
        const problems = [];
        if (healthError) problems.push(`Health check failed: ${healthError}.`);
        if (health && health.status !== "ok") problems.push(`Updater: ${health.status}.`);
        if (health && health.last_error) problems.push(`Last update failed: ${health.last_error}`);
        if (age !== null && age > STALE_SECONDS) problems.push("Data is older than 24 h.");
        fresh.classList.toggle("stale", problems.length > 0);
        fresh.classList.toggle("ok", problems.length === 0 && last !== null);
        let text = last ? `updated ${formatTime(last)}` : "no update yet";
        if (health && health.update_running) text = "updating…";
        freshText.textContent = text;
        const lines = [];
        if (last) lines.push(`Data generated ${new Date(last * 1000).toLocaleString()}.`);
        lines.push(...problems);
        if (!problems.length && last) lines.push("Updates run on NetBox webhooks.");
        fresh.title = lines.join("\n");
    }

    function pollHealth() {
        if (!fresh) return;
        fetch(fresh.dataset.healthUrl, { cache: "no-store" })
            .then((r) => r.json())
            .then((body) => { health = body; healthError = null; })
            .catch((error) => { health = null; healthError = error.message; })
            .finally(renderFresh);
    }

    function say(content) {
        if (content === null) { msg.hidden = true; return; }
        msg.replaceChildren(...[].concat(content));
        msg.hidden = false;
    }

    const QUERY = /^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/;
    // Mirrors ADDRESS_LIKE in app/webapp.py: digits and dots, or IPv6, are meant as an address
    const ADDRESS_LIKE = /^[\d./]+$|^[0-9a-fA-F]*:[0-9a-fA-F:./]*$/;
    let searchSeq = 0;
    let searchTimer = null;

    function node(tag, className, text) {
        const e = document.createElement(tag);
        if (className) e.className = className;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    function resultItem(r) {
        const li = node("li");
        const link = node("a", "mono", r.kind === "ip" ? r.address : r.prefix);
        link.href = r.url;
        if (r.kind === "free") {
            li.append(node("span", "chip", r.vrf_name), link, node("span", "desc", ` free · in ${r.in}`));
            return li;
        }
        if (r.kind === "ip") {
            li.append(node("span", "chip", r.vrf_name), link, node("span", "desc", ` in ${r.prefix}`));
            li.append(node("div", "ip", [r.ip.dns_name, r.ip.description].filter(Boolean).join(" · ")));
            return li;
        }
        const details = [r.match === "exact" ? "" : "contains it", r.description].filter(Boolean).join(" · ");
        li.append(node("span", "chip", r.vrf_name), link);
        if (details) li.append(node("span", "desc", ` ${details}`));
        if (r.ip !== undefined) {
            const ip = r.ip;
            li.append(node("div", "ip", ip ? [ip.status, ip.role, ip.dns_name].filter(Boolean).join(" · ") || "IP record" : "no IP record"));
        }
        return li;
    }

    function serverSearch(q, commit, ui) {
        const seq = ++searchSeq;
        const vrf = search.dataset.vrf ? `&vrf=${encodeURIComponent(search.dataset.vrf)}` : "";
        fetch(`${search.dataset.searchUrl}?q=${encodeURIComponent(q)}${vrf}`)
            .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
            .then(({ ok, body }) => {
                if (seq !== searchSeq) return;
                if (!ok) { ui.bad(); say(body.error || "Search failed."); return; }
                if (!body.results.length) {
                    say(body.free ? `${q}: no free block of that size.` : body.text ? `${q}: no names or descriptions match.` : `${q}: no prefix contains it.`);
                    return;
                }
                if (commit) { window.location.href = body.results[0].url; return; }
                const list = node("ul");
                list.append(...body.results.map(resultItem));
                const head = body.free
                    ? `Free: ${Object.entries(body.counts).map(([vrf, n]) => `${n.toLocaleString("en-US")} in ${vrf}`).join(", ")}. Enter opens the first:`
                    : body.truncated ? `First ${body.results.length} matches; Enter opens the first:` : "Enter opens the first map:";
                say([node("div", null, head), list]);
            })
            .catch((error) => { if (seq === searchSeq) say(`Search failed: ${error.message}`); });
    }

    function runSearch(commit) {
        search.classList.remove("bad");
        clearTimeout(searchTimer);
        searchSeq++;
        const q = search.value.trim();
        if (!q) { say(null); return; }
        const ui = { say, bad: () => search.classList.add("bad") };
        if (!QUERY.test(q)) {
            // Text: names and descriptions, searched on the server
            if (!ADDRESS_LIKE.test(q) && q.length >= 2) {
                if (commit) serverSearch(q, true, ui);
                else searchTimer = setTimeout(() => serverSearch(q, false, ui), 250);
                return;
            }
            if (commit || /^\d+\.\d+\.\d+\.\d+/.test(q)) {
                ui.bad();
                say("Enter an IPv4 address or prefix (10.20.0.1, 10.20.36.0/24), or a name or description");
            } else {
                say(null);
            }
            return;
        }
        if (searchHandler && searchHandler(q, commit, ui)) return;
        if (commit) serverSearch(q, true, ui);
        else searchTimer = setTimeout(() => serverSearch(q, false, ui), 150);
    }

    if (search) {
        search.addEventListener("input", () => runSearch(false));
        search.addEventListener("keydown", (e) => {
            if (e.key === "Enter") runSearch(true);
            else if (e.key === "Escape") { search.value = ""; say(null); search.classList.remove("bad"); search.blur(); }
        });
        search.addEventListener("blur", () => setTimeout(() => { msg.hidden = true; }, 200));
        search.addEventListener("focus", () => { if (search.value.trim()) runSearch(false); });
        // The / key gives "." on the Russian layout
        document.addEventListener("keydown", (e) => {
            if ((e.key === "/" || (e.code === "Slash" && e.key === ".")) && !(e.target instanceof HTMLInputElement) && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                search.focus();
            }
        });
    }

    pollHealth();
    setInterval(pollHealth, 60000);

    // Language switch: keep the current query (?focus=, ?tenant=), which the map updates after load
    document.querySelectorAll(".lang-switch a[data-lang]").forEach((a) => a.addEventListener("click", () => {
        const url = new URL(window.location.href);
        url.searchParams.set("lang", a.dataset.lang);
        a.href = url.href;
    }));

    return {
        setGeneratedAt(seconds) { generatedAt = seconds || null; renderFresh(); },
        setSearchHandler(fn) { searchHandler = fn; },
    };
})();
