from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from models import Schedule, Subject, Trainer, db, init_db
from scheduler import DAYS, auto_schedule, get_time_slots

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
DATABASE_PATH = BASE_DIR / "database" / "schedule.db"
ALLOWED_EXTENSIONS = {".xls", ".xlsx"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("APP_SECRET", "training-schedule-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    init_db(app)

    @app.route("/", methods=["GET"])
    def index():
        trainers = Trainer.query.order_by(Trainer.name).all()
        subjects = Subject.query.order_by(Subject.name).all()
        time_slots = get_time_slots()
        weekly_schedule = _group_schedule(time_slots)
        trainer_schedules = _group_schedule_by_trainer(time_slots)
        conflicts = _detect_conflicts()
        return render_template(
            "index.html",
            trainers=trainers,
            subjects=subjects,
            weekly_schedule=weekly_schedule,
            trainer_schedules=trainer_schedules,
            time_slots=time_slots,
            conflicts=conflicts,
            days=DAYS,
        )

    @app.route("/upload", methods=["POST"])
    def upload():
        file = request.files.get("excel_file")
        if file is None or file.filename == "":
            flash("الرجاء اختيار ملف Excel قبل الرفع", "danger")
            return redirect(url_for("index"))

        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            flash("نوع الملف غير مدعوم. استخدم XLSX أو XLS.", "danger")
            return redirect(url_for("index"))

        filename = secure_filename(file.filename)
        save_path = UPLOAD_FOLDER / filename
        file.save(save_path)

        try:
            df = pd.read_excel(save_path)
            processed = _process_excel_dataframe(df)
            flash(
                f"تمت معالجة الملف بنجاح: {processed['trainers']} مدرب، {processed['subjects']} مادة.",
                "success",
            )
        except Exception as exc:  # pylint: disable=broad-except
            flash(f"حدث خطأ أثناء قراءة الملف: {exc}", "danger")
        finally:
            save_path.unlink(missing_ok=True)

        return redirect(url_for("index"))

    @app.route("/auto-schedule", methods=["POST"])
    def run_auto_schedule():
        result = auto_schedule(db.session)
        if result["created"]:
            flash(
                f"تم إنشاء {result['created']} حصة دراسية تلقائيًا.",
                "success",
            )
        if result["warnings"]:
            for warning in result["warnings"]:
                flash(warning, "warning")
        if not result["created"] and not result["warnings"]:
            flash("لا توجد بيانات كافية للجدولة.", "info")
        return redirect(url_for("index"))

    @app.route("/download-template", methods=["GET"])
    def download_template():
        template_path = BASE_DIR / "sample_data" / "trainers_template.xlsx"
        if not template_path.exists():
            flash("ملف القالب غير متوفر حالياً.", "danger")
            return redirect(url_for("index"))
        return send_file(
            template_path,
            as_attachment=True,
            download_name="trainers_template.xlsx",
        )

    @app.route("/export-schedule", methods=["GET"])
    def export_schedule():
        entries = (
            Schedule.query.join(Trainer).join(Subject).order_by(
                Schedule.day,
                Schedule.start_time,
            )
        ).all()

        if not entries:
            flash("لا يوجد جدول لتصديره حالياً.", "warning")
            return redirect(url_for("index"))

        records = [
            {
                "اليوم": entry.day,
                "وقت البداية": entry.start_time,
                "وقت النهاية": entry.end_time,
                "المادة": entry.subject.name,
                "المدرب": entry.trainer.name,
            }
            for entry in entries
        ]

        df = pd.DataFrame(records)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Schedule", index=False)
        buffer.seek(0)
        filename = f"schedule_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/trainer/<int:trainer_id>/export", methods=["GET"])
    def export_trainer_schedule(trainer_id: int):
        trainer = Trainer.query.get_or_404(trainer_id)
        entries = (
            Schedule.query.filter_by(trainer_id=trainer_id)
            .join(Subject)
            .order_by(Schedule.day, Schedule.start_time)
            .all()
        )

        if not entries:
            flash(f"لا توجد حصص للمدرب {trainer.name} لتصديرها.", "warning")
            return redirect(url_for("index"))

        records = [
            {
                "اليوم": entry.day,
                "وقت البداية": entry.start_time,
                "وقت النهاية": entry.end_time,
                "المادة": entry.subject.name,
                "الشعبة": entry.section or "-",
            }
            for entry in entries
        ]

        df = pd.DataFrame(records)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=trainer.name[:28] or "Trainer", index=False)
        buffer.seek(0)
        filename = f"schedule_{trainer.name}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/reset-data", methods=["POST"])
    def reset_data():
        db.session.query(Schedule).delete()
        db.session.query(Subject).delete()
        db.session.query(Trainer).delete()
        db.session.commit()
        flash("تم مسح جميع البيانات من قاعدة البيانات.", "success")
        return redirect(url_for("index"))

    @app.route("/schedule/<int:schedule_id>/update", methods=["POST"])
    def update_schedule_entry(schedule_id: int):
        entry = Schedule.query.get_or_404(schedule_id)
        time_slots = get_time_slots()
        slot_count = len(time_slots)

        try:
            subject_id = int(request.form.get("subject_id", entry.subject_id))
            trainer_id = int(request.form.get("trainer_id", entry.trainer_id))
            start_slot = int(request.form.get("start_slot", 0))
            duration_slots = max(int(request.form.get("duration_slots", 1)), 1)
        except (TypeError, ValueError):
            flash("بيانات التعديل غير صالحة.", "danger")
            return redirect(url_for("index"))

        day = request.form.get("day", entry.day)
        section = (request.form.get("section") or "").strip()

        subject = Subject.query.get(subject_id)
        trainer = Trainer.query.get(trainer_id)
        if subject is None or trainer is None:
            flash("المادة أو المدرب غير موجودين.", "danger")
            return redirect(url_for("index"))

        if start_slot < 0 or start_slot >= slot_count:
            flash("الفتحة الزمنية غير صالحة.", "danger")
            return redirect(url_for("index"))

        if start_slot + duration_slots > slot_count:
            flash("المدة المختارة تتجاوز اليوم.", "danger")
            return redirect(url_for("index"))

        new_start = time_slots[start_slot][0]
        new_end = time_slots[start_slot + duration_slots - 1][1]

        overlapping = (
            Schedule.query.filter(
                Schedule.id != schedule_id,
                Schedule.day == day,
                Schedule.start_time < new_end,
                Schedule.end_time > new_start,
            )
            .first()
        )
        if overlapping is not None:
            flash("هناك حصة أخرى في نفس الفترة الزمنية.", "danger")
            return redirect(url_for("index"))

        trainer_conflict = (
            Schedule.query.filter(
                Schedule.id != schedule_id,
                Schedule.trainer_id == trainer_id,
                Schedule.day == day,
                Schedule.start_time < new_end,
                Schedule.end_time > new_start,
            )
            .first()
        )
        if trainer_conflict is not None:
            flash("المدرب مشغول في نفس الفترة.", "danger")
            return redirect(url_for("index"))

        entry.subject_id = subject_id
        entry.trainer_id = trainer_id
        entry.day = day
        entry.start_time = new_start
        entry.end_time = new_end
        entry.section = section

        db.session.commit()
        flash("تم تحديث الحصة بنجاح.", "success")
        return redirect(url_for("index"))

    @app.route("/schedule/create", methods=["POST"])
    def create_schedule_entry():
        time_slots = get_time_slots()
        slot_count = len(time_slots)

        try:
            subject_id = int(request.form.get("subject_id"))
            trainer_id = int(request.form.get("trainer_id"))
            start_slot = int(request.form.get("start_slot", 0))
            duration_slots = max(int(request.form.get("duration_slots", 1)), 1)
        except (TypeError, ValueError):
            flash("بيانات الإضافة غير صالحة.", "danger")
            return redirect(url_for("index"))

        day = request.form.get("day")
        section = (request.form.get("section") or "").strip()

        subject = Subject.query.get(subject_id)
        trainer = Trainer.query.get(trainer_id)
        if subject is None or trainer is None or day not in DAYS:
            flash("المادة أو المدرب أو اليوم غير صالحين.", "danger")
            return redirect(url_for("index"))

        if start_slot < 0 or start_slot >= slot_count:
            flash("الفتحة الزمنية غير صالحة.", "danger")
            return redirect(url_for("index"))

        if start_slot + duration_slots > slot_count:
            flash("المدة المختارة تتجاوز اليوم.", "danger")
            return redirect(url_for("index"))

        new_start = time_slots[start_slot][0]
        new_end = time_slots[start_slot + duration_slots - 1][1]

        overlapping = (
            Schedule.query.filter(
                Schedule.day == day,
                Schedule.start_time < new_end,
                Schedule.end_time > new_start,
            )
            .first()
        )
        if overlapping is not None:
            flash("هناك حصة أخرى في نفس الفترة الزمنية.", "danger")
            return redirect(url_for("index"))

        trainer_conflict = (
            Schedule.query.filter(
                Schedule.trainer_id == trainer_id,
                Schedule.day == day,
                Schedule.start_time < new_end,
                Schedule.end_time > new_start,
            )
            .first()
        )
        if trainer_conflict is not None:
            flash("المدرب مشغول في نفس الفترة.", "danger")
            return redirect(url_for("index"))

        new_entry = Schedule(
            trainer_id=trainer_id,
            subject_id=subject_id,
            day=day,
            start_time=new_start,
            end_time=new_end,
            section=section,
        )
        db.session.add(new_entry)
        db.session.commit()
        flash("تمت إضافة الحصة الجديدة بنجاح.", "success")
        return redirect(url_for("index"))

    @app.route("/subjects/<int:subject_id>/daily-slots", methods=["POST"])
    def update_daily_slots(subject_id: int):
        subject = Subject.query.get_or_404(subject_id)
        try:
            daily_slots = int(request.form.get("daily_slots", 1))
        except ValueError:
            daily_slots = 1
        subject.daily_slots = max(daily_slots, 1)
        db.session.commit()
        flash(
            f"تم تحديث عدد الحصص اليومية لمادة {subject.name} إلى {subject.daily_slots}.",
            "success",
        )
        return redirect(url_for("index"))

    return app


