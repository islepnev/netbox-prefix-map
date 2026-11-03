window.PrefixMapTop = (() => {
    const fresh = document.getElementById("fresh");
    const freshText = document.getElementById("fresh-text");
    const search = document.getElementById("search");
    const msg = document.getElementById("search-msg");
    const STALE_SECONDS = 24 * 3600;
    let generatedAt = null;
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

    function runSearch(commit) {
        search.classList.remove("bad");
        const q = search.value.trim();
        if (!q) { say(null); return; }
        if (searchHandler) searchHandler(q, commit, { say, bad: () => search.classList.add("bad") });
    }

    if (search) {
        search.addEventListener("input", () => runSearch(false));
        search.addEventListener("keydown", (e) => {
            if (e.key === "Enter") runSearch(true);
            else if (e.key === "Escape") { search.value = ""; say(null); search.classList.remove("bad"); search.blur(); }
        });
        search.addEventListener("blur", () => setTimeout(() => { msg.hidden = true; }, 200));
        search.addEventListener("focus", () => { if (search.value.trim()) runSearch(false); });
        document.addEventListener("keydown", (e) => {
            if (e.key === "/" && !(e.target instanceof HTMLInputElement) && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                search.focus();
            }
        });
    }

    pollHealth();
    setInterval(pollHealth, 60000);

    return {
        setGeneratedAt(seconds) { generatedAt = seconds || null; renderFresh(); },
        setSearchHandler(fn) { searchHandler = fn; },
    };
})();
