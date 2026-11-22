CREATE OR REPLACE TABLE workspace.datathon_silver.gold_india_pin_centers AS
WITH postal_points AS (
  SELECT DISTINCT
    TRIM(CAST(pincode AS STRING)) AS pin,
    TRY_CAST(latitude AS DOUBLE) AS lat,
    TRY_CAST(longitude AS DOUBLE) AS lon
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory
  WHERE TRIM(CAST(pincode AS STRING)) RLIKE '^[1-9][0-9]{5}$'
),
valid_points AS (
  SELECT pin, lat, lon
  FROM postal_points
  WHERE lat BETWEEN 6 AND 38 AND lon BETWEEN 68 AND 98
),
pin_reference AS (
  SELECT pin, PERCENTILE(lat, 0.5) AS median_lat,
         PERCENTILE(lon, 0.5) AS median_lon, COUNT(*) AS point_count
  FROM valid_points
  GROUP BY pin
),
near_reference AS (
  SELECT p.pin, p.lat, p.lon, r.point_count
  FROM valid_points p
  JOIN pin_reference r ON p.pin = r.pin
  WHERE 111.2 * SQRT(
    POWER(p.lat - r.median_lat, 2)
    + POWER((p.lon - r.median_lon) * COS(RADIANS(r.median_lat)), 2)
  ) <= 25
)
SELECT pin, AVG(lat) AS lat, AVG(lon) AS lon
FROM near_reference
GROUP BY pin
HAVING COUNT(*) * 2 > MAX(point_count);
