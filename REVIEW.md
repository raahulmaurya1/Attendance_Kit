# REVIEW.md

## Defects Found in the Starter Code

The following table documents defects identified during the review of `app/main.py`, including helper functions and API endpoints.

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `create_indexes()` | Only unique indexes are created; additional indexes are needed for frequently used queries. | Run explain on attendance queries with a large dataset and inspect for collection scans. | Add indexes that support the actual filters and sorting used by the endpoints. |
| 2 | `list_attendance()` | Loading all matching attendance records into Python before sorting and pagination is inefficient. | Test with a large attendance collection; unnecessary records are fetched into application memory. | Move filtering, sorting, skipping, and limiting into MongoDB. |
| 3 | `list_attendance()` | The response may not follow the required timestamp and response-field formats. | Compare the returned JSON against the OpenAPI response schema. | Serialize timestamps and fields according to the API contract. |
| 4 | `PATCH /attendance/{emp_code}/{date}` | Correction-history field names do not match the required history schema. | Submit a correction and inspect the stored history and response. | Use the required fields for correction time, changed values, and reason. |
| 5 | `PATCH /attendance/{emp_code}/{date}` | Correction edge cases need validation, including no-op changes and invalid values. | Submit an empty correction or an invalid status and inspect the response. | Validate correction input and handle invalid or unchanged values according to the contract. |
| 6 | `department_trend` | Generating a complete daily trend is difficult when dates have no attendance records. | Query a date range containing gaps or a department with no attendance records. | Use a MongoDB aggregation strategy that generates the required daily rows, including dates without attendance. |
| 7 | `department_trend` | The date densification and range boundaries need verification against the exact requested date range. | Test the first and last dates, weekends, and a range with missing dates. | Ensure the aggregation returns exactly one row per requested calendar day. |
| 8 | `/admin/explain/{endpoint}` | The explain implementation must inspect the actual query or pipeline used by each endpoint, not a simplified substitute. | Compare explain output with the corresponding endpoint's filters and aggregation stages. | Build the explain command from the same query or pipeline used by the endpoint. |
| 9 | `employee_monthly()` | Monthly calculations must correctly handle joining dates, weekdays, and weekend attendance. | Test a mid-month joiner with weekday and weekend attendance records. | Calculate working days from the joining date and count present days using weekdays only, while retaining applicable weekend late and overtime totals. |
| 10 | Attendance calculation helpers | Late arrival, overtime, and working-hour rounding must follow the specified boundary rules exactly. | Test the 10-minute grace period, the 30-minute overtime threshold, and half-day boundaries. | Apply the specified thresholds and `ROUND_HALF_UP` rounding consistently. |

**Note:** The exact line numbers should be added after reviewing the original starter file. Each fix should be confirmed in the final implementation before this review is submitted.

## Items Reviewed but Not Considered Defects

| # | Item reviewed | Why it was not considered a defect |
|---|---|---|
| 1 | Unique index on `employees.emp_code` | This is required to prevent duplicate employee codes. |
| 2 | Unique compound index on `attendance_logs.emp_code` and `attendance_logs.date` | This enforces the required uniqueness of an employee's attendance date. |
| 3 | Storing timestamps as UTC BSON datetime values | This is appropriate when IST is used for attendance-date calculations and API timestamps follow the required epoch-millisecond format. |
| 4 | Treating Monday through Friday as working days | This follows the assignment's rules; no separate holiday calendar is required. |
| 5 | Using MongoDB aggregation for analytics | Database-side aggregation is appropriate for filtering and summarizing large attendance datasets. |

## Review Conclusion

The starter implementation requires verification of API response formats, attendance calculation boundaries, correction history, daily trend generation, and query performance.

The final implementation should be tested against the OpenAPI contract and assignment requirements. No item should be marked fixed until the corresponding code and test results confirm the fix.
