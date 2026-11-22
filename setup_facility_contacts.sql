-- Refresh the existing facilities table with contacts from the original dataset.
CREATE OR REPLACE TABLE workspace.datathon_silver.gold_india_facilities AS
WITH supported_evidence AS (
  SELECT campus_id, evidence_text, source_url,
    ROW_NUMBER() OVER (PARTITION BY campus_id ORDER BY evidence_id) AS evidence_rank
  FROM workspace.datathon_silver.silver_service_evidence
  WHERE service = 'dialysis'
    AND evidence_status = 'supported'
    AND source_url IS NOT NULL
),
source_rows AS (
  SELECT campus_id, ids.raw_id
  FROM workspace.datathon_silver.silver_facilities
  LATERAL VIEW EXPLODE(source_ids) ids AS raw_id
),
raw_contacts AS (
  SELECT f.campus_id, TRIM(CAST(r.officialPhone AS STRING)) AS primary_phone,
    FROM_JSON(
      GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.phone_numbers)), '$.v'), 'ARRAY<STRING>'
    ) AS alternate_phones
  FROM source_rows f
  JOIN databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities r
    ON f.raw_id = LOWER(TRIM(CAST(r.unique_id AS STRING)))
),
contacts AS (
  SELECT campus_id, TRUE AS is_primary, primary_phone AS phone FROM raw_contacts
  UNION ALL
  SELECT campus_id, FALSE AS is_primary, phone
  FROM raw_contacts LATERAL VIEW EXPLODE(alternate_phones) phones AS phone
),
normalized AS (
  SELECT campus_id, is_primary, CASE
    WHEN digits RLIKE r'^1800[0-9]{6,8}$' THEN digits
    WHEN digits RLIKE r'^91[1-9][0-9]{9}$' THEN CONCAT('+', digits)
    WHEN digits RLIKE r'^0091[1-9][0-9]{9}$' THEN CONCAT('+', SUBSTRING(digits, 3))
    WHEN digits RLIKE r'^0?[1-9][0-9]{9}$' THEN CONCAT('+91', RIGHT(digits, 10))
  END AS phone
  FROM (
    SELECT campus_id, is_primary, REGEXP_REPLACE(phone, r'[^0-9]', '') AS digits
    FROM contacts
    WHERE TRIM(phone) RLIKE r'^\+?[0-9() .-]+$'
  ) digits_only
),
facility_contacts AS (
  SELECT campus_id, CASE
    WHEN COUNT(DISTINCT CASE WHEN is_primary THEN phone END) = 1
      THEN MAX(CASE WHEN is_primary THEN phone END)
    WHEN COUNT(DISTINCT phone) = 1 THEN MAX(phone)
  END AS phone
  FROM normalized
  GROUP BY campus_id
)
SELECT f.campus_id, f.name AS facility_name, f.address_line1, f.pin_clean,
       f.city, f.state, f.latitude, f.longitude,
       f.eligible_for_distance, e.evidence_text, e.source_url, c.phone, f.location_flags
FROM workspace.datathon_silver.silver_facilities f
LEFT JOIN supported_evidence e
  ON f.campus_id = e.campus_id AND e.evidence_rank = 1
LEFT JOIN facility_contacts c ON f.campus_id = c.campus_id;
