-- Run both statements in the Databricks SQL Editor as the project owner.

CREATE OR REPLACE TABLE workspace.datathon_silver.gold_lucknow_pin_centers AS
WITH coordinates AS (
  SELECT DISTINCT
    TRIM(CAST(pincode AS STRING)) AS pin,
    TRY_CAST(latitude AS DOUBLE) AS lat,
    TRY_CAST(longitude AS DOUBLE) AS lon
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory
  WHERE LOWER(TRIM(district)) = 'lucknow'
    AND LOWER(TRIM(statename)) = 'uttar pradesh'
    AND TRIM(CAST(pincode AS STRING)) RLIKE '^[1-9][0-9]{5}$'
)
SELECT pin, AVG(lat) AS lat, AVG(lon) AS lon
FROM coordinates
WHERE lat BETWEEN 6 AND 38 AND lon BETWEEN 68 AND 98
GROUP BY pin;

CREATE OR REPLACE TABLE workspace.datathon_silver.gold_lucknow_dialysis_facilities AS
WITH evidence AS (
  SELECT
    campus_id, evidence_text, source_url,
    ROW_NUMBER() OVER (PARTITION BY campus_id ORDER BY evidence_id) AS evidence_rank
  FROM workspace.datathon_silver.silver_service_evidence
  WHERE service = 'dialysis'
    AND evidence_status = 'supported'
    AND source_url IS NOT NULL
)
SELECT
  f.campus_id, f.name AS facility_name, f.address_line1, f.pin_clean,
  f.latitude, f.longitude, e.evidence_text, e.source_url
FROM workspace.datathon_silver.silver_facilities f
JOIN evidence e ON f.campus_id = e.campus_id
WHERE f.city_key = 'lucknow'
  AND f.eligible_for_distance = TRUE
  AND f.latitude IS NOT NULL AND f.longitude IS NOT NULL
  AND e.evidence_rank = 1;

SELECT 'PIN centers' AS table_name, COUNT(*) AS row_count
FROM workspace.datathon_silver.gold_lucknow_pin_centers
UNION ALL
SELECT 'Dialysis facilities', COUNT(*)
FROM workspace.datathon_silver.gold_lucknow_dialysis_facilities;