from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .extensions import db
from .models import Client, Interaction
from .utils import (
    CHANNEL_LABELS,
    build_channel_url,
    complete_client_events,
    normalize_interaction_text,
    save_uploads,
)


bp = Blueprint("messaging", __name__, url_prefix="/messages")


@bp.route("/compose", methods=["GET", "POST"])
@login_required
def compose():
    clients = db.session.scalars(
        db.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.full_name)
    ).all()
    selected_client_id = request.args.get("client_id", type=int)

    if request.method == "POST":
        client = db.get_or_404(Client, request.form.get("client_id", type=int))
        channel = request.form.get("channel", "")
        message = request.form.get("message", "").strip()
        if channel not in CHANNEL_LABELS:
            flash("Выберите канал связи.", "error")
        elif not message:
            flash("Введите сообщение.", "error")
        else:
            interaction = Interaction(
                client_id=client.id,
                text=normalize_interaction_text(message),
                interaction_type="message",
                channel=channel,
                delivery_status="prepared",
            )
            db.session.add(interaction)
            db.session.flush()
            complete_client_events(client.id, interaction)
            try:
                save_uploads(
                    request.files.getlist("files"), client.id, interaction.id
                )
                db.session.commit()
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "error")
                return redirect(request.url)

            return render_template(
                "messaging/prepared.html",
                client=client,
                interaction=interaction,
                message=message,
                channel_label=CHANNEL_LABELS[channel],
                external_url=build_channel_url(client, channel, message),
            )

    return render_template(
        "messaging/compose.html",
        clients=clients,
        channels=CHANNEL_LABELS,
        selected_client_id=selected_client_id,
    )


@bp.post("/<int:interaction_id>/mark-sent")
@login_required
def mark_sent(interaction_id):
    interaction = db.get_or_404(Interaction, interaction_id)
    interaction.delivery_status = "sent"
    db.session.commit()
    flash("Отправка отмечена в истории клиента.", "success")
    return redirect(url_for("clients.detail", client_id=interaction.client_id))
