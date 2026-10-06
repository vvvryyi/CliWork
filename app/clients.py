import re
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required
from sqlalchemy import or_

from .extensions import db
from .models import Attachment, CalendarEvent, Client, Interaction, utcnow
from .utils import (
    CHANNEL_LABELS,
    OPEN_EVENT_STATUSES,
    complete_due_quarterly_events,
    complete_client_events,
    due_client_contact_events,
    interaction_text_body,
    local_to_utc_naive,
    normalize_interaction_text,
    parse_planning_details,
    regenerate_quarterly_events,
    save_uploads,
    utc_naive_to_local,
    validate_mmdd,
)


bp = Blueprint("clients", __name__, url_prefix="/clients")

INTERACTION_TYPES = {"call", "meeting", "message", "documents"}
CLIENT_GROUP_LABELS = {
    "d": "Д",
    "v": "Б",
    "b": "В",
    "r": "Р",
    "m": "М",
    "p": "П",
    "a": "А",
    "k": "Н",
}
CLIENT_GROUPS = set(CLIENT_GROUP_LABELS)
CLIENT_FLAG_FIELDS = (
    "flag_f",
    "flag_d",
    "flag_b",
    "flag_n",
    "flag_ki",
    "flag_ku",
    "flag_ks",
    "flag_kr",
)
# Invisible boundary keeps entries separate in storage without drawing a line in the editor.
HISTORY_DIVIDER = "\n\u2063"


def get_client_or_404(client_id, include_archived=False):
    client = db.get_or_404(Client, client_id)
    if client.is_archived and not include_archived:
        abort(404)
    return client


def apply_client_form(client):
    client.full_name = request.form.get("full_name", "").strip()
    client.phone = request.form.get("phone", "").strip()
    client.email = request.form.get("email", "").strip()
    client.additional_contacts = request.form.get("additional_contacts", "").strip()
    client.preferred_channel = request.form.get("preferred_channel", "").strip()
    client.whatsapp = request.form.get("whatsapp", "").strip()
    client.telegram = request.form.get("telegram", "").strip()
    client.max_contact = request.form.get("max_contact", "").strip()
    client.instagram = request.form.get("instagram", "").strip()
    client.facebook = request.form.get("facebook", "").strip()


def apply_client_workflow_form(client):
    for field in CLIENT_FLAG_FIELDS:
        setattr(client, field, field in request.form)
    percent_value = request.form.get("percent_value", "").strip()
    if percent_value:
        if not percent_value.isdigit() or not 0 <= int(percent_value) <= 100:
            raise ValueError("Процент должен быть целым числом от 0 до 100.")
        client.percent_value = int(percent_value)
        client.flag_percent = True
    else:
        client.percent_value = None
        client.flag_percent = False
    client.quarterly_reminder_mmdd = validate_mmdd(
        request.form.get("quarterly_reminder_mmdd", "")
    )


def add_interaction(
    client, text, interaction_type="call", submission_token=None, show_history_date=True
):
    """Create a history record and its optional calendar event."""
    text = normalize_interaction_text(text, utcnow())
    if not interaction_text_body(text):
        text = ""
    interaction = Interaction(
        client_id=client.id,
        text=text,
        show_history_date=show_history_date,
        interaction_type=interaction_type,
        submission_token=submission_token,
    )
    db.session.add(interaction)
    db.session.flush()
    complete_client_events(client.id, interaction)

    planned_local, date_suffix_found, is_important = parse_planning_details(text)
    calendar_event = None
    if planned_local:
        starts_at = local_to_utc_naive(planned_local.isoformat(timespec="minutes"))
        calendar_event = CalendarEvent(
            client_id=client.id,
            source_interaction_id=interaction.id,
            origin="interaction",
            event_type="task",
            starts_at=starts_at,
            comment="",
            status="overdue" if starts_at < utcnow() else "planned",
            is_important=is_important,
        )
        db.session.add(calendar_event)
    return interaction, calendar_event, planned_local, date_suffix_found


def history_entry_date(interaction):
    return utc_naive_to_local(interaction.created_at).strftime("%y%m%d")


def build_history_text(interactions, now):
    entries = [
        (
            f"{history_entry_date(item)}\n{interaction_text_body(item.text)}"
            if item.show_history_date
            else interaction_text_body(item.text)
        )
        for item in interactions
    ]
    entries.append(normalize_interaction_text("", now))
    return HISTORY_DIVIDER.join(entries)


