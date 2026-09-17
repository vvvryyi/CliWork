document.querySelector("[data-nav-toggle]")?.addEventListener("click", () => {
    document.querySelector("[data-main-nav]")?.classList.toggle("is-open");
});

document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (!window.confirm(form.dataset.confirm)) {
            event.preventDefault();
        }
    });
});

document.querySelectorAll("[data-confirm-button]").forEach((button) => {
    button.addEventListener("click", (event) => {
        if (!window.confirm(button.dataset.confirmButton)) {
            event.preventDefault();
        }
    });
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
        const target = document.querySelector(button.dataset.copyTarget);
        if (!target) return;
        await navigator.clipboard.writeText(target.textContent.trim());
        const initial = button.textContent;
        button.textContent = "Скопировано";
        window.setTimeout(() => { button.textContent = initial; }, 1600);
    });
});

document.querySelectorAll("[data-copy-value]").forEach((button) => {
    button.addEventListener("click", async () => {
        await navigator.clipboard.writeText(button.dataset.copyValue);
        const initial = button.textContent;
        button.textContent = "Скопировано";
        window.setTimeout(() => { button.textContent = initial; }, 1600);
    });
});

document.querySelectorAll("[data-auto-submit]").forEach((field) => {
    field.addEventListener("change", () => field.form?.submit());
});

const interactionLeadingDate = /^(\d{6})(?:\s+|$)/;
const interactionTrailingDate = /(?:^|\s)\d{6}(?:\s+(?:в\s*)?(?:[01]\d|2[0-3]):[0-5]\d)?!?\s*$/;

function normalizeInteractionText(value, currentDate) {
    const cleaned = value.replace(/\r\n/g, "\n").trim();
    if (!cleaned) return `${currentDate} `;

    const leadingMatch = cleaned.match(interactionLeadingDate);
    const body = leadingMatch ? cleaned.slice(leadingMatch[0].length).trimStart() : cleaned;
    if (body && interactionTrailingDate.test(body)) return body;
    if (leadingMatch) return cleaned;
    return `${currentDate} ${cleaned}`;
}

function renderInteractionEditor(editor, value) {
    editor.replaceChildren();
    const leadingMatch = value.match(interactionLeadingDate);
    if (!leadingMatch) {
        editor.textContent = value;
        return;
    }

    const date = document.createElement("span");
    date.className = "interaction-date";
    date.contentEditable = "false";
    date.textContent = leadingMatch[1];
    editor.append(date, document.createTextNode(value.slice(6)));
}

document.querySelectorAll("textarea[data-dated-interaction]").forEach((source) => {
    const editor = document.createElement("div");
    editor.className = "dated-interaction-editor";
    editor.contentEditable = "true";
    editor.setAttribute("role", "textbox");
    editor.setAttribute("aria-multiline", "true");
    editor.setAttribute("aria-label", "Запись о клиенте");
    editor.style.minHeight = `${source.offsetHeight}px`;

    const syncSource = (normalize = false) => {
        let value = editor.innerText.replace(/\r\n/g, "\n");
        if (normalize) {
            value = normalizeInteractionText(value, source.dataset.currentDate);
            renderInteractionEditor(editor, value);
        }
        source.value = value;
    };

    const initialValue = normalizeInteractionText(
        source.value,
        source.dataset.currentDate,
    );
    renderInteractionEditor(editor, initialValue);
    source.value = initialValue;
    source.insertAdjacentElement("beforebegin", editor);
    source.hidden = true;

    editor.addEventListener("input", () => syncSource());
    editor.addEventListener("blur", () => syncSource(true));
    editor.addEventListener("paste", (event) => {
        event.preventDefault();
        document.execCommand(
            "insertText",
            false,
            event.clipboardData.getData("text/plain"),
        );
    });
    source.form?.addEventListener("submit", () => syncSource(true));
});

const searchDialog = document.querySelector("[data-search-dialog]");
const searchInput = searchDialog?.querySelector("[data-search-input]");
const searchForm = searchDialog?.querySelector("[data-search-form]");
const searchResults = searchDialog?.querySelector("[data-search-results]");
let searchTimer;
let searchRequest;

function setSearchMessage(message) {
    if (!searchResults) return;
    searchResults.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = message;
    searchResults.append(empty);
}

function renderSearchResults(items) {
    if (!searchResults) return;
    searchResults.replaceChildren();
    if (!items.length) {
        setSearchMessage("Совпадений не найдено.");
        return;
    }
    items.forEach((item) => {
        const link = document.createElement("a");
        link.className = "search-result";
        link.href = item.url;

        const name = document.createElement("strong");
        name.textContent = item.client_name;
        const excerpt = document.createElement("span");
        excerpt.className = "search-excerpt";
        excerpt.append(document.createTextNode(item.before));
        const mark = document.createElement("mark");
        mark.textContent = item.match;
        excerpt.append(mark, document.createTextNode(item.after));
        link.append(name, excerpt);
        searchResults.append(link);
    });
}

async function runInteractionSearch() {
    const query = searchInput?.value.trim() || "";
    if (!query) {
        searchRequest?.abort();
        setSearchMessage("Введите слово, которое нужно найти в записках.");
        return;
    }
    searchRequest?.abort();
    searchRequest = new AbortController();
    setSearchMessage("Ищем…");
    try {
        const url = new URL(searchDialog.dataset.searchUrl, window.location.origin);
        url.searchParams.set("q", query);
        const response = await fetch(url, {
            headers: { "Accept": "application/json" },
            signal: searchRequest.signal,
        });
        if (!response.ok) throw new Error("search failed");
        const payload = await response.json();
        renderSearchResults(payload.results || []);
    } catch (error) {
        if (error.name !== "AbortError") {
            setSearchMessage("Не удалось выполнить поиск. Попробуйте ещё раз.");
        }
    }
}

document.querySelector("[data-search-open]")?.addEventListener("click", () => {
    if (typeof searchDialog.showModal === "function") searchDialog.showModal();
    else searchDialog.setAttribute("open", "");
    searchInput?.focus();
});

searchDialog?.querySelector("[data-search-close]")?.addEventListener("click", () => {
    searchDialog.close();
});

searchDialog?.addEventListener("click", (event) => {
    if (event.target === searchDialog) searchDialog.close();
});

searchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    window.clearTimeout(searchTimer);
    runInteractionSearch();
});

searchInput?.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(runInteractionSearch, 350);
});

document.querySelectorAll("form[data-disable-on-submit]").forEach((form) => {
    form.addEventListener("submit", () => {
        form.querySelectorAll("button[type='submit']").forEach((button) => {
            button.disabled = true;
        });
    });
});

if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js");
    });
}
