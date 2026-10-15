# HROne Employee Attendance & Analytics API

A RESTful backend API built with **FastAPI and MongoDB** to manage employee records, track attendance, calculate working hours, and generate attendance analytics.

## Features

- **Employee Management:** Create and retrieve employee records.
- **Attendance Tracking:** Record employee punch-in and punch-out times.
- **Attendance Corrections:** Update attendance records through an administrative correction endpoint.
- **Working Hours:** Calculate work hours, late minutes, overtime, and half-day status.
- **Monthly Analytics:** Generate employee attendance statistics for a selected month.
- **Department Analytics:** Summarize attendance by department.
- **Late Arrival Leaderboard:** Rank employees based on late-arrival minutes.
- **Department Attendance Trends:** Generate daily attendance trends and moving averages.
- **Database Health Check:** Verify MongoDB connectivity.
- **Query Explain:** Inspect database query execution plans.
- **Pagination:** Retrieve records using page and page-size parameters.

## Tech Stack

- **Language:** Python
- **Framework:** FastAPI
- **Database:** MongoDB
- **MongoDB Driver:** PyMongo
- **Data Validation:** Pydantic
- **ASGI Server:** Uvicorn
- **Environment Configuration:** python-dotenv

## Project Structure

```text
hrone-attendance-api/
├── app/
│   └── main.py
├── .env
├── .gitignore
├── requirements.txt
├── README.md
├── REVIEW.md
└── DECISIONS.md
```

The structure above represents the main project files; additional files may be present in the repository.

## Prerequisites

Install the following before running the application:

- Python 3.10 or a compatible version supported by your dependencies
- MongoDB running locally or a reachable MongoDB instance
- Git (optional)

## Installation and Setup

### 1. Clone the repository

If the project is hosted on GitHub:

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd hrone-attendance-api
```

Alternatively, open your existing project folder in VS Code.

### 2. Create a virtual environment

**Windows PowerShell:**

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can use the virtual environment's Python executable directly instead.

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

Ensure that `requirements.txt` includes the packages required by the application, such as FastAPI, Uvicorn, PyMongo, and python-dotenv.

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
MONGO_URI=mongodb://127.0.0.1:27017
MONGO_DB=attendance_db
```

- `MONGO_URI`: MongoDB connection URI.
- `MONGO_DB`: Name of the database used by the application.

Make sure MongoDB is running before starting the API.

### 5. Run the application

From the project root, execute:

```powershell
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

- **Base URL:** http://127.0.0.1:8000
- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI schema:** http://127.0.0.1:8000/openapi.json

## API Endpoints

The following endpoints describe the intended API functionality. Check the generated Swagger documentation for the exact request parameters, schemas, and response formats implemented in the application.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Check API and database health |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees with pagination |
| GET | `/employees/{emp_code}/monthly` | Retrieve monthly employee analytics |
| POST | `/attendance/{emp_code}/punch-in` | Record employee punch-in |
| POST | `/attendance/{emp_code}/punch-out` | Record employee punch-out |
| GET | `/attendance` | List attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Correct an attendance record |
| GET | `/analytics/department-summary` | Generate department attendance summaries |
| GET | `/analytics/late-leaderboard` | Retrieve the late-arrival leaderboard |
| GET | `/analytics/department-trend` | Retrieve department attendance trends |
| GET | `/admin/explain/{endpoint}` | Inspect query execution statistics |

## Testing the API

Use the following commands in a Windows PowerShell terminal. Keep the FastAPI server running in a separate terminal.

### 1. Health Check

```powershell
curl.exe http://127.0.0.1:8000/health
```

### 2. Create an Employee

```powershell
curl.exe -X POST "http://127.0.0.1:8000/employees" `
  -H "Content-Type: application/json" `
  -d '{"emp_code":"EMP767285","name":"Rahul Sharma","email":"rahul767285@example.com","department":"Engineering","shift_start":"09:30","shift_end":"18:30","joined_on":"2026-01-15"}'
```

Use a unique employee code and email when creating additional employees.

### 3. Punch-In

```powershell
curl.exe -X POST "http://127.0.0.1:8000/attendance/EMP767285/punch-in" `
  -H "Content-Type: application/json" `
  -d "{}"
```

### 4. Punch-Out

```powershell
curl.exe -X POST "http://127.0.0.1:8000/attendance/EMP767285/punch-out" `
  -H "Content-Type: application/json" `
  -d "{}"
```

These punch-in and punch-out examples assume the implemented endpoints accept an empty JSON body. If the application requires timestamp fields, supply them according to the Swagger schema.

### 5. List Employees

```powershell
curl.exe "http://127.0.0.1:8000/employees?page=1&page_size=20"
```

### 6. Monthly Analytics

```powershell
curl.exe "http://127.0.0.1:8000/employees/EMP767285/monthly?month=2026-10"
```

### 7. Department Summary

```powershell
curl.exe "http://127.0.0.1:8000/analytics/department-summary?month=2026-10"
```

### 8. Late Arrival Leaderboard

```powershell
curl.exe "http://127.0.0.1:8000/analytics/late-leaderboard?month=2026-10"
```

## Attendance Calculation Rules

The application is designed around the following attendance rules:

- **Late Arrival:** A grace period of 10 minutes applies after the scheduled shift start.
- **Overtime:** Overtime is counted when an employee works at least 30 minutes beyond the scheduled shift end.
- **Working Hours:** Calculated from elapsed punch-in and punch-out time and rounded to two decimal places.
- **Half-Day:** An employee is classified as half-day when rounded working hours are below 4.50.
- **Working Days:** Monday through Friday are treated as working days; weekends are excluded from present-day counts.
- **Attendance Date:** Based on the Indian Standard Time (IST) calendar date of punch-in.
- **Monthly Headcount:** Includes employees whose joining date is on or before the end of the selected month.

## Database Design

The application uses two primary MongoDB collections:

### `employees`

Stores employee information, including:

- Employee code
- Name
- Email
- Department
- Shift start and end times
- Joining date

### `attendance_logs`

Stores employee attendance records, including:

- Employee code
- Attendance date
- Punch-in and punch-out timestamps
- Attendance status
- Working hours
- Late-arrival minutes
- Overtime minutes
- Half-day information
- Correction history, where supported

Unique indexes should prevent duplicate employee codes and duplicate attendance records for the same employee and date.

## Error Handling

The API uses standard HTTP status codes, including:

- `200 OK` — Successful request
- `201 Created` — Resource created
- `404 Not Found` — Resource not found
- `409 Conflict` — Duplicate or conflicting resource, where implemented
- `422 Unprocessable Content` — Request validation failed
- `503 Service Unavailable` — Database health check failed

Refer to each endpoint's response schema for its actual behavior.

## Development Notes

- Keep MongoDB credentials and secrets in environment variables.
- Do not commit `.env` or virtual environment folders.
- Use `/docs` to inspect and test API endpoints.
- Review query execution plans to identify database performance issues.
- Verify attendance calculations using boundary cases and overnight shifts.
- Add automated tests before deploying the API.

## License

This project was developed as an employee attendance and analytics API assignment. Add a license if the repository is intended for public distribution.
# Attendance_Kit
