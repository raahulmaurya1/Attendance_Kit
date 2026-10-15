# DECISIONS.md

## 1. Indexes
I created a unique index on `employees.emp_code` to prevent duplicate employees and a compound unique index on `attendance_logs(emp_code, date)` to prevent duplicate daily attendance. I considered a standalone index on `status` but rejected it because status has few possible values and may not be selective enough to justify the extra storage and write cost.

## 2. Punch-in Race
Two identical requests may both check for an existing record and find none. Both then try to insert. The unique compound index allows only one insert; MongoDB raises `DuplicateKeyError` for the other request, which the API converts into HTTP 409. This makes the operation race-safe.

## 3. Ties
The leaderboard uses ranking by total late minutes, so employees with equal totals share the same rank and the next rank is skipped, such as 1, 2, 2, 4. Tied employees are ordered by `emp_code`, and the limit is applied after ranking.

## 4. Headcount
The department summary starts from employees and looks up attendance records. Therefore, employees with no logs remain included in headcount, while joining-date filtering excludes employees who joined after the month ends.

## 5. Scaling
For 100 times more data, I would improve query-supporting indexes and verify actual execution plans with MongoDB explain statistics.