def _normalize_columns(columns: List[str]) -> Dict[str, str]:
    mapping = {}
    for col in columns:
        lower = col.strip().lower()
        if "trainer" in lower or "مدرب" in lower:
            mapping[col] = "trainer"
        elif "subject" in lower or "مادة" in lower:
            mapping[col] = "subject"
        elif "hour" in lower or "س" in lower:
            mapping[col] = "hours"
        elif "daily" in lower or "حصص" in lower or "يومي" in lower:
            mapping[col] = "daily_slots"
    return mapping


def _process_excel_dataframe(df: pd.DataFrame) -> Dict[str, int]:
    mapping = _normalize_columns(list(df.columns))
    required_columns = {"trainer", "subject", "hours"}
    if required_columns - set(mapping.values()):
        raise ValueError("يجب أن يحتوي الملف على أعمدة المدرب، المادة، الساعات")

    normalized = df.rename(columns=mapping)
    normalized = normalized[[col for col in ["trainer", "subject", "hours", "daily_slots"] if col in normalized.columns]]
    normalized = normalized.dropna()

    trainers_added = set()
    subjects_added = set()

    trainer_rows = normalized.groupby("trainer")

    for trainer_name, group in trainer_rows:
        trainer_name = str(trainer_name).strip()
        if not trainer_name:
            continue
        trainer = Trainer.query.filter_by(name=trainer_name).first()
        if trainer is None:
            trainer = Trainer(name=trainer_name)
            db.session.add(trainer)

        subjects_list = {str(subj).strip() for subj in group["subject"].tolist() if str(subj).strip()}
        hours_sum = int(group["hours"].astype(float).sum())
        if subjects_list:
            current_subjects = set(trainer.list_experience())
            trainer.experience = ", ".join(sorted(current_subjects | subjects_list))
        trainer.weekly_hours = max(trainer.weekly_hours or 0, hours_sum)
        trainers_added.add(trainer_name)

        for _, row in group.iterrows():
            subject_name = str(row["subject"]).strip()
            if not subject_name:
                continue
            hours_value = int(float(row["hours"]))
            subject = Subject.query.filter_by(name=subject_name).first()
            if subject is None:
                subject = Subject(name=subject_name)
                db.session.add(subject)
            subject.hours_per_week = max(subject.hours_per_week or 0, hours_value)
            if "daily_slots" in row.index:
                try:
                    subject.daily_slots = max(int(row["daily_slots"]), 1)
                except (TypeError, ValueError):
                    subject.daily_slots = subject.daily_slots or 1
            subjects_added.add(subject_name)

    db.session.commit()
    return {"trainers": len(trainers_added), "subjects": len(subjects_added)}