def parse_history_text(value, interactions, now):
    sections = value.replace("\r\n", "\n").split(HISTORY_DIVIDER)
    if len(sections) != len(interactions) + 1:
        raise ValueError("Граница между записями была удалена. Обновите страницу и повторите правку.")
    updates = []
    for interaction, section in zip(interactions, sections):
        if not section.strip():
            updates.append(None)
            continue
        first_line, separator, remainder = section.lstrip("\n").partition("\n")
        show_date = first_line.strip() == history_entry_date(interaction)
        if show_date:
            body = remainder
        elif separator and re.fullmatch(r"\d{6}", first_line.strip()):
            raise ValueError("Чтобы убрать дату записи, удалите её целиком.")
        else:
            body = section
        body = body.strip()
        if not body and (interaction_text_body(interaction.text) or not interaction.attachments):
            updates.append(None)
        else:
            updates.append(
                (f"{history_entry_date(interaction)} {body}" if body else "", show_date)
            )
    new_section = sections[-1].strip()
    new_show_date = bool(re.match(r"^\d{6}(?:\s|$)", new_section))
    return updates, normalize_interaction_text(new_section, now), new_show_date


def remove_interaction(interaction):
    paths = [Path(item.file_path) for item in interaction.attachments]
    completed_events = db.session.scalars(
        db.select(CalendarEvent).where(
            CalendarEvent.completed_by_interaction_id == interaction.id
        )
    ).all()
    for event in completed_events:
        event.completed_by_interaction_id = None
    if interaction.calendar_event is not None:
        if interaction.calendar_event.external_uid:
            interaction.calendar_event.source_interaction_id = None
            interaction.calendar_event.status = "cancelled"
        else:
            db.session.delete(interaction.calendar_event)
    db.session.delete(interaction)
    return paths


def reschedule_interaction_event(client, interaction):
    planned_local, date_suffix_found, is_important = parse_planning_details(
        interaction.text
    )
    calendar_event = interaction.calendar_event
    if planned_local:
        starts_at = local_to_utc_naive(planned_local.isoformat(timespec="minutes"))
        if calendar_event is None:
            calendar_event = CalendarEvent(
                client_id=client.id,
                source_interaction_id=interaction.id,
                origin="interaction",
                event_type="task",
                status="overdue" if starts_at < utcnow() else "planned",
            )
            db.session.add(calendar_event)
        calendar_event.starts_at = starts_at
        calendar_event.comment = ""
        calendar_event.is_important = is_important
        if calendar_event.status != "completed":
            calendar_event.status = "overdue" if starts_at < utcnow() else "planned"
    elif calendar_event is not None:
        if calendar_event.external_uid:
            calendar_event.status = "cancelled"
        else:
            db.session.delete(calendar_event)
    return planned_local, date_suffix_found


@bp.get("/")
@login_required
def index():
    query_text = request.args.get("q", "").strip()
    channel = request.args.get("channel", "").strip()
    show_archived = request.args.get("archived") == "1"

    statement = db.select(Client)
    statement = statement.where(
        Client.archived_at.is_not(None)
        if show_archived
        else Client.archived_at.is_(None)
    )
    if query_text:
        pattern = f"%{query_text}%"
        statement = statement.where(
            or_(
                Client.full_name.ilike(pattern),
                Client.phone.ilike(pattern),
                Client.email.ilike(pattern),
            )
        )
    if channel:
        statement = statement.where(Client.preferred_channel == channel)
    clients = db.session.scalars(statement.order_by(Client.full_name)).all()
    clients.sort(key=lambda item: item.full_name.casefold())
    grouped_by_category = {key: [] for key in CLIENT_GROUP_LABELS}
    alphabetical_clients = clients
    if not show_archived:
        for item in clients:
            if item.client_group in grouped_by_category:
                grouped_by_category[item.client_group].append(item)
        alphabetical_clients = [
            item for item in clients if item.client_group not in CLIENT_GROUPS
        ]

    client_groups = {}
    for client in alphabetical_clients:
        first = client.full_name.strip()[:1].upper()
        letter = first if first.isalpha() else "#"
        client_groups.setdefault(letter, []).append(client)
    return render_template(
        "clients/index.html",
        clients=clients,
        client_categories=CLIENT_GROUP_LABELS,
        clients_by_category=grouped_by_category,
        client_groups=client_groups,
        query_text=query_text,
        selected_channel=channel,
        show_archived=show_archived,
        channels=CHANNEL_LABELS,
    )


