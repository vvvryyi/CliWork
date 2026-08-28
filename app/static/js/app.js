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

const reminderType = document.querySelector("[data-reminder-type]");
const meetingFields = document.querySelector("[data-meeting-fields]");
if (reminderType && meetingFields) {
    const updateMeetingFields = () => {
        meetingFields.hidden = reminderType.value !== "meeting";
    };
    reminderType.addEventListener("change", updateMeetingFields);
    updateMeetingFields();
}
