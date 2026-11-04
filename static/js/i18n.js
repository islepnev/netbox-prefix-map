// UI language: messages embedded by the server (#i18n), t(key, params), plurals and number formats.
// A message is a string with {name} placeholders, or plural forms (one, few, many, other) chosen by params.n.
// {n} is formatted with the language's digit grouping; other values are inserted as they are.
(function () {
    "use strict";
    const node = document.getElementById("i18n");
    const conf = node ? JSON.parse(node.textContent) : { lang: "en", messages: {} };
    const lang = conf.lang || "en";
    const messages = conf.messages || {};
    const plurals = new Intl.PluralRules(lang);
    const numbers = new Intl.NumberFormat(lang);

    const fmt = (n) => numbers.format(n);
    function t(key, params) {
        let msg = messages[key];
        if (msg === undefined) msg = key;
        if (msg && typeof msg === "object") {
            const n = params && typeof params.n === "number" ? params.n : 0;
            msg = msg[plurals.select(n)] ?? msg.other ?? msg.many ?? "";
        }
        if (!params) return msg;
        return msg.replace(/\{(\w+)\}/g, (m, name) => {
            if (!(name in params)) return m;
            const v = params[name];
            return name === "n" && typeof v === "number" ? fmt(v) : String(v);
        });
    }
    const date = (d, opts) => new Date(d).toLocaleString(lang, opts);
    const dateOnly = (d, opts) => new Date(d).toLocaleDateString(lang, opts);
    const time = (d, opts) => new Date(d).toLocaleTimeString(lang, opts);

    // ?lang= has set the cookie: keep it out of the address bar, so shared links follow the reader's language
    const url = new URL(window.location.href);
    if (url.searchParams.has("lang")) {
        url.searchParams.delete("lang");
        history.replaceState(history.state, "", url);
    }

    window.I18N = { lang, t, fmt, date, dateOnly, time };
})();
