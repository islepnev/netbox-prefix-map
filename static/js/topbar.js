window.PrefixMapTop = (() => {
    const { t, fmt } = window.I18N;
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
        const d = new Date(seconds * 1000);
        const sameDay = d.toDateString() === new Date().toDateString();
        return sameDay
            ? window.I18N.time(d, { hour: "2-digit", minute: "2-digit" })
            : window.I18N.dateOnly(d, { month: "short", day: "numeric" });
    }

    function renderFresh() {
        if (!fresh) return;
        const last = (health && health.last_success_at) || generatedAt;
        const age = last ? Date.now() / 1000 - last : null;
        const problems = [];
        if (healthError) problems.push(t("fresh.health_failed", { error: healthError }));
        if (health && health.status !== "ok") problems.push(t("fresh.updater", { status: health.status }));
        if (health && health.last_error) problems.push(t("fresh.last_failed", { error: health.last_error }));
        if (age !== null && age > STALE_SECONDS) problems.push(t("fresh.stale"));
        fresh.classList.toggle("stale", problems.length > 0);
        fresh.classList.toggle("ok", problems.length === 0 && last !== null);
        let text = last ? t("fresh.updated", { time: formatTime(last) }) : t("fresh.none");
        if (health && health.update_running) text = t("fresh.running");
        freshText.textContent = text;
        const lines = [];
        if (last) lines.push(t("fresh.generated", { date: window.I18N.date(last * 1000) }));
        lines.push(...problems);
        if (!problems.length && last) lines.push(t("fresh.webhooks"));
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

    // vrf_name of the Global VRF is "Global" in the JSON, shown in the page language
    const vrfName = (r) => (r.vrf === "None" ? t("vrf.global") : r.vrf_name);
    const statusLabel = (s) => (s && window.I18N.has(`status.${s}`) ? t(`status.${s}`) : s);

    function resultItem(r) {
        const li = node("li");
        const link = node("a", "mono", r.kind === "ip" ? r.address : r.prefix);
        link.href = r.url;
        if (r.kind === "free") {
            li.append(node("span", "chip", vrfName(r)), link, node("span", "desc", ` ${t("search.free_in", { prefix: r.in })}`));
            return li;
        }
        if (r.kind === "ip") {
            li.append(node("span", "chip", vrfName(r)), link, node("span", "desc", ` ${t("search.in", { prefix: r.prefix })}`));
            li.append(node("div", "ip", [r.ip.dns_name, r.ip.description].filter(Boolean).join(" · ")));
            return li;
        }
        const details = [r.match === "exact" ? "" : t("search.contains_it"), r.description].filter(Boolean).join(" · ");
        li.append(node("span", "chip", vrfName(r)), link);
        if (details) li.append(node("span", "desc", ` ${details}`));
        if (r.ip !== undefined) {
            const ip = r.ip;
            li.append(node("div", "ip", ip ? [statusLabel(ip.status), ip.role, ip.dns_name].filter(Boolean).join(" · ") || t("search.ip_record") : t("search.no_ip_record")));
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
                if (!ok) { ui.bad(); say(body.error || t("search.failed")); return; }
                if (!body.results.length) {
                    say(t(body.free ? "search.no_free" : body.text ? "search.no_text" : "search.no_prefix", { q }));
                    return;
                }
                if (commit) { window.location.href = body.results[0].url; return; }
                const list = node("ul");
                list.append(...body.results.map(resultItem));
                const head = body.free
                    ? t("search.free_head", { counts: Object.entries(body.counts).map(([vrf, n]) => t("search.free_count", { n, vrf: vrf === "Global" ? t("vrf.global") : vrf })).join(", ") })
                    : body.truncated ? t("search.truncated", { n: body.results.length }) : t("search.enter_opens");
                say([node("div", null, head), list]);
            })
            .catch((error) => { if (seq === searchSeq) say(t("search.failed_error", { error: error.message })); });
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
                say(t("search.hint"));
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
