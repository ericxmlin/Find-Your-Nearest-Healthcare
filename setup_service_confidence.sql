CREATE OR REPLACE TABLE workspace.datathon_silver.gold_india_service_confidence AS
WITH service_patterns AS (
  SELECT * FROM VALUES
    ('dialysis', r'\b(?:ha?emodialysis|(?:peritoneal )?dialysis)\b', r'\bnephrology\b'),
    ('mri', r'\b(?:mri|magnetic resonance imaging)\b', NULL),
    ('ct_scan', r'\b(?:ct[ -]+(?:scans?|scanners?)|computed tomography)\b', NULL),
    ('icu', r'\b(?:icu|intensive care units?)\b', NULL),
    ('nicu', r'\b(?:nicu|neonatal intensive care units?)\b', r'\bneonatology\b'),
    ('emergency_care', r'\b(?:emergency (?:department|room|services?|care|unit)|accident and emergency)\b', NULL),
    ('c_section', r'\b(?:c[ -]sections?|caesarean(?: section| delivery)?|cesarean(?: section| delivery)?)\b', NULL),
    ('cardiac_surgery', r'\b(?:cardiac surgery|heart surgery|open[ -]heart surgery|coronary artery bypass|cabg)\b', r'\b(?:cardiothoracic surgery|cardiology)\b'),
    ('burn_care', r'\b(?:burns? (?:unit|care|cent(?:er|re)))\b', NULL),
    ('chemotherapy', r'\bchemotherapy\b', NULL),
    ('radiotherapy', r'\b(?:radiotherapy|radiation therapy)\b', NULL),
    ('kidney_transplant', r'\b(?:kidney|renal) transplant(?:ation)?\b', NULL)
    AS p(service, term, related_specialty)
),
facility_ids AS (
  SELECT f.campus_id, ids.raw_id,
    COALESCE(ARRAY_CONTAINS(f.location_flags, 'conflicting_source_id_variants'), FALSE)
      OR COALESCE(ARRAY_CONTAINS(f.location_flags, 'mixed_facility_and_address'), FALSE)
      AS attribution_conflict
  FROM workspace.datathon_silver.silver_facilities f
  LATERAL VIEW EXPLODE(f.source_ids) ids AS raw_id
),
fields AS (
  SELECT f.campus_id, f.raw_id, f.attribution_conflict, fields.field_name, fields.field_value,
    GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.source_urls)), '$.v') AS source_urls_json,
    NULLIF(TRIM(REGEXP_REPLACE(LOWER(CAST(r.name AS STRING)), r'\s+', ' ')), '') AS facility_name
  FROM facility_ids f
  JOIN databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities r
    ON f.raw_id = LOWER(TRIM(CAST(r.unique_id AS STRING)))
  LATERAL VIEW STACK(5,
    'capability', GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.capability)), '$.v'),
    'procedure', GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.procedure)), '$.v'),
    'description', GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.description)), '$.v'),
    'equipment', GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.equipment)), '$.v'),
    'specialties', GET_JSON_OBJECT(TO_JSON(NAMED_STRUCT('v', r.specialties)), '$.v')
  ) fields AS field_name, field_value
),
excerpts AS (
  SELECT DISTINCT f.campus_id, f.raw_id, f.attribution_conflict, f.field_name, f.facility_name, f.source_urls_json,
    TRIM(claims.excerpt) AS excerpt
  FROM fields f
  LATERAL VIEW EXPLODE(COALESCE(
    FROM_JSON(f.field_value, 'ARRAY<STRING>'), ARRAY(f.field_value)
  )) items AS item
  LATERAL VIEW EXPLODE(SPLIT(item, r'(?<=[!?])\s+|(?<=\.)\s+(?=[A-Z])|[;\r\n]+')) claims AS excerpt
  WHERE TRIM(claims.excerpt) <> ''
),
service_text AS (
  SELECT *,
    CASE WHEN facility_name IS NULL THEN LOWER(excerpt)
      ELSE REGEXP_REPLACE(
        REGEXP_REPLACE(LOWER(excerpt), r'\s+', ' '),
        CONCAT(r'(?<![\p{L}\p{N}])\Q', facility_name, r'\E(?![\p{L}\p{N}])'),
        ' '
      )
    END AS claim_text
  FROM excerpts
),
normalized AS (
  SELECT *,
    REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(claim_text,
      r'\b(?:pet|spect)\s*[-/–]?\s*ct(?:[ -]+(?:scans?|scanners?))?\b', ' '),
      r'\b(?:neonatal|pediatric|paediatric) intensive care units?\b', ' '),
      r'\bct[ -]+(?:scans?|scanners?)\s+simulators?\b|\bct[ -]+simulation\b', ' ') AS general_text
  FROM service_text
),
candidates AS (
  SELECT n.*, p.service, p.term, p.related_specialty,
    CASE WHEN p.service IN ('ct_scan', 'icu') THEN n.general_text ELSE n.claim_text END AS claim
  FROM normalized n CROSS JOIN service_patterns p
),
classified AS (
  SELECT *,
    CASE
      WHEN attribution_conflict THEN 'attribution'
      WHEN claim RLIKE CONCAT(r'(?:\bno\s+|\bwithout\s+|\b(?:does|do|did) not (?:offer|provide|perform)\s+)', term)
        OR claim RLIKE CONCAT(term, r'\s+(?:(?:is|are)\s+)?(?:not (?:currently )?available|unavailable|not offered|not provided)\b')
        THEN 'negative'
      WHEN claim RLIKE r'\b(?:formerly|previously|historical|used to|discontinued|no longer|expired|closed permanently)\b'
        OR TRY_CAST(REGEXP_EXTRACT(claim,
          r'\b(?:expires|expired|valid until|valid through)\s+(?:on\s+)?(\d{4}-\d{2}-\d{2})\b', 1) AS DATE) < CURRENT_DATE()
        THEN 'historical'
      WHEN claim RLIKE r'\b(?:refer(?:s|red|ring)?\s+(?:patients?|to|for|elsewhere|out)|referrals?\s+(?:to|for|only)|transferred\s+(?:to|for|elsewhere))\b'
        OR claim RLIKE r'\b(?:planned|proposed|coming soon|under construction|training|workshop|course|research only)\b'
        THEN 'referral_or_planned'
      WHEN field_name = 'equipment' THEN 'equipment'
      WHEN field_name = 'specialties' THEN 'specialty'
      WHEN claim RLIKE r'\b(?:machine|scanner|equipment|simulator)s?\b' THEN 'equipment'
      WHEN claim RLIKE CONCAT(r'\b(?:offers?|provides?|performs?|conducts?|administers?|operates?|delivers?|offering|providing)\b[^.!?]{0,70}', term)
        OR claim RLIKE CONCAT(term, r'\s+(?:(?:services?|treatments?)\s+)?(?:is |are )?(?:available|offered|provided|performed|operational)\b')
        OR (field_name IN ('procedure', 'capability')
          AND claim RLIKE CONCAT(r'^\s*(?:advanced |routine |diagnostic )?', term, r'(?:\s+(?:procedures?|services?|treatments?|units?|centres?|centers?))?\s*[.!]?\s*$'))
        THEN 'direct'
      ELSE 'mention'
    END AS reason
  FROM candidates
  WHERE claim RLIKE term
     OR (field_name = 'specialties' AND claim_text RLIKE related_specialty)
),
summary AS (
  SELECT campus_id, service,
    MIN(CASE WHEN reason = 'direct' THEN NAMED_STRUCT(
      'excerpt', excerpt, 'field', field_name, 'raw_id', raw_id, 'urls', source_urls_json
    ) END) AS direct_example
  FROM classified
  GROUP BY campus_id, service
),
ranked AS (
  SELECT c.*, s.direct_example,
    CASE
      WHEN c.reason = 'negative' AND s.direct_example IS NOT NULL THEN 'conflict'
      WHEN c.reason = 'negative' THEN 'negative'
      ELSE c.reason
    END AS evidence_reason,
    ROW_NUMBER() OVER (
      PARTITION BY c.campus_id, c.service
      ORDER BY CASE c.reason
        WHEN 'attribution' THEN 0 WHEN 'negative' THEN 1 WHEN 'direct' THEN 2
        WHEN 'historical' THEN 3 WHEN 'referral_or_planned' THEN 4
        WHEN 'equipment' THEN 5 WHEN 'specialty' THEN 6 ELSE 7 END,
        CASE c.field_name WHEN 'procedure' THEN 0 WHEN 'capability' THEN 1
          WHEN 'description' THEN 2 WHEN 'equipment' THEN 3 ELSE 4 END,
        LENGTH(c.excerpt), c.excerpt, c.raw_id, c.source_urls_json
    ) AS evidence_rank
  FROM classified c
  JOIN summary s ON c.campus_id = s.campus_id AND c.service = s.service
)
SELECT campus_id, service,
  CASE WHEN evidence_reason = 'direct' THEN 3
    WHEN evidence_reason IN ('equipment', 'specialty', 'mention') THEN 2 ELSE 1 END AS confidence,
  evidence_reason,
  field_name AS source_field,
  excerpt AS evidence_text,
  raw_id AS source_record_id,
  source_urls_json,
  CASE WHEN evidence_reason = 'conflict' THEN direct_example.excerpt END AS counter_evidence_text,
  CASE WHEN evidence_reason = 'conflict' THEN direct_example.field END AS counter_source_field,
  CASE WHEN evidence_reason = 'conflict' THEN direct_example.raw_id END AS counter_record_id,
  CASE WHEN evidence_reason = 'conflict' THEN direct_example.urls END AS counter_source_urls_json
FROM ranked
WHERE evidence_rank = 1;