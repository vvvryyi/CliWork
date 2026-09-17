import re
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
    complete_client_events,
    interaction_text_body,
    local_to_utc_naive,
    normalize_interaction_text,
    parse_planning_details,
    save_uploads,
)


bp = Blueprint("clients", __name__, url_prefix="/clients")

INTERACTION_TYPES = {"call", "meeting", "message", "documents"}
CLIENT_GROUPS = {"active", "potential"}


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


def add_interaction(client, text, interaction_type="call", submission_token=None):
    """Create a history record and its optional calendar event."""
    text = normalize_interaction_text(text, utcnow())
    if not interaction_text_body(text):
        text = ""
    interaction = Interaction(
        client_id=client.id,
        text=text,
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
    active_clients = []
    potential_clients = []
    alphabetical_clients = clients
    if not show_archived:
        active_clients = [item for item in clients if item.client_group == "active"]
        potential_clients = [
            item for item in clients if item.client_group == "potential"
        ]
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
        active_clients=active_clients,
        potential_clients=potential_clients,
        client_groups=client_groups,
        query_text=query_text,
        selected_channel=channel,
        show_archived=show_archived,
        channels=CHANNEL_LABELS,
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
                    f"Клиент и запись созданы, событие добавлено на "
                    f"{planned_local:%d.%m.%Y %H:%M}.",
                    "success",
                )
            elif date_suffix_found:
                flash(
                    "Клиент и запись созданы, но событие не создано: "
                    "проверьте дату ГГММДД.",
                    "error",
                )
            elif interaction_text_body(interaction_text):
                flash("Клиент и запись истории созданы.", "success")
            else:
                flash("Клиент создан.", "success")
            return redirect(url_for("clients.detail", client_id=client.id))
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
    current_interaction = db.session.scalar(
        db.select(Interaction)
        .where(Interaction.client_id == client.id)
        .order_by(Interaction.created_at.desc())
        .limit(1)
    )
    return render_template(
        "clients/detail.html",
        client=client,
        current_interaction=current_interaction,
        interaction_text=normalize_interaction_text(
            current_interaction.text if current_interaction else "",
            utcnow(),
        ),
        interaction_token=uuid4().hex,
        new_interaction_date=utcnow(),
    )


@bp.post("/<int:client_id>/group")
@login_required
def toggle_group(client_id):
    client = get_client_or_404(client_id)
    requested_group = request.form.get("group", "")
    if requested_group not in CLIENT_GROUPS:
        abort(400)
    client.client_group = (
        "none" if client.client_group == requested_group else requested_group
    )
    db.session.commit()
    labels = {"active": "активных", "potential": "потенциальных"}
    if client.client_group == requested_group:
        flash(f"Клиент добавлен в группу {labels[requested_group]} клиентов.", "success")
    else:
        flash(f"Клиент удалён из группы {labels[requested_group]} клиентов.", "success")
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
            return redirect(url_for("clients.detail", client_id=client.id))
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
    db.session.commit()
    flash("Клиент восстановлен из архива.", "success")
    return redirect(url_for("clients.detail", client_id=client.id))


@bp.post("/<int:client_id>/interactions")
@login_required
def create_interaction(client_id):
    client = get_client_or_404(client_id)
    text = normalize_interaction_text(request.form.get("text", ""), utcnow())
    files = request.files.getlist("files")
    if not interaction_text_body(text) and not any(item.filename for item in files):
        flash("Введите текст или приложите файл.", "error")
        return redirect(url_for("clients.detail", client_id=client.id))

    interaction_type = request.form.get("interaction_type", "call")
    if interaction_type not in INTERACTION_TYPES:
        interaction_type = "call"
    submission_token = request.form.get("submission_token", "").strip()
    if submission_token and db.session.scalar(
        db.select(Interaction).where(Interaction.submission_token == submission_token)
    ):
        flash("Эта запись уже сохранена.", "success")
        return redirect(url_for("clients.detail", client_id=client.id))
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", submission_token):
        submission_token = uuid4().hex

    interaction, calendar_event, planned_local, date_suffix_found = add_interaction(
        client, text, interaction_type, submission_token
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
            f"Запись сохранена, событие добавлено на {planned_local:%d.%m.%Y %H:%M}.",
            "success",
        )
    elif date_suffix_found:
        flash(
            "Запись сохранена, но событие не создано: проверьте дату ГГММДД.",
            "error",
        )
    else:
        flash("Запись добавлена в историю.", "success")
    return redirect(url_for("clients.detail", client_id=client.id))


