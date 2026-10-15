"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import calendar
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient, DESCENDING
from pymongo.errors import DuplicateKeyError
import re

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def create_indexes():
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employees_emp_code"
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_date"
    )



# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    shift_end: str
) -> int:
    local_punch = (
        punch_in.astimezone(IST)
        if punch_in.tzinfo
        else punch_in
    )

    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    punch_minutes = local_punch.hour * 60 + local_punch.minute

    # Overnight shift: early-morning punch belongs
    # to the shift that started the previous day.
    if end_minutes <= start_minutes and punch_minutes < end_minutes:
        shift_start_time = (
            local_punch.replace(
                hour=start_hour,
                minute=start_minute,
                second=0,
                microsecond=0
            ) - timedelta(days=1)
        )
    else:
        shift_start_time = local_punch.replace(
            hour=start_hour,
            minute=start_minute,
            second=0,
            microsecond=0
        )

    seconds_late = (
        local_punch - shift_start_time
    ).total_seconds()

    # Early arrival or arrival within the 10-minute grace period.
    if seconds_late <= 600:
        return 0

    return int(seconds_late // 60)



from decimal import Decimal, ROUND_HALF_UP

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = Decimal(str((punch_out - punch_in).total_seconds()))
    hours = (seconds / Decimal("3600")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )
    return float(hours)




def compute_overtime(
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str
) -> int:
    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute

    shift_end_date = datetime.fromisoformat(date_str)

    # Overnight shift ends the next day.
    if end_minutes <= start_minutes:
        shift_end_date += timedelta(days=1)

    shift_end_time = shift_end_date.replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0,
        tzinfo=IST
    )

    local_punch_out = (
        punch_out.astimezone(IST)
        if punch_out.tzinfo
        else punch_out.replace(tzinfo=IST)
    )

    overtime_seconds = (
        local_punch_out - shift_end_time
    ).total_seconds()

    # Overtime is counted only if at least 30 minutes.
    if overtime_seconds < 1800:
        return 0

    return int(overtime_seconds // 60)



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(
        default="09:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    shift_end: str = Field(
        default="18:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("joined_on must be YYYY-MM-DD")
        return value

    @field_validator("shift_end")
    @classmethod
    def validate_shift_end(cls, value, info):
        shift_start = info.data.get("shift_start")
        if shift_start == value:
            raise ValueError("shift_start and shift_end must differ")
        return value




class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(
        default=None,
        ge=100000000000,
        le=4102444800000
    )
    status: str = "PRESENT"

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value
        if type(value) is not int:
            raise ValueError("punched_at must be epoch milliseconds")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value not in {"PRESENT", "WFH", "ON_DUTY"}:
            raise ValueError("Invalid punch-in status")
        return value


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(
        default=None,
        ge=100000000000,
        le=4102444800000
    )

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value
        if type(value) is not int:
            raise ValueError("punched_at must be epoch milliseconds")
        return value


class AttendanceCorrectionIn(BaseModel):
    punch_in: Optional[int] = Field(
        default=None,
        ge=100000000000,
        le=4102444800000
    )
    punch_out: Optional[int] = Field(
        default=None,
        ge=100000000000,
        le=4102444800000
    )
    status: Optional[str] = None
    reason: str = Field(min_length=1)

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_timestamp(cls, value):
        if value is None:
            return value
        if type(value) is not int:
            raise ValueError("Timestamp must be integer epoch milliseconds")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise ValueError("Invalid attendance status")
        return value


@app.patch("/attendance/{emp_code}/{date}")
def correct_attendance(
    emp_code: str,
    date: str,
    body: AttendanceCorrectionIn
):
    from datetime import date as date_type
    from decimal import Decimal, ROUND_HALF_UP

    try:
        date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="date must be YYYY-MM-DD"
        )

    if body.punch_in is None and body.punch_out is None and body.status is None:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one field to correct"
        )

    employee = db.employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date
    })
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    changes = body.model_dump(exclude_unset=True)
    changes.pop("reason", None)

    old_values = {}
    updates = {}

    for field in ("punch_in", "punch_out"):
        if field in changes and changes[field] is not None:
            old_values[field] = record.get(field)
            updates[field] = datetime.fromtimestamp(
                changes[field] / 1000,
                tz=timezone.utc
            ).replace(tzinfo=None)

    if "status" in changes and changes["status"] is not None:
        old_values["status"] = record.get("status")
        updates["status"] = changes["status"]

    final_punch_in = updates.get("punch_in", record.get("punch_in"))
    final_punch_out = updates.get("punch_out", record.get("punch_out"))

    if final_punch_in is not None and final_punch_out is not None:
        if final_punch_out <= final_punch_in:
            raise HTTPException(
                status_code=422,
                detail="punch_out must be after punch_in"
            )

        duration = Decimal(str(
            (final_punch_out - final_punch_in).total_seconds()
        ))
        hours = (duration / Decimal("3600")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        updates["work_hours"] = float(hours)
        updates["half_day"] = float(hours) < 4.50

        updates["overtime_minutes"] = compute_overtime(
            final_punch_out.replace(tzinfo=timezone.utc).astimezone(IST),
            employee["shift_start"],
            employee["shift_end"],
            record["date"]
        )

        local_in = final_punch_in.replace(tzinfo=timezone.utc).astimezone(IST)
        updates["late_minutes"] = compute_late_minutes(
            local_in,
            employee["shift_start"],
            employee["shift_end"]
        )

    history_entry = {
        "reason": body.reason,
        "changed_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "old_values": old_values
    }

    result = db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": updates,
            "$push": {"history": history_entry}
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]},
        {"_id": 0}
    )

    for field in ("punch_in", "punch_out"):
        if isinstance(updated.get(field), datetime):
            updated[field] = int(
                updated[field].replace(tzinfo=timezone.utc).timestamp() * 1000
            )

    for entry in updated.get("history", []):
        if isinstance(entry.get("changed_at"), datetime):
            entry["changed_at"] = int(
                entry["changed_at"].replace(tzinfo=timezone.utc).timestamp() * 1000
            )
        for field in ("punch_in", "punch_out"):
            if isinstance(entry.get("old_values", {}).get(field), datetime):
                entry["old_values"][field] = int(
                    entry["old_values"][field].replace(tzinfo=timezone.utc).timestamp() * 1000
                )

    return updated

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="MongoDB unavailable"
        )




