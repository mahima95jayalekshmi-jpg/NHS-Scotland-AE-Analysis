-- NHS Scotland A&E waiting times: SQL version of the checks and analysis.
-- Run `python analysis.py` first to build results/nhs_ae.db, then open it in
-- DB Browser for SQLite (or `sqlite3 results/nhs_ae.db < analysis.sql`).
--
-- AttendanceCategory 'All' already includes 'Unplanned' and 'New planned',
-- so every aggregate filters to 'All' to avoid double counting.
-- Rates are ratios of summed counts, never averages of percentages.


-- ===================================================================
-- 1. Data quality checks
-- ===================================================================

-- 1a. Row count and date range
SELECT COUNT(*)                       AS total_rows,
       COUNT(DISTINCT WeekEndingDate) AS weeks,
       MIN(WeekEndingDate)            AS first_week,
       MAX(WeekEndingDate)            AS last_week
FROM ae_waiting_times;

-- 1b. Missing values in key columns
SELECT SUM(WeekEndingDate IS NULL)             AS missing_week,
       SUM(TreatmentLocation IS NULL)          AS missing_location,
       SUM(NumberOfAttendancesEpisode IS NULL) AS missing_attendances,
       SUM(NumberWithin4HoursEpisode IS NULL)  AS missing_within_4h
FROM ae_waiting_times;

-- 1c. Duplicate site-week-category keys
SELECT WeekEndingDate, TreatmentLocation, AttendanceCategory, COUNT(*) AS records
FROM ae_waiting_times
GROUP BY WeekEndingDate, TreatmentLocation, AttendanceCategory
HAVING COUNT(*) > 1;

-- 1d. Logical consistency: each check should return 0
SELECT
    SUM(NumberWithin4HoursEpisode > NumberOfAttendancesEpisode)                               AS within_4h_gt_attendances,
    SUM(NumberWithin4HoursEpisode + NumberOver4HoursEpisode <> NumberOfAttendancesEpisode)    AS parts_dont_sum,
    SUM(NumberOver8HoursEpisode > NumberOver4HoursEpisode)                                    AS over_8h_gt_over_4h,
    SUM(NumberOver12HoursEpisode > NumberOver8HoursEpisode)                                   AS over_12h_gt_over_8h,
    SUM(NumberOfAttendancesEpisode < 0 OR NumberWithin4HoursEpisode < 0)                      AS negative_counts
FROM ae_waiting_times;


-- ===================================================================
-- 2. Scotland vs NHS Greater Glasgow and Clyde (S08000031)
-- ===================================================================

-- 2a. Weekly four-hour performance
SELECT WeekEndingDate,
       SUM(NumberOfAttendancesEpisode) AS scotland_attendances,
       ROUND(100.0 * SUM(NumberWithin4HoursEpisode) / SUM(NumberOfAttendancesEpisode), 1) AS scotland_pct,
       ROUND(100.0 * SUM(CASE WHEN HBT = 'S08000031' THEN NumberWithin4HoursEpisode END)
                   / SUM(CASE WHEN HBT = 'S08000031' THEN NumberOfAttendancesEpisode END), 1) AS ggc_pct
FROM ae_waiting_times
WHERE AttendanceCategory = 'All'
GROUP BY WeekEndingDate
ORDER BY WeekEndingDate DESC;

-- 2b. Annual performance and long waits, Scotland
SELECT SUBSTR(WeekEndingDate, 1, 4)    AS year,
       COUNT(DISTINCT WeekEndingDate)  AS weeks,
       SUM(NumberOfAttendancesEpisode) AS attendances,
       ROUND(100.0 * SUM(NumberWithin4HoursEpisode) / SUM(NumberOfAttendancesEpisode), 1) AS pct_within_4h,
       ROUND(100.0 * SUM(NumberOver8HoursEpisode)   / SUM(NumberOfAttendancesEpisode), 2) AS pct_over_8h,
       ROUND(100.0 * SUM(NumberOver12HoursEpisode)  / SUM(NumberOfAttendancesEpisode), 2) AS pct_over_12h
FROM ae_waiting_times
WHERE AttendanceCategory = 'All'
GROUP BY year
ORDER BY year;


-- ===================================================================
-- 3. NHS GGC hospitals, with names from the official lookup
-- ===================================================================

-- 3a. Latest week
SELECT a.TreatmentLocation,
       COALESCE(h.HospitalName, 'Unknown - check lookup') AS hospital,
       SUM(a.NumberOfAttendancesEpisode) AS attendances,
       ROUND(100.0 * SUM(a.NumberWithin4HoursEpisode) / SUM(a.NumberOfAttendancesEpisode), 1) AS pct_within_4h
FROM ae_waiting_times a
LEFT JOIN hospital_lookup h ON h.HospitalCode = a.TreatmentLocation
WHERE a.AttendanceCategory = 'All'
  AND a.HBT = 'S08000031'
  AND a.WeekEndingDate = (SELECT MAX(WeekEndingDate) FROM ae_waiting_times)
GROUP BY a.TreatmentLocation, h.HospitalName
ORDER BY pct_within_4h;

-- 3b. Last 13 weeks, with 12-hour waits (window function ranks sites)
WITH recent AS (
    SELECT DISTINCT WeekEndingDate
    FROM ae_waiting_times
    ORDER BY WeekEndingDate DESC
    LIMIT 13
),
sites AS (
    SELECT a.TreatmentLocation,
           h.HospitalName,
           SUM(a.NumberOfAttendancesEpisode) AS attendances,
           100.0 * SUM(a.NumberWithin4HoursEpisode) / SUM(a.NumberOfAttendancesEpisode) AS pct_within_4h,
           100.0 * SUM(a.NumberOver12HoursEpisode)  / SUM(a.NumberOfAttendancesEpisode) AS pct_over_12h
    FROM ae_waiting_times a
    JOIN recent r ON r.WeekEndingDate = a.WeekEndingDate
    LEFT JOIN hospital_lookup h ON h.HospitalCode = a.TreatmentLocation
    WHERE a.AttendanceCategory = 'All' AND a.HBT = 'S08000031'
    GROUP BY a.TreatmentLocation, h.HospitalName
)
SELECT RANK() OVER (ORDER BY pct_within_4h) AS rank_worst_first,
       TreatmentLocation, HospitalName, attendances,
       ROUND(pct_within_4h, 1) AS pct_within_4h,
       ROUND(pct_over_12h, 2)  AS pct_over_12h
FROM sites
ORDER BY rank_worst_first;
