from __future__ import annotations

from typing import List

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text


db = SQLAlchemy()


class Trainer(db.Model):
    __tablename__ = "trainers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    experience = db.Column(db.Text, default="")
    weekly_hours = db.Column(db.Integer, default=0)

    schedules = db.relationship(
        "Schedule", back_populates="trainer", cascade="all, delete-orphan"
    )

    def list_experience(self) -> List[str]:
        if not self.experience:
            return []
        return [item.strip() for item in self.experience.split(",") if item.strip()]


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    hours_per_week = db.Column(db.Integer, default=0)
    daily_slots = db.Column(db.Integer, default=1)

    schedules = db.relationship(
        "Schedule", back_populates="subject", cascade="all, delete-orphan"
    )


class Schedule(db.Model):
    __tablename__ = "schedule"

    id = db.Column(db.Integer, primary_key=True)
    trainer_id = db.Column(db.Integer, db.ForeignKey("trainers.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    day = db.Column(db.String(32), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    section = db.Column(db.String(64), default="")

    trainer = db.relationship("Trainer", back_populates="schedules")
    subject = db.relationship("Subject", back_populates="schedules")


def init_db(app) -> None:
    """Initialise the database and create tables if needed."""

    db.init_app(app)
    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        subject_columns = {column["name"] for column in inspector.get_columns("subjects")}
        if "daily_slots" not in subject_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE subjects ADD COLUMN daily_slots INTEGER DEFAULT 1"))

        schedule_columns = {column["name"] for column in inspector.get_columns("schedule")}
        if "section" not in schedule_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE schedule ADD COLUMN section VARCHAR(64) DEFAULT ''"))