@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    doc.pop("_id", None)
    doc["created_at"] = int(
        doc["created_at"].timestamp() * 1000
    )
    return doc



@app.get("/employees")


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = {}

    if department:
        query["department"] = department

    total = db.employees.count_documents(query)

    skip = (page - 1) * page_size

    items = list(
        db.employees.find(query, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    for employee in items:
        if isinstance(employee.get("created_at"), datetime):
            created_at = employee["created_at"].replace(
                tzinfo=timezone.utc
            )
            employee["created_at"] = int(
                created_at.timestamp() * 1000
            )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
):
    employee = db.employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    year, month_number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    month_start = f"{month}-01"
    month_end = f"{month}-{last_day:02d}"

    joined_on = employee["joined_on"]
    effective_start = max(joined_on, month_start)

    working_days = 0
    if effective_start <= month_end:
        current = date.fromisoformat(effective_start)
        end_date = date.fromisoformat(month_end)

        while current <= end_date:
            if current.weekday() < 5:
                working_days += 1
            current += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": month_start, "$lte": month_end}
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    {"$lt": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 7]},
                                    {"$gt": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 1]}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}
                },
                "late_count": {
                    "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"}
            }
        }
    ]

    result = list(db.attendance_logs.aggregate(pipeline))
    summary = result[0] if result else {}

    present_days = summary.get("present_days", 0)
    attendance_pct = None
    if working_days > 0:
        attendance_pct = float(
            (Decimal(str(present_days)) * Decimal("100") / Decimal(str(working_days)))
            .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": summary.get("leave_days", 0),
        "late_count": summary.get("late_count", 0),
        "total_late_minutes": summary.get("total_late_minutes", 0),
        "total_overtime_minutes": summary.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct
    }



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    if body.punched_at is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        )

    # Truncate to whole seconds, then convert to IST.
    ts = ts.replace(microsecond=0)
    local_ts = ts.astimezone(IST)
    attendance_date = local_ts.date().isoformat()

    # Store the instant as a UTC BSON datetime.
    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts.replace(tzinfo=None),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
    local_ts,
    emp["shift_start"],
    emp["shift_end"]
),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this date"
        )

    # Return epoch milliseconds; never expose MongoDB _id.
    doc.pop("_id", None)
    doc["punch_in"] = int(ts.timestamp() * 1000)
    return doc


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    if body.punched_at is None:
        punch_out_time = datetime.now(timezone.utc)
    else:
        punch_out_time = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        )

    punch_out_time = punch_out_time.replace(microsecond=0)

    # Find the latest open attendance record before punch-out.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$ne": None, "$lte": punch_out_time.replace(tzinfo=None)},
            "punch_out": None,
        },
        sort=[("punch_in", -1)]
    )

    if not record:
        raise HTTPException(
            status_code=404,
            detail="No open attendance record found"
        )

    punch_in_time = record["punch_in"].replace(tzinfo=timezone.utc)

    if punch_out_time <= punch_in_time:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in"
        )

    duration_seconds = (
        punch_out_time - punch_in_time
    ).total_seconds()

    # Round work hours to 2 decimal places, half-up.
    from decimal import Decimal, ROUND_HALF_UP

    work_hours = float(
        (Decimal(str(duration_seconds)) / Decimal("3600"))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )

    local_out = punch_out_time.astimezone(IST)
    shift_start = emp["shift_start"]
    shift_end = emp["shift_end"]

    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    shift_start_minutes = start_hour * 60 + start_minute
    shift_end_minutes = end_hour * 60 + end_minute

    shift_end_date = record["date"]

    if shift_end_minutes <= shift_start_minutes:
        # Overnight shift ends on the next calendar day.
        from datetime import date, timedelta as td

        shift_end_date = (
            date.fromisoformat(record["date"]) + td(days=1)
        ).isoformat()

    shift_end_dt = datetime.fromisoformat(
        shift_end_date
    ).replace(
        hour=end_hour,
        minute=end_minute,
        tzinfo=IST
    )

    overtime_seconds = (
        local_out - shift_end_dt
    ).total_seconds()

    overtime_minutes = (
        int(overtime_seconds // 60)
        if overtime_seconds >= 30 * 60
        else 0
    )

    half_day = work_hours < 4.50

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": punch_out_time.replace(tzinfo=None),
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        }
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance record was already updated"
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]},
        {"_id": 0}
    )

    updated["punch_in"] = int(
        punch_in_time.timestamp() * 1000
    )
    updated["punch_out"] = int(
        punch_out_time.timestamp() * 1000
    )

    return updated


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #

