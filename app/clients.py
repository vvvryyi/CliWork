from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
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
    local_to_utc_naive,
    parse_planning_suffix,
    save_uploads,
)


bp = Blueprint("clients", __name__, url_prefix="/clients")

INTERACTION_TYPES = {"call", "meeting", "message", "documents"}


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
    client.notes = request.form.get("notes", "").strip()
    client.preferred_channel = request.form.get("preferred_channel", "").strip()
    client.whatsapp = request.form.get("whatsapp", "").strip()
    client.telegram = request.form.get("telegram", "").strip()
    client.max_contact = request.form.get("max_contact", "").strip()
    client.instagram = request.form.get("instagram", "").strip()
    client.facebook = request.form.get("facebook", "").strip()


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
    client_groups = {}
    for client in clients:
        first = client.full_name.strip()[:1].upper()
        letter = first if first.isalpha() else "#"
        client_groups.setdefault(letter, []).append(client)
    return render_template(
        "clients/index.html",
        clients=clients,
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
    if request.method == "POST":
        apply_client_form(client)
        if not client.full_name:
            flash("Укажите ФИО клиента.", "error")
        else:
            db.session.add(client)
            db.session.commit()
            flash("Клиент создан.", "success")
            return redirect(url_for("clients.detail", client_id=client.id))
    return render_template(
        "clients/form.html",
        client=client,
        title="Новый клиент",
        channels=CHANNEL_LABELS,
    )


@bp.get("/<int:client_id>")
@login_required
def detail(client_id):
    client = get_client_or_404(client_id)
    interactions = db.session.scalars(
        db.select(Interaction)
        .where(Interaction.client_id == client.id)
        .order_by(Interaction.created_at.desc())
    ).all()
    return render_template(
        "clients/detail.html",
        client=client,
        interactions=interactions,
    )


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
            CalendarEvent.status == "planned",
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
    text = request.form.get("text", "").strip()
    files = request.files.getlist("files")
    if not text and not any(item.filename for item in files):
        flash("Введите текст или приложите файл.", "error")
        return redirect(url_for("clients.detail", client_id=client.id))

    interaction_type = request.form.get("interaction_type", "call")
    if interaction_type not in INTERACTION_TYPES:
        interaction_type = "call"
    interaction = Interaction(
        client_id=client.id,
        text=text,
        interaction_type=interaction_type,
    )
    db.session.add(interaction)
    db.session.flush()
    planned_local, date_suffix_found = parse_planning_suffix(text)
    calendar_event = None
    if planned_local:
        calendar_event = CalendarEvent(
            client_id=client.id,
            source_interaction_id=interaction.id,
            origin="interaction",
            event_type="task",
            starts_at=local_to_utc_naive(planned_local.isoformat(timespec="minutes")),
            comment="",
            status="planned",
        )
        db.session.add(calendar_event)
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
        text = request.form.get("text", "").strip()
        if not text and not interaction.attachments:
            flash("Запись не может быть пустой.", "error")
        else:
            interaction.text = text
            interaction_type = request.form.get("interaction_type", "call")
            interaction.interaction_type = (
                interaction_type if interaction_type in INTERACTION_TYPES else "call"
            )
            planned_local, date_suffix_found = parse_planning_suffix(text)
            calendar_event = interaction.calendar_event
            if planned_local:
                if calendar_event is None:
                    calendar_event = CalendarEvent(
                        client_id=client.id,
                        source_interaction_id=interaction.id,
                        origin="interaction",
                        event_type="task",
                    )
                    db.session.add(calendar_event)
                calendar_event.starts_at = local_to_utc_naive(
                    planned_local.isoformat(timespec="minutes")
                )
                calendar_event.comment = ""
                calendar_event.status = "planned"
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
    )


@bp.post("/<int:client_id>/interactions/<int:interaction_id>/delete")
@login_required
def delete_interaction(client_id, interaction_id):
    client = get_client_or_404(client_id)
    interaction = db.get_or_404(Interaction, interaction_id)
    if interaction.client_id != client.id:
        abort(404)
    paths = [Path(item.file_path) for item in interaction.attachments]
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
