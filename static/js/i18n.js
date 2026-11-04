// UI language: messages embedded by the server (#i18n), t(key, params), plurals and number formats.
// A message is a string with {name} placeholders, or plural forms (one, few, many, other) chosen by params.n.
// {n} is formatted with the language's digit grouping; other values are inserted as they are.
(function () {
    "use strict";
    const node = document.getElementById("i18n");
    const conf = node ? JSON.parse(node.textContent) : { lang: "en", messages: {} };
    const lang = conf.lang || "en";
    const messages = conf.messages || {};
    // The browser's regional variant of the page language (en-GB, ru-RU) for numbers, dates and times
    const locale = (navigator.languages || [navigator.language]).find((l) => l && l.toLowerCase().split("-")[0] === lang) || lang;
    const plurals = new Intl.PluralRules(lang);
    const numbers = new Intl.NumberFormat(locale);

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
    // Message with DOM nodes in place of placeholders, e.g. nodes("free.title", { prefix: span }) -> ["Free blocks in ", span]
    function nodes(key, params) {
        const strings = {}, parts = {};
        for (const [k, v] of Object.entries(params || {})) (v instanceof Node ? parts : strings)[k] = v;
        return t(key, strings).split(/\{(\w+)\}/).map((s, i) => (i % 2 ? parts[s] ?? `{${s}}` : s)).filter((s) => s !== "");
    }
    const has = (key) => Object.prototype.hasOwnProperty.call(messages, key);
    // Fixed decimals in the page language: 12.5 -> "12,5" in Russian
    const fixed = (n, digits) => new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
    const date = (d, opts) => new Date(d).toLocaleString(locale, opts);
    const dateOnly = (d, opts) => new Date(d).toLocaleDateString(locale, opts);
    const time = (d, opts) => new Date(d).toLocaleTimeString(locale, opts);

    // ?lang= has set the cookie: keep it out of the address bar, so shared links follow the reader's language
    const url = new URL(window.location.href);
    if (url.searchParams.has("lang")) {
        url.searchParams.delete("lang");
        history.replaceState(history.state, "", url);
    }

    window.I18N = { lang, locale, t, fmt, fixed, nodes, has, date, dateOnly, time };
})();
