from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Tuple

from models import Schedule, Subject, Trainer, db

DAYS: Sequence[str] = ("الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس")
START_TIME = "08:00"
SLOTS_PER_DAY = 6
SLOT_MINUTES = 50
BREAK_MINUTES = 10


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _generate_time_slots() -> List[Tuple[str, str]]:
    start_dt = datetime.strptime(START_TIME, "%H:%M")
    slots: List[Tuple[str, str]] = []
    current = start_dt
    for _ in range(SLOTS_PER_DAY):
        end_dt = current + timedelta(minutes=SLOT_MINUTES)
        slots.append((current.strftime("%H:%M"), end_dt.strftime("%H:%M")))
        current = end_dt + timedelta(minutes=BREAK_MINUTES)
    return slots


def _trainer_subjects(trainer: Trainer) -> List[str]:
    return [_normalize(name) for name in trainer.list_experience()]


def _block_available(
    day: str,
    slot_index: int,
    block_size: int,
    trainer_id: int,
    occupancy: Dict[Tuple[str, int], bool],
    trainer_busy: Dict[Tuple[int, str, int], bool],
) -> bool:
    for offset in range(block_size):
        current_index = slot_index + offset
        if occupancy.get((day, current_index)):
            return False
        if trainer_busy.get((trainer_id, day, current_index)):
            return False
    return True


def auto_schedule(db_session) -> Dict[str, object]:
    """Create an automatic schedule distribution.

    Returns
    -------
    dict with keys `created` and `warnings`.
    """

    time_slots = get_time_slots()
    slots_per_day = len(time_slots)
    total_slots = len(DAYS) * slots_per_day
    occupancy: Dict[Tuple[str, int], bool] = {}
    trainer_busy: Dict[Tuple[int, str, int], bool] = {}
    created = 0
    warnings: List[str] = []

    # Clear previous schedule before re-populating
    db_session.query(Schedule).delete()
    db_session.commit()

    trainers = Trainer.query.all()
    subjects = Subject.query.filter(Subject.hours_per_week > 0).all()

    if not trainers:
        warnings.append("لا يوجد مدربون مسجلون لإنشاء جدول.")
        return {"created": created, "warnings": warnings}

    if not subjects:
        warnings.append("لا توجد مواد بساعات محددة لإنشاء جدول.")
        return {"created": created, "warnings": warnings}

    trainer_profiles = {
        trainer.id: {
            "id": trainer.id,
            "name": trainer.name,
            "capacity": max(trainer.weekly_hours, 0),
            "assigned": 0,
            "subjects": set(_trainer_subjects(trainer)),
        }
        for trainer in trainers
    }

    subject_plan = sorted(
        subjects,
        key=lambda subj: (subj.hours_per_week, subj.name.lower()),
        reverse=True,
    )

    slot_cursor = 0

    for subject in subject_plan:
        total_slots_needed = max(int(subject.hours_per_week), 0)
        block_size = max(int(subject.daily_slots or 1), 1)
        slots_remaining = total_slots_needed

        if slots_remaining == 0:
            continue

        eligible_trainers = [
            profile
            for profile in trainer_profiles.values()
            if _normalize(subject.name) in profile["subjects"]
        ]

        if not eligible_trainers:
            warnings.append(
                f"لا يوجد مدرب مؤهل للمادة {subject.name}، لم يتم جدولة الحصص المطلوبة."
            )
            continue

        # Ensure trainers with remaining capacity get priority
        eligible_trainers.sort(key=lambda profile: profile["assigned"])

        subject_day_usage: Dict[str, bool] = {}

        while slots_remaining > 0:
            placed = False
            # choose trainer with least load capable of teaching
            eligible_trainers.sort(key=lambda profile: profile["assigned"])
            trainer_choice = next(
                (
                    profile
                    for profile in eligible_trainers
                    if profile["assigned"] < profile["capacity"]
                ),
                None,
            )

            if trainer_choice is None:
                warnings.append(
                    f"تم استنفاد نصاب المدربين لمادة {subject.name} قبل إكمال جميع الحصص."
                )
                break

            block_size_needed = min(block_size, slots_remaining)

            for attempt in range(total_slots):
                offset = (slot_cursor + attempt) % total_slots
                day_index, slot_index = divmod(offset, slots_per_day)
                day = DAYS[day_index]
                if slot_index + block_size_needed > slots_per_day:
                    continue

                if subject_day_usage.get(day):
                    continue

                if not _block_available(
                    day,
                    slot_index,
                    block_size_needed,
                    trainer_choice["id"],
                    occupancy,
                    trainer_busy,
                ):
                    continue

                schedule_entry = Schedule(
                    trainer_id=trainer_choice["id"],
                    subject_id=subject.id,
                    day=day,
                    start_time=time_slots[slot_index][0],
                    end_time=time_slots[slot_index + block_size_needed - 1][1],
                )
                db_session.add(schedule_entry)
                for offset_index in range(block_size_needed):
                    current_index = slot_index + offset_index
                    occupancy[(day, current_index)] = True
                    trainer_busy[(trainer_choice["id"], day, current_index)] = True

                subject_day_usage[day] = True
                trainer_choice["assigned"] += block_size_needed
                slots_remaining -= block_size_needed
                created += 1
                slot_cursor = (offset + block_size_needed) % total_slots
                placed = True
                break

            if not placed:
                warnings.append(
                    f"لا توجد فترات زمنية كافية للمادة {subject.name} لتغطية جميع الحصص."
                )
                break

    db_session.commit()
    return {"created": created, "warnings": warnings}


def get_time_slots() -> List[Tuple[str, str]]:
    """Return the canonical list of time slots used across the app."""

    return _generate_time_slots()