@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None
):
    year, month_number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    month_start = f"{month}-01"
    month_end = f"{month}-{last_day:02d}"

    employee_match = {"joined_on": {"$lte": month_end}}
    if department:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$gte": ["$date", month_start]},
                                    {"$lte": ["$date", month_end]}
                                ]
                            }
                        }
                    },
                    {
                        "$addFields": {
                            "_weekday": {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date"
                                    }
                                }
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_days": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                                {"$gte": ["$_weekday", 2]},
                                                {"$lte": ["$_weekday", 6]}
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$eq": ["$half_day", True]},
                                                0.5, 1
                                            ]
                                        },
                                        0
                                    ]
                                }
                            },
                            "work_hours_sum": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                                {"$ne": ["$work_hours", None]}
                                            ]
                                        },
                                        "$work_hours", 0
                                    ]
                                }
                            },
                            "work_hours_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                                {"$ne": ["$work_hours", None]}
                                            ]
                                        },
                                        1, 0
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": ["$late_minutes", 0]}, 1, 0
                                    ]
                                }
                            },
                            "total_late_minutes": {"$sum": "$late_minutes"},
                            "leave_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "LEAVE"]}, 1, 0
                                    ]
                                }
                            },
                            "on_duty_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "ON_DUTY"]}, 1, 0
                                    ]
                                }
                            }
                        }
                    }
                ],
                "as": "attendance"
            }
        },
        {
            "$unwind": {
                "path": "$attendance",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_days": {
                    "$sum": {"$ifNull": ["$attendance.present_days", 0]}
                },
                "work_hours_sum": {
                    "$sum": {"$ifNull": ["$attendance.work_hours_sum", 0]}
                },
                "work_hours_count": {
                    "$sum": {"$ifNull": ["$attendance.work_hours_count", 0]}
                },
                "late_count": {
                    "$sum": {"$ifNull": ["$attendance.late_count", 0]}
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$attendance.total_late_minutes", 0]}
                },
                "leave_count": {
                    "$sum": {"$ifNull": ["$attendance.leave_count", 0]}
                },
                "on_duty_count": {
                    "$sum": {"$ifNull": ["$attendance.on_duty_count", 0]}
                }
            }
        },
        {"$sort": {"_id": 1}}
    ]

    results = list(db.employees.aggregate(pipeline))
    items = []

    for row in results:
        count = row["work_hours_count"]
        avg_hours = None

        if count:
            avg_hours = float(
                (Decimal(str(row["work_hours_sum"])) / Decimal(str(count)))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )

        items.append({
            "department": row["_id"],
            "headcount": row["headcount"],
            "present_days": row["present_days"],
            "avg_work_hours": avg_hours,
            "late_count": row["late_count"],
            "total_late_minutes": row["total_late_minutes"],
            "leave_count": row["leave_count"],
            "on_duty_count": row["on_duty_count"]
        })

    return {"month": month, "items": items}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None
):
    year, month_number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    month_start = f"{month}-01"
    month_end = f"{month}-{last_day:02d}"

    pipeline = [
        {
            "$match": {
                "date": {"$gte": month_start, "$lte": month_end},
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1}
            }
        },
        {
            "$match": {"total_late_minutes": {"$gt": 0}}
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1
                },
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items
    }


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to")
):
    from datetime import date, datetime, time, timedelta, timezone
    from decimal import Decimal, ROUND_HALF_UP

    try:
        start_date = date.fromisoformat(from_date)
        end_date = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates must use YYYY-MM-DD")

    if start_date.isoformat() != from_date or end_date.isoformat() != to_date:
        raise HTTPException(status_code=422, detail="Dates must use YYYY-MM-DD")

    days = (end_date - start_date).days + 1
    if days < 1 or days > 92:
        raise HTTPException(status_code=422, detail="Date range must be 1 to 92 days")

    if not db.employees.find_one({"department": department}):
        raise HTTPException(status_code=404, detail="Department not found")

    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": from_date,
                    "$lte": to_date
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {
            "$addFields": {
                "_trend_date": {
                    "$dateFromString": {"dateString": "$date"}
                }
            }
        },
        {
            "$group": {
                "_id": "$_trend_date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                }
            }
        },
        {"$project": {"_id": 0, "date": "$_id", "present_count": 1, "late_count": 1}},
        {
            "$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_dt, end_dt]
                }
            }
        },
        {
            "$set": {
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$date",
                        "timezone": "UTC"
                    }
                },
                "present_count": {"$ifNull": ["$present_count", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]}
            }
        },
        {
            "$set": {
                "is_working_day": {
                    "$and": [
                        {"$gte": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 2]},
                        {"$lte": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, 6]}
                    ]
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"trend_date": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$department", department]},
                                    {"$lte": ["$joined_on", "$$trend_date"]}
                                ]
                            }
                        }
                    },
                    {"$count": "count"}
                ],
                "as": "headcount_result"
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$headcount_result.count", 0]},
                        0
                    ]
                }
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                        {"$divide": ["$present_count", "$headcount"]},
                        None
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]}
                    }
                }
            }
        },
        {"$sort": {"date": 1}},
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1
            }
        }
    ]

    rows = list(db.attendance_logs.aggregate(pipeline))
    items = []

    def round_half_up(value):
        if value is None:
            return None
        return float(
            Decimal(str(value)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP
            )
        )

    for row in rows:
        row["attendance_rate"] = round_half_up(row.get("attendance_rate"))
        row["moving_avg_7d"] = round_half_up(row.get("moving_avg_7d"))
        items.append(row)

    return {"department": department, "items": items}


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    if endpoint not in {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    }:
        raise HTTPException(status_code=422, detail="Unsupported endpoint")

    if endpoint == "attendance_list":
        query = {}
        if emp_code:
            query["emp_code"] = emp_code
        if status:
            query["status"] = status
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to

        explanation = db.command({
            "explain": {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1},
                "skip": (page - 1) * page_size,
                "limit": page_size
            },
            "verbosity": "executionStats"
        })
        collection = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required"
            )
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="Invalid month")

        last_day = calendar.monthrange(
            int(month[:4]), int(month[5:7])
        )[1]

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": f"{month}-01",
                        "$lte": f"{month}-{last_day:02d}"
                    }
                }
            },
            {"$group": {"_id": "$emp_code", "records": {"$sum": 1}}}
        ]
        explanation = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            "verbosity": "executionStats"
        })
        collection = "attendance_logs"

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="Invalid month")

        last_day = calendar.monthrange(
            int(month[:4]), int(month[5:7])
        )[1]
        employee_filter = {}
        if department:
            employee_filter["department"] = department
        employee_filter["joined_on"] = {
            "$lte": f"{month}-{last_day:02d}"
        }

        explanation = db.command({
            "explain": {
                "find": "employees",
                "filter": employee_filter
            },
            "verbosity": "executionStats"
        })
        collection = "employees"

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(status_code=422, detail="Invalid month")

        last_day = calendar.monthrange(
            int(month[:4]), int(month[5:7])
        )[1]
        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": f"{month}-01",
                        "$lte": f"{month}-{last_day:02d}"
                    },
                    "late_minutes": {"$gt": 0}
                }
            },
            {"$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"}
            }},
            {"$sort": {"total_late_minutes": -1}},
            {"$limit": limit}
        ]
        explanation = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            "verbosity": "executionStats"
        })
        collection = "attendance_logs"

    else:
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from and to are required"
            )
        if from_date > to_date:
            raise HTTPException(status_code=422, detail="Invalid date range")

        pipeline = [
            {
                "$match": {
                    "date": {"$gte": from_date, "$lte": to_date}
                }
            },
            {"$sort": {"date": 1}}
        ]
        explanation = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            "verbosity": "executionStats"
        })
        collection = "attendance_logs"

    return {
        "endpoint": endpoint,
        "collection": collection,
        "explain": explanation
    }
