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

document.querySelectorAll("[data-client-segment-open]").forEach((button) => {
    button.addEventListener("click", () => {
        const dialog = document.getElementById(button.dataset.clientSegmentOpen);
        if (!dialog) return;
        if (typeof dialog.showModal === "function") dialog.showModal();
        else dialog.setAttribute("open", "");
    });
});

document.querySelectorAll("[data-client-segment-dialog]").forEach((dialog) => {
    dialog.querySelector("[data-client-segment-close]")?.addEventListener("click", () => {
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
    });
    dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        if (typeof dialog.close === "function") dialog.close();
        else dialog.removeAttribute("open");
    });
});

const interactionLeadingDate = /^(\d{6})(?:\s+|$)/;
const interactionTrailingDate = /(?:^|\s)\d{6}(?:\s+(?:в\s*)?(?:[01]\d|2[0-3]):[0-5]\d)?!?\s*$/;

function normalizeInteractionText(value, currentDate) {
    const cleaned = value.replace(/\r\n/g, "\n").trim();
    if (!cleaned) return `${currentDate} `;

    const leadingMatch = cleaned.match(interactionLeadingDate);
    const body = leadingMatch ? cleaned.slice(leadingMatch[0].length).trimStart() : cleaned;
    return body ? `${currentDate} ${body}` : `${currentDate} `;
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

document.querySelectorAll("[data-file-input]").forEach((input) => {
    input.addEventListener("change", () => {
        const status = input.closest(".compact-upload")?.querySelector("[data-file-status]");
        if (!status) return;
        const count = input.files?.length || 0;
        status.textContent = count ? `Выбрано: ${count} · До 20 МБ` : "До 20 МБ";
    });
});

const taskEditor = document.querySelector("[data-task-editor]");
if (taskEditor) {
    const taskList = taskEditor.querySelector("[data-task-list]");
    const taskStatus = taskEditor.querySelector("[data-task-status]");
    const taskCsrf = taskEditor.querySelector("[data-task-csrf]").value;
    const selectedTaskDate = taskEditor.dataset.selectedDate;
    const undoStack = [];

    const setTaskStatus = (message, isError = false) => {
        taskStatus.textContent = message;
        taskStatus.classList.toggle("is-error", isError);
    };

    const postTask = async (payload) => {
        const formData = new FormData();
        formData.set("csrf_token", taskCsrf);
        Object.entries(payload).forEach(([key, value]) => {
            if (value !== null && value !== undefined && value !== "") {
                formData.set(key, value);
            }
        });
        const response = await fetch(taskEditor.dataset.saveUrl, {
            method: "POST",
            body: formData,
            headers: { "Accept": "application/json" },
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || "Не удалось сохранить дело.");
        return result;
    };

    const taskSnapshot = (row) => ({
        id: row.dataset.taskId || null,
        text: row.dataset.savedText || "",
        completed: row.dataset.savedCompleted === "1",
        dueDate: row.dataset.dueDate,
    });

    const buildTaskRow = (task) => {
        const row = document.createElement("div");
        row.className = `task-line${task.completed ? " is-completed" : ""}`;
        row.dataset.taskRow = "";
        row.dataset.taskId = task.id || "";
        row.dataset.dueDate = task.dueDate || selectedTaskDate;
        row.dataset.savedText = task.text || "";
        row.dataset.savedCompleted = task.completed ? "1" : "0";
        if (!task.id) row.classList.add("is-new");

        const checkbox = document.createElement("input");
        checkbox.className = "task-line-check";
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(task.completed);
        checkbox.dataset.taskCheck = "";
        checkbox.setAttribute("aria-label", "Выполнено");

        const input = document.createElement("input");
        input.className = "task-line-text";
        input.type = "text";
        input.maxLength = 500;
        input.value = task.text || "";
        input.dataset.taskText = "";
        input.placeholder = task.id ? "" : "Введите дело и нажмите Enter";
        input.setAttribute("aria-label", task.id ? "Текст дела" : "Новое дело");

        const remove = document.createElement("button");
        remove.className = "task-line-remove";
        remove.type = "button";
        remove.dataset.taskRemove = "";
        remove.setAttribute("aria-label", task.id ? "Удалить дело" : "Удалить строку");
        remove.textContent = "×";
        row.append(checkbox, input, remove);
        return row;
    };

    const ensureBlankTaskRow = () => {
        let blank = taskList.querySelector(".task-line.is-new");
        if (!blank) {
            blank = buildTaskRow({ dueDate: selectedTaskDate });
            taskList.append(blank);
        }
        return blank;
    };

    const sortTaskRows = () => {
        const blank = ensureBlankTaskRow();
        const rows = [...taskList.querySelectorAll("[data-task-row]:not(.is-new)")];
        rows.sort((left, right) => {
            const completionOrder = Number(left.dataset.savedCompleted === "1")
                - Number(right.dataset.savedCompleted === "1");
            if (completionOrder) return completionOrder;
            const leftText = left.dataset.savedText.toLocaleLowerCase("ru").replaceAll("ё", "е");
            const rightText = right.dataset.savedText.toLocaleLowerCase("ru").replaceAll("ё", "е");
            if (leftText < rightText) return -1;
            if (leftText > rightText) return 1;
            return Number(left.dataset.taskId) - Number(right.dataset.taskId);
        });
        rows.forEach((row) => taskList.insertBefore(row, blank));
    };

    const rememberTaskChange = (before, after, index) => {
        undoStack.push({ before, after, index });
        if (undoStack.length > 100) undoStack.shift();
    };

    const saveTaskRow = async (row, { remember = true, remove = false } = {}) => {
        if (row.dataset.saving === "1") return null;
        const input = row.querySelector("[data-task-text]");
        const checkbox = row.querySelector("[data-task-check]");
        const before = row.dataset.taskId ? taskSnapshot(row) : null;
        const text = input.value.trim();
        const index = [...taskList.children].indexOf(row);

        if (!text && !row.dataset.taskId) {
            checkbox.checked = false;
            if (!row.classList.contains("is-new")) row.remove();
            ensureBlankTaskRow();
            return null;
        }

        row.dataset.saving = "1";
        setTaskStatus("Сохраняем…");
        try {
            if (remove || !text) {
                await postTask({ task_id: row.dataset.taskId, delete: "1" });
                row.remove();
                if (remember && before) rememberTaskChange(before, null, index);
                ensureBlankTaskRow();
                setTaskStatus("Сохранено");
                return null;
            }

            const result = await postTask({
                task_id: row.dataset.taskId,
                text,
                due_date: row.dataset.dueDate,
                completed: checkbox.checked ? "1" : "0",
            });
            row.dataset.taskId = String(result.task_id);
            row.dataset.savedText = result.text;
            row.dataset.savedCompleted = result.completed ? "1" : "0";
            row.classList.remove("is-new");
            row.classList.toggle("is-completed", result.completed);
            input.value = result.text;
            input.placeholder = "";
            const after = taskSnapshot(row);
            if (remember && JSON.stringify(before) !== JSON.stringify(after)) {
                rememberTaskChange(before, after, index);
            }
            if (result.completed && row.dataset.dueDate !== selectedTaskDate) {
                row.remove();
            }
            sortTaskRows();
            setTaskStatus("Сохранено");
            return after;
        } catch (error) {
            setTaskStatus(error.message, true);
            throw error;
        } finally {
            delete row.dataset.saving;
        }
    };

    const replaceUndoTaskId = (oldId, newId) => {
        undoStack.forEach((action) => {
            [action.before, action.after].forEach((snapshot) => {
                if (snapshot?.id === oldId) snapshot.id = newId;
            });
        });
    };

    const applyTaskUndo = async () => {
        const action = undoStack.pop();
        if (!action) return;
        setTaskStatus("Отменяем…");
        try {
            if (!action.before && action.after) {
                await postTask({ task_id: action.after.id, delete: "1" });
                taskList.querySelector(`[data-task-id="${action.after.id}"]`)?.remove();
            } else if (action.before && !action.after) {
                const restored = await postTask({
                    text: action.before.text,
                    due_date: action.before.dueDate,
                    completed: action.before.completed ? "1" : "0",
                });
                const restoredRow = buildTaskRow({
                    id: String(restored.task_id),
                    text: restored.text,
                    dueDate: restored.due_date,
                    completed: restored.completed,
                });
                const blank = ensureBlankTaskRow();
                taskList.insertBefore(restoredRow, taskList.children[action.index] || blank);
                replaceUndoTaskId(action.before.id, String(restored.task_id));
            } else if (action.before && action.after) {
                const restored = await postTask({
                    task_id: action.after.id,
                    text: action.before.text,
                    due_date: action.before.dueDate,
                    completed: action.before.completed ? "1" : "0",
                });
                let row = taskList.querySelector(`[data-task-id="${action.after.id}"]`);
                if (!row) {
                    row = buildTaskRow({
                        id: String(restored.task_id),
                        text: restored.text,
                        dueDate: restored.due_date,
                        completed: restored.completed,
                    });
                    taskList.insertBefore(row, ensureBlankTaskRow());
                } else {
                    row.dataset.savedText = restored.text;
                    row.dataset.savedCompleted = restored.completed ? "1" : "0";
                    row.querySelector("[data-task-text]").value = restored.text;
                    row.querySelector("[data-task-check]").checked = restored.completed;
                    row.classList.toggle("is-completed", restored.completed);
                }
            }
            sortTaskRows();
            setTaskStatus("Изменение отменено");
        } catch (error) {
            undoStack.push(action);
            setTaskStatus(error.message, true);
        }
    };

    taskList.addEventListener("keydown", async (event) => {
        const input = event.target.closest("[data-task-text]");
        if (!input || event.key !== "Enter") return;
        event.preventDefault();
        const row = input.closest("[data-task-row]");
        try {
            await saveTaskRow(row);
            const blank = ensureBlankTaskRow();
            blank.querySelector("[data-task-text]").focus();
        } catch (_) {
            input.focus();
        }
    });

    taskList.addEventListener("focusout", (event) => {
        const input = event.target.closest("[data-task-text]");
        if (!input) return;
        const row = input.closest("[data-task-row]");
        if (event.relatedTarget?.closest?.("[data-task-row]") === row) return;
        if (input.value.trim() !== row.dataset.savedText) {
            saveTaskRow(row).catch(() => {});
        }
    });

    taskList.addEventListener("change", (event) => {
        const checkbox = event.target.closest("[data-task-check]");
        if (!checkbox) return;
        const row = checkbox.closest("[data-task-row]");
        if (!row.querySelector("[data-task-text]").value.trim()) {
            checkbox.checked = false;
            return;
        }
        saveTaskRow(row).catch(() => {});
    });

    taskList.addEventListener("mousedown", (event) => {
        if (event.target.closest("[data-task-remove]")) event.preventDefault();
    });

    taskList.addEventListener("click", (event) => {
        const button = event.target.closest("[data-task-remove]");
        if (!button) return;
        const row = button.closest("[data-task-row]");
        saveTaskRow(row, { remove: true }).catch(() => {});
    });

    taskEditor.addEventListener("keydown", (event) => {
        if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z" || event.shiftKey) return;
        const activeInput = document.activeElement?.closest?.("[data-task-text]");
        const activeRow = activeInput?.closest("[data-task-row]");
        if (activeInput && activeInput.value.trim() !== activeRow.dataset.savedText) return;
        event.preventDefault();
        applyTaskUndo();
    });
}

if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js");
    });
}
