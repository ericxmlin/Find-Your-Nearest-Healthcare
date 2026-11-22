WITH nearby AS (
  SELECT pin, lat, lon
  FROM workspace.datathon_silver.gold_india_pin_centers
  WHERE lat BETWEEN :latitude - 0.25 AND :latitude + 0.25
    AND lon BETWEEN :longitude - 0.25 AND :longitude + 0.25
),
distances AS (
  SELECT pin, 2 * 6371 * ASIN(LEAST(1.0, SQRT(
    POWER(SIN(RADIANS(lat - :latitude) / 2), 2)
    + COS(RADIANS(:latitude)) * COS(RADIANS(lat))
      * POWER(SIN(RADIANS(lon - :longitude) / 2), 2)
  ))) AS distance_km
  FROM nearby
)
SELECT pin, distance_km
FROM distances
WHERE distance_km <= 15
ORDER BY distance_km, pin
LIMIT 1;
