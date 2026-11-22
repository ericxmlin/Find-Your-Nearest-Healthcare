WITH requested AS (
  SELECT DISTINCT EXPLODE(FROM_JSON(:services, 'ARRAY<STRING>')) AS service
),
search_point AS (
  SELECT CAST(:origin_lat AS DOUBLE) AS lat, CAST(:origin_lon AS DOUBLE) AS lon
  WHERE :use_map_point = 1
  UNION ALL
  SELECT lat, lon
  FROM workspace.datathon_silver.gold_india_pin_centers
  WHERE :use_map_point = 0 AND pin = :pin
),
matches AS (
  SELECT e.*
  FROM workspace.datathon_silver.gold_india_service_confidence e
  JOIN requested r ON e.service = r.service
),
matching_campuses AS (
  SELECT campus_id,
    SUM(CASE WHEN confidence = 3 THEN 1 ELSE 0 END) AS high_count,
    SUM(CASE WHEN confidence = 2 THEN 1 ELSE 0 END) AS medium_count
  FROM matches
  GROUP BY campus_id
),
distances AS (
  SELECT f.campus_id, f.facility_name, f.address_line1, f.city, f.state, f.pin_clean,
    f.latitude, f.longitude, f.phone, f.location_flags, p.lat AS origin_latitude, p.lon AS origin_longitude,
    m.high_count, m.medium_count,
    2 * 6371 * ASIN(LEAST(1.0, SQRT(
      POWER(SIN(RADIANS(f.latitude - p.lat) / 2), 2)
      + COS(RADIANS(p.lat)) * COS(RADIANS(f.latitude))
        * POWER(SIN(RADIANS(f.longitude - p.lon) / 2), 2)
    ))) AS distance_km
  FROM workspace.datathon_silver.gold_india_facilities f
  JOIN matching_campuses m ON f.campus_id = m.campus_id
  CROSS JOIN search_point p
  WHERE f.eligible_for_distance AND f.latitude IS NOT NULL AND f.longitude IS NOT NULL
),
unavailable AS (
  SELECT TO_JSON(SORT_ARRAY(COLLECT_SET(r.service))) AS services_json
  FROM requested r
  WHERE NOT EXISTS (
    SELECT 1 FROM matches m JOIN distances d ON m.campus_id = d.campus_id
    WHERE m.service = r.service AND m.confidence >= 2
  )
),
excluded_locations AS (
  SELECT COUNT(*) AS excluded_location_count
  FROM workspace.datathon_silver.gold_india_facilities f
  JOIN matching_campuses m ON f.campus_id = m.campus_id
  WHERE SIZE(f.location_flags) > 0
    AND NOT COALESCE(f.eligible_for_distance AND f.latitude IS NOT NULL AND f.longitude IS NOT NULL, FALSE)
),
scores AS (
  SELECT d.*,
    (high_count + 0.7 * medium_count) / (SELECT COUNT(*) FROM requested) AS confidence_score,
    POWER(0.5, distance_km / :distance_half_life_km) AS distance_score
  FROM distances d
),
weighted_scores AS (
  SELECT *,
    high_count + medium_count > 0 AS recommended,
    60 * confidence_score AS evidence_points,
    40 * distance_score AS distance_points
  FROM scores
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY recommended
      ORDER BY evidence_points + distance_points DESC,
        confidence_score DESC, distance_km, campus_id
    ) AS overall_rank,
    ROW_NUMBER() OVER (
      ORDER BY distance_km, confidence_score DESC, campus_id
    ) AS distance_rank,
    ROW_NUMBER() OVER (
      PARTITION BY recommended
      ORDER BY confidence_score DESC, distance_km, campus_id
    ) AS confidence_rank
  FROM weighted_scores
),
top_results AS (
  SELECT *, 'overall' AS ranking, overall_rank AS result_rank
  FROM ranked WHERE recommended AND overall_rank <= 10
  UNION ALL
  SELECT *, 'nearest' AS ranking, distance_rank AS result_rank
  FROM ranked WHERE distance_rank <= 5
  UNION ALL
  SELECT *, 'confidence' AS ranking, confidence_rank AS result_rank
  FROM ranked WHERE recommended AND confidence_rank <= 5
)
SELECT t.ranking AS ranking, t.result_rank AS result_rank, t.facility_name, t.address_line1, t.city, t.state, t.pin_clean,
       ROUND(t.distance_km, 1) AS straight_line_km, r.service AS service,
       COALESCE(m.confidence, 1) AS confidence, COALESCE(m.evidence_reason, 'missing') AS evidence_reason,
       m.source_field, m.evidence_text, m.source_record_id,
       m.counter_evidence_text, m.counter_source_field, m.counter_record_id,
       t.high_count, t.medium_count, t.confidence_score, t.evidence_points, t.distance_points,
       u.services_json AS unavailable_services_json, CAST(NULL AS STRING) AS status,
       t.latitude AS latitude, t.longitude AS longitude, t.phone AS phone,
       t.origin_latitude AS origin_latitude, t.origin_longitude AS origin_longitude,
       t.location_flags, m.source_urls_json, m.counter_source_urls_json, x.excluded_location_count
FROM top_results t
CROSS JOIN requested r
CROSS JOIN unavailable u
CROSS JOIN excluded_locations x
LEFT JOIN matches m ON t.campus_id = m.campus_id AND r.service = m.service

UNION ALL

SELECT CAST(NULL AS STRING), 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, NULL, NULL, NULL, u.services_json,
       CASE WHEN NOT EXISTS (SELECT 1 FROM search_point) THEN 'unknown_pin' ELSE 'no_matches' END,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, x.excluded_location_count
FROM unavailable u
CROSS JOIN excluded_locations x
WHERE NOT EXISTS (SELECT 1 FROM top_results)
ORDER BY ranking, result_rank, service;