@bp.get("/contacts-today")
@login_required
def contacts_today():
    now = utcnow()
    today = utc_naive_to_local(now).date()
    try:
        selected_date = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        selected_date = today
    return render_template(
        "clients/contacts_today.html",
        contact_events=due_client_contact_events(now, selected_date),
        today=today,
        selected_date=selected_date,
        previous_date=selected_date - timedelta(days=1),
        next_date=selected_date + timedelta(days=1),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    client = Client()
    interaction_text = request.form.get("interaction_text", "").strip()
    if request.method == "POST":
        apply_client_form(client)
        if not client.full_name:
            flash("Укажите ФИО клиента.", "error")
        else:
            db.session.add(client)
            db.session.flush()
            planned_local = None
            date_suffix_found = False
            if interaction_text_body(interaction_text):
                _, _, planned_local, date_suffix_found = add_interaction(
                    client, interaction_text
                )
            db.session.commit()
            if planned_local:
                flash(
                    f"Клиент и запись созданы, дело добавлено на "
                    f"{planned_local:%d.%m.%Y %H:%M}.",
                    "success",
                )
            elif date_suffix_found:
                flash(
                    "Клиент и запись созданы, но дело не создано: "
                    "проверьте дату ГГММДД.",
                    "error",
                )
            elif interaction_text_body(interaction_text):
                flash("Клиент и запись истории созданы.", "success")
            else:
                flash("Клиент создан.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template(
        "clients/form.html",
        client=client,
        title="Новый клиент",
        channels=CHANNEL_LABELS,
        interaction_text=normalize_interaction_text(interaction_text, utcnow()),
        new_interaction_date=utcnow(),
    )


@bp.get("/<int:client_id>")
@login_required
def detail(client_id):
    client = get_client_or_404(client_id)
    event_id = request.args.get("event_id", type=int)
    selected_event = db.session.get(CalendarEvent, event_id) if event_id else None
    if selected_event is None or selected_event.client_id != client.id:
        selected_event = None
    interactions = db.session.scalars(
        db.select(Interaction)
        .where(Interaction.client_id == client.id)
        .order_by(Interaction.created_at)
    ).all()
    now = utcnow()
    return render_template(
        "clients/detail.html",
        client=client,
        interactions=interactions,
        history_text=build_history_text(interactions, now),
        interaction_token=uuid4().hex,
        client_categories=CLIENT_GROUP_LABELS,
        selected_event_id=selected_event.id if selected_event else None,
    )


@bp.post("/<int:client_id>/group")
@login_required
def toggle_group(client_id):
    client = get_client_or_404(client_id)
    requested_group = request.form.get("group", "")
    if requested_group != "none" and requested_group not in CLIENT_GROUPS:
        abort(400)
    client.client_group = requested_group
    regenerate_quarterly_events(client)
    db.session.commit()
    if requested_group == "none":
        flash("Клиент удалён из группы.", "success")
    else:
        flash(
            f"Клиент добавлен в группу {CLIENT_GROUP_LABELS[requested_group]}.",
            "success",
        )
    return redirect(request.referrer or url_for("clients.detail", client_id=client.id))


def search_excerpt(text, query, context=70):
    flattened = " ".join((text or "").split())
    match = re.search(re.escape(query), flattened, flags=re.IGNORECASE)
    if not match:
        return None
    start = max(0, match.start() - context)
    end = min(len(flattened), match.end() + context)
    return {
        "before": ("…" if start else "") + flattened[start:match.start()],
        "match": flattened[match.start():match.end()],
        "after": flattened[match.end():end] + ("…" if end < len(flattened) else ""),
    }


@bp.get("/search")
@login_required
def search_interactions():
    query_text = request.args.get("q", "").strip()[:100]
    if not query_text:
        return jsonify({"query": "", "results": []})

    rows = db.session.execute(
        db.select(Interaction, Client)
        .join(Client, Interaction.client_id == Client.id)
        .where(Client.archived_at.is_(None))
        .order_by(Interaction.created_at.desc())
    ).all()
    results = []
    for interaction, client in rows:
        excerpt = search_excerpt(interaction.text, query_text)
        if not excerpt:
            continue
        results.append(
            {
                "client_name": client.full_name,
                "url": url_for(
                    "clients.detail",
                    client_id=client.id,
                    _anchor=f"interaction-{interaction.id}",
                ),
                **excerpt,
            }
        )
        if len(results) >= 50:
            break
    return jsonify({"query": query_text, "results": results})


@bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit(client_id):
    client = get_client_or_404(client_id)
    if request.method == "POST":
        apply_client_form(client)
        if not client.full_name:
            flash("Укажите ФИО клиента.", "error")
        else:
            db.session.commit()
            flash("Данные клиента обновлены.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template(
        "clients/form.html",
        client=client,
        title="Редактирование клиента",
        channels=CHANNEL_LABELS,
    )


@bp.post("/<int:client_id>/archive")
@login_required
def archive(client_id):
    client = get_client_or_404(client_id)
    client.archived_at = utcnow()
    db.session.execute(
        db.update(CalendarEvent)
        .where(
            CalendarEvent.client_id == client.id,
            CalendarEvent.status.in_(OPEN_EVENT_STATUSES),
        )
        .values(status="cancelled")
    )
    db.session.commit()
    flash("Клиент перемещён в архив.", "success")
    return redirect(url_for("clients.index"))


@bp.post("/<int:client_id>/restore")
@login_required
def restore(client_id):
    client = get_client_or_404(client_id, include_archived=True)
    client.archived_at = None
    regenerate_quarterly_events(client)
    db.session.commit()
    flash("Клиент восстановлен из архива.", "success")
    return redirect(url_for("clients.detail", client_id=client.id))


@bp.post("/<int:client_id>/delete-permanently")
@login_required
def delete_permanently(client_id):
    client = get_client_or_404(client_id, include_archived=True)
    if not client.is_archived:
        abort(400)

    paths = [Path(item.file_path) for item in client.attachments.all()]
    for event in client.events.all():
        if event.daily_task is not None:
            task = event.daily_task
            task.calendar_event = None
            db.session.delete(task)
        db.session.delete(event)
    client_name = client.full_name
    db.session.delete(client)
    db.session.commit()

    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning(
                "Could not remove attachment after deleting client: %s", path
            )
    flash(f"Клиент «{client_name}» удалён навсегда.", "success")
    return redirect(url_for("clients.index", archived=1))


@bp.post("/<int:client_id>/history")
@login_required
def save_history(client_id):
    client = get_client_or_404(client_id)
    interactions = db.session.scalars(
        db.select(Interaction)
        .where(Interaction.client_id == client.id)
        .order_by(Interaction.created_at)
    ).all()
    submitted_text = request.form.get("history_text", "")
    files = request.files.getlist("files")
    event_id = request.form.get("event_id", type=int)
    selected_event = db.session.get(CalendarEvent, event_id) if event_id else None
    if selected_event is None or selected_event.client_id != client.id:
        selected_event = None
    try:
        if request.form.get("history_ids", "") != ",".join(
            str(item.id) for item in interactions
        ):
            raise ValueError("История изменилась. Обновите страницу перед сохранением.")
        updates, new_text, new_show_date = parse_history_text(
            submitted_text, interactions, utcnow()
        )
        apply_client_workflow_form(client)
        deleted_paths = []
        for interaction, update in zip(interactions, updates):
            if update is None:
                deleted_paths.extend(remove_interaction(interaction))
                continue
            updated_text, show_date = update
            interaction.show_history_date = show_date
            if interaction.text != updated_text:
                interaction.text = updated_text
                reschedule_interaction_event(client, interaction)
        submission_token = request.form.get("submission_token", "").strip()
        already_saved = submission_token and db.session.scalar(
            db.select(Interaction).where(Interaction.submission_token == submission_token)
        )
        if (interaction_text_body(new_text) or any(item.filename for item in files)) and not already_saved:
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", submission_token):
                submission_token = uuid4().hex
            interaction, _, _, _ = add_interaction(
                client,
                new_text,
                submission_token=submission_token,
                show_history_date=new_show_date,
            )
            save_uploads(files, client.id, interaction.id)
            if selected_event is not None and selected_event.status in OPEN_EVENT_STATUSES:
                selected_event.status = "completed"
                selected_event.completed_at = interaction.created_at
                selected_event.completed_by_interaction_id = interaction.id
        complete_due_quarterly_events(client.id)
        regenerate_quarterly_events(
            client, after_date=utc_naive_to_local(utcnow()).date()
        )
        db.session.commit()
        for path in deleted_paths:
            path.unlink(missing_ok=True)
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
        return render_template(
            "clients/detail.html",
            client=client,
            interactions=interactions,
            history_text=submitted_text,
            interaction_token=request.form.get("submission_token", uuid4().hex),
            client_categories=CLIENT_GROUP_LABELS,
            selected_event_id=selected_event.id if selected_event else None,
        ), 400
    flash("История клиента сохранена.", "success")
    return redirect(url_for("main.dashboard"))


@bp.post("/<int:client_id>/interactions")
@login_required
def create_interaction(client_id):
    client = get_client_or_404(client_id)
    text = normalize_interaction_text(request.form.get("text", ""), utcnow())
    files = request.files.getlist("files")
    try:
        apply_client_workflow_form(client)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("clients.detail", client_id=client.id))
    if not interaction_text_body(text) and not any(item.filename for item in files):
        regenerate_quarterly_events(client)
        db.session.commit()
        flash("Карточка клиента сохранена.", "success")
        return redirect(url_for("clients.index"))

    interaction_type = request.form.get("interaction_type", "call")
    if interaction_type not in INTERACTION_TYPES:
        interaction_type = "call"
    submission_token = request.form.get("submission_token", "").strip()
    if submission_token and db.session.scalar(
        db.select(Interaction).where(Interaction.submission_token == submission_token)
    ):
        flash("Эта запись уже сохранена.", "success")
        return redirect(url_for("clients.index"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", submission_token):
        submission_token = uuid4().hex

    interaction, calendar_event, planned_local, date_suffix_found = add_interaction(
        client, text, interaction_type, submission_token
    )
    complete_due_quarterly_events(client.id)
    regenerate_quarterly_events(
        client, after_date=utc_naive_to_local(utcnow()).date()
    )
    try:
        save_uploads(files, client.id, interaction.id)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
        return redirect(url_for("clients.detail", client_id=client.id))
    if calendar_event:
        flash(
            f"Запись сохранена, дело добавлено на {planned_local:%d.%m.%Y %H:%M}.",
            "success",
        )
    elif date_suffix_found:
        flash(
            "Запись сохранена, но дело не создано: проверьте дату ГГММДД.",
            "error",
        )
    else:
        flash("Запись добавлена в историю.", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/<int:client_id>/interactions/<int:interaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_interaction(client_id, interaction_id):
    client = get_client_or_404(client_id)
    interaction = db.get_or_404(Interaction, interaction_id)
    if interaction.client_id != client.id:
        abort(404)
    if request.method == "POST":
        if request.form.get("workflow_fields_present"):
            try:
                apply_client_workflow_form(client)
            except ValueError as error:
                flash(str(error), "error")
                return redirect(request.url)
        text = normalize_interaction_text(request.form.get("text", ""), utcnow())
        if not interaction_text_body(text) and not interaction.attachments:
            flash("Запись не может быть пустой.", "error")
        else:
            interaction.text = text if interaction_text_body(text) else ""
            interaction_type = request.form.get("interaction_type", "call")
            interaction.interaction_type = (
                interaction_type if interaction_type in INTERACTION_TYPES else "call"
            )
            planned_local, date_suffix_found = reschedule_interaction_event(
                client, interaction
            )
            if request.form.get("workflow_fields_present"):
                complete_due_quarterly_events(client.id)
                regenerate_quarterly_events(
                    client, after_date=utc_naive_to_local(utcnow()).date()
                )
            try:
                save_uploads(request.files.getlist("files"), client.id, interaction.id)
                db.session.commit()
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "error")
                return redirect(request.url)
            if planned_local:
                flash(
                    f"Запись обновлена, дело назначено на {planned_local:%d.%m.%Y %H:%M}.",
                    "success",
                )
            elif date_suffix_found:
                flash(
                    "Запись обновлена, но дело удалено: проверьте дату ГГММДД.",
                    "error",
                )
            else:
                flash("Запись истории обновлена.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template(
        "clients/interaction_form.html",
        client=client,
        interaction=interaction,
        interaction_text=interaction.text,
        new_interaction_date=interaction.created_at,
    )


@bp.post("/<int:client_id>/interactions/<int:interaction_id>/delete")
@login_required
def delete_interaction(client_id, interaction_id):
    client = get_client_or_404(client_id)
    interaction = db.get_or_404(Interaction, interaction_id)
    if interaction.client_id != client.id:
        abort(404)
    paths = remove_interaction(interaction)
    db.session.commit()
    for path in paths:
        path.unlink(missing_ok=True)
    flash("Запись истории удалена.", "success")
    return redirect(url_for("clients.detail", client_id=client.id))


@bp.get("/attachments/<int:attachment_id>")
@login_required
def download_attachment(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    path = Path(attachment.file_path).absolute()
    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).absolute()
    if not path.exists() or path.is_symlink():
        abort(404)
    if not path.is_relative_to(upload_root):
        abort(403)
    return send_file(
        path,
        as_attachment=True,
        download_name=attachment.original_name,
        mimetype=attachment.mime_type or None,
    )


@bp.post("/attachments/<int:attachment_id>/delete")
@login_required
def delete_attachment(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    client_id = attachment.client_id
    path = Path(attachment.file_path)
    db.session.delete(attachment)
    db.session.commit()
    path.unlink(missing_ok=True)
    flash("Файл удалён.", "success")
    return redirect(url_for("clients.detail", client_id=client_id))