def _group_schedule(time_slots: List[Tuple[str, str]]) -> Dict[str, List[Schedule]]:
    grouped: Dict[str, List[Schedule]] = {day: [] for day in DAYS}
    entries = (
        Schedule.query.order_by(
            Schedule.day,
            Schedule.start_time,
        ).all()
    )
    _annotate_entries(entries, time_slots)
    for entry in entries:
        grouped.setdefault(entry.day, []).append(entry)
    return grouped


def _group_schedule_by_trainer(time_slots: List[Tuple[str, str]]) -> Dict[str, List[Schedule]]:
    grouped: Dict[str, List[Schedule]] = {}
    entries = (
        Schedule.query.join(Trainer)
        .order_by(Trainer.name, Schedule.day, Schedule.start_time)
        .all()
    )
    _annotate_entries(entries, time_slots)
    for entry in entries:
        grouped.setdefault(entry.trainer.name, []).append(entry)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def _annotate_entries(entries: List[Schedule], time_slots: List[Tuple[str, str]]):
    start_lookup = {slot[0]: idx for idx, slot in enumerate(time_slots)}
    end_lookup = {slot[1]: idx for idx, slot in enumerate(time_slots)}
    for entry in entries:
        start_idx = start_lookup.get(entry.start_time, 0)
        end_idx = end_lookup.get(entry.end_time, start_idx)
        entry.start_slot_index = start_idx
        entry.duration_slots = max(end_idx - start_idx + 1, 1)


def _detect_conflicts() -> List[Dict[str, object]]:
    conflicts: List[Dict[str, object]] = []
    entries = (
        Schedule.query.join(Trainer)
        .join(Subject)
        .order_by(Schedule.day, Schedule.start_time)
        .all()
    )
    time_slots = get_time_slots()
    _annotate_entries(entries, time_slots)
    entries_by_day: Dict[str, List[Schedule]] = {}
    for entry in entries:
        entries_by_day.setdefault(entry.day, []).append(entry)

    for day, day_entries in entries_by_day.items():
        for i, first in enumerate(day_entries):
            for second in day_entries[i + 1 :]:
                if not _overlaps(first, second):
                    continue
                conflict_type = "تعارض مدرب" if first.trainer_id == second.trainer_id else "تعارض وقت"
                conflicts.append(
                    {
                        "day": day,
                        "type": conflict_type,
                        "first": first,
                        "second": second,
                    }
                )
    return conflicts


def _overlaps(first: Schedule, second: Schedule) -> bool:
    if first.day != second.day:
        return False
    return first.start_time < second.end_time and second.start_time < first.end_time


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
