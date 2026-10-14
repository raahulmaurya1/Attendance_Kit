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

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient
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

def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    local_punch = punch_in.astimezone(IST) if punch_in.tzinfo else punch_in

    h, m = map(int, shift_start.split(":"))
    start = local_punch.replace(
        hour=h, minute=m, second=0, microsecond=0
    )

    # For an overnight shift, an early-morning punch
    # belongs to the shift that started the previous day.
    if local_punch.hour * 60 + local_punch.minute < h * 60 + m:
        start -= timedelta(days=1)

    seconds_late = (local_punch - start).total_seconds()

    if seconds_late <= 600:
        return 0

    return int(seconds_late // 60)



def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


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
            local_ts, emp["shift_start"]
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
