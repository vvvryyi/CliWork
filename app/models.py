from datetime import datetime, timezone

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Client(TimestampMixin, db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False, index=True)
    phone = db.Column(db.String(50), nullable=False, default="", index=True)
    email = db.Column(db.String(200), nullable=False, default="", index=True)
    additional_contacts = db.Column(db.Text, nullable=False, default="")
    notes = db.Column(db.Text, nullable=False, default="")
    preferred_channel = db.Column(db.String(30), nullable=False, default="")
    whatsapp = db.Column(db.String(100), nullable=False, default="")
    telegram = db.Column(db.String(100), nullable=False, default="")
    max_contact = db.Column(db.String(200), nullable=False, default="")
    instagram = db.Column(db.String(200), nullable=False, default="")
    facebook = db.Column(db.String(300), nullable=False, default="")
    archived_at = db.Column(db.DateTime, nullable=True)

    interactions = db.relationship(
        "Interaction",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    attachments = db.relationship(
        "Attachment",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    events = db.relationship(
        "CalendarEvent",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    reminders = db.relationship(
        "Reminder",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    @property
    def is_archived(self):
        return self.archived_at is not None

    def channel_contact(self, channel):
        contacts = {
            "whatsapp": self.whatsapp or self.phone,
            "telegram": self.telegram,
            "max": self.max_contact,
            "instagram": self.instagram,
            "facebook": self.facebook,
        }
        return contacts.get(channel, "")


class Interaction(TimestampMixin, db.Model):
    __tablename__ = "interactions"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True
    )
    text = db.Column(db.Text, nullable=False, default="")
    interaction_type = db.Column(db.String(30), nullable=False, default="call")
    channel = db.Column(db.String(30), nullable=False, default="")
    delivery_status = db.Column(db.String(30), nullable=False, default="")

    client = db.relationship("Client", back_populates="interactions")
    attachments = db.relationship(
        "Attachment",
        back_populates="interaction",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Attachment(TimestampMixin, db.Model):
    __tablename__ = "attachments"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True
    )
    interaction_id = db.Column(
        db.Integer, db.ForeignKey("interactions.id"), nullable=True, index=True
    )
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    file_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(150), nullable=False, default="")
    file_size = db.Column(db.Integer, nullable=False, default=0)

    client = db.relationship("Client", back_populates="attachments")
    interaction = db.relationship("Interaction", back_populates="attachments")


class CalendarEvent(TimestampMixin, db.Model):
    __tablename__ = "calendar_events"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True
    )
    event_type = db.Column(db.String(50), nullable=False, default="other")
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    comment = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="planned")

    client = db.relationship("Client", back_populates="events")


class Reminder(TimestampMixin, db.Model):
    __tablename__ = "reminders"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True
    )
    reminder_type = db.Column(db.String(20), nullable=False, index=True)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    topic = db.Column(db.String(250), nullable=False)
    comment = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(30), nullable=False, default="planned")
    notify_before_minutes = db.Column(db.Integer, nullable=False, default=60)
    meeting_format = db.Column(db.String(20), nullable=False, default="")
    location_or_url = db.Column(db.String(500), nullable=False, default="")

    client = db.relationship("Client", back_populates="reminders")


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=False)