@bp.route("/<int:client_id>/interactions/<int:interaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_interaction(client_id, interaction_id):
    client = get_client_or_404(client_id)
    interaction = db.get_or_404(Interaction, interaction_id)
    if interaction.client_id != client.id:
        abort(404)
    if request.method == "POST":
        text = normalize_interaction_text(request.form.get("text", ""), utcnow())
        if not interaction_text_body(text) and not interaction.attachments:
            flash("Запись не может быть пустой.", "error")
        else:
            interaction.text = text if interaction_text_body(text) else ""
            interaction_type = request.form.get("interaction_type", "call")
            interaction.interaction_type = (
                interaction_type if interaction_type in INTERACTION_TYPES else "call"
            )
            planned_local, date_suffix_found, is_important = parse_planning_details(
                interaction.text
            )
            calendar_event = interaction.calendar_event
            if planned_local:
                starts_at = local_to_utc_naive(
                    planned_local.isoformat(timespec="minutes")
                )
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
                    calendar_event.status = (
                        "overdue" if starts_at < utcnow() else "planned"
                    )
            elif calendar_event is not None:
                db.session.delete(calendar_event)
            try:
                save_uploads(request.files.getlist("files"), client.id, interaction.id)
                db.session.commit()
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "error")
                return redirect(request.url)
            if planned_local:
                flash(
                    f"Запись обновлена, событие назначено на {planned_local:%d.%m.%Y %H:%M}.",
                    "success",
                )
            elif date_suffix_found:
                flash(
                    "Запись обновлена, но событие удалено: проверьте дату ГГММДД.",
                    "error",
                )
            else:
                flash("Запись истории обновлена.", "success")
            return redirect(url_for("clients.detail", client_id=client.id))
    return render_template(
        "clients/interaction_form.html",
        client=client,
        interaction=interaction,
        interaction_text=normalize_interaction_text(interaction.text, utcnow()),
        new_interaction_date=utcnow(),
    )


@bp.post("/<int:client_id>/interactions/<int:interaction_id>/delete")
@login_required
def delete_interaction(client_id, interaction_id):
    client = get_client_or_404(client_id)
    interaction = db.get_or_404(Interaction, interaction_id)
    if interaction.client_id != client.id:
        abort(404)
    paths = [Path(item.file_path) for item in interaction.attachments]
    completed_events = db.session.scalars(
        db.select(CalendarEvent).where(
            CalendarEvent.completed_by_interaction_id == interaction.id
        )
    ).all()
    now = utcnow()
    for event in completed_events:
        event.status = "overdue" if event.starts_at < now else "planned"
        event.completed_at = None
        event.completed_by_interaction_id = None
    if interaction.calendar_event is not None:
        db.session.delete(interaction.calendar_event)
    db.session.delete(interaction)
    db.session.commit()
    for path in paths:
        path.unlink(missing_ok=True)
    flash("Запись истории удалена.", "success")
    return redirect(url_for("clients.detail", client_id=client.id))


@bp.get("/attachments/<int:attachment_id>")
@login_required
def download_attachment(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    path = Path(attachment.file_path)
    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        abort(404)
    if not resolved.is_relative_to(upload_root):
        abort(403)
    return send_file(
        resolved,
        as_attachment=True,
        download_name=attachment.original_name,
        mimetype=attachment.mime_type or None,
    )


@bp.post("/attachments/<int:attachment_id>/delete")
@login_required
def delete_attachment(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    client_id = attachment.client_id
    interaction_id = attachment.interaction_id
    path = Path(attachment.file_path)
    db.session.delete(attachment)
    db.session.commit()
    path.unlink(missing_ok=True)
    flash("Файл удалён.", "success")
    if interaction_id:
        return redirect(
            url_for(
                "clients.edit_interaction",
                client_id=client_id,
                interaction_id=interaction_id,
            )
        )
    return redirect(url_for("clients.detail", client_id=client_id))
