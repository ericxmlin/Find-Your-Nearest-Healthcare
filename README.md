# Find Your Nearest Healthcare

Find healthcare facilities in India by postal PIN or map location, then compare how close they are and what the underlying records say about the services you need. This project is built with Streamlit on Databricks, with an English and Hindi interface.

**Try the demo.** 

The [submission notebook](Find_Your_Nearest_Healthcare.ipynb) includes saved results for a dialysis search near PIN **226003**. To reproduce the search, import the notebook into Databricks and run the demonstration cell after setting up the data below.

## Data sources and pipeline

The Virtue Foundation dataset provides facility records, service descriptions and source URLs. The India Post directory supplies postal coordinates. Both are read from the shared Databricks catalog. The general workflow is **source tables → Silver cleaning and audit → Gold search tables → parameterized SQL → Streamlit results**.

The app keeps two questions separate throughout this flow. Location checks determine whether a facility can be placed reliably enough to rank by distance. Evidence rules determine what the source records say about each requested service.

| Step | What it does |
| --- | --- |
| [Clean the facility records](datathon_silver/clean_facilities.py) | Keep Indian facility records with valid IDs, normalize place names and postal codes, and remove exact duplicates. Group rows by source ID, preserve the original records for auditing, and flag potential duplicate campuses based on address, PIN, and website. Merge a known same-campus alias only when its address matches. |
| [Build postal reference points](setup_pin_centers.sql) | Deduplicate and screen postal coordinates. For each PIN, compute the median latitude and longitude, keep points within about 25 km of that reference, and average the remaining points only if they make up a strict majority. |
| [Build facility search records](setup_facility_contacts.sql) | Store campus locations, location flags, and contact numbers. Normalize phone formats, prefer a unique official number, and fall back to a number only when all usable candidates agree. |
| [Build service evidence](setup_service_confidence.sql) | Join each campus to its original source IDs, extract text excerpts, and assign a confidence level and reason for each campus–service pair. |

Location checks compare facility coordinates with postal data when the PIN reference is sufficiently consistent. The pipeline flags issues such as PIN–state disagreement, a large separation from a consistent PIN reference, conflicting variants of a source record, and reviewed location conflicts. Flagged facilities that fail the location checks do not enter the distance rankings.

## How service confidence is assigned

The app covers 12 service categories: dialysis, MRI, CT scan, ICU, NICU, emergency care, C-section, cardiac surgery, burn care, chemotherapy, radiotherapy, and kidney transplant.

The Gold SQL splits capability, procedure, description, equipment, and specialty fields into excerpts and matches each excerpt against service-specific terms. It uses service-specific terms and context rules. For example, it removes PET-CT and CT simulation terms from general CT matching and separates neonatal or pediatric intensive care units from general ICU matches. Facility names are removed from the text used for matching so a name alone cannot trigger a match.

| Confidence | Score per service | Examples |
| --- | ---: | --- |
| High | 1.0 | A direct statement that a facility offers or performs the service |
| Medium | 0.7 | Relevant equipment, a related specialty, or a mention without a direct service claim |
| Low | 0.0 | A denial, an attribution conflict, historical availability, a referral, or a planned service |
| Missing | 0.0 | No matching excerpt for that facility and service |

We treat low confidence the same as missing to provide maximum accuracy for the clients. The query prioritizes conflicting campus attribution and explicit denials when choosing a representative excerpt. If a denial and a direct claim coexist, the result shows both as conflicting evidence. Within an evidence reason, the SQL uses field priority and deterministic tie-breakers to keep one representative excerpt. Repeated mentions of the same service earn no extra points. The app labels low or missing evidence for individual services when a facility only partially matches the search. Each excerpt carries its original field, record ID, and the URLs already listed in that source record's source_urls field. The app keeps well-formed HTTP and HTTPS links, removes exact duplicates within the list, and preserves the source order.

## How results are ranked

For a typed PIN, the app uses the approximate postal reference point. For a selected map point, it measures from the chosen coordinates. The map can suggest a nearby PIN for display without moving the search origin. The distance calculation uses the Haversine formula, which estimates straight-line distance along the Earth's surface. The optional map-to-PIN lookup uses the nearest candidate postal reference point within 15 km. This threshold only affects the PIN suggestion. Facility results have no maximum search radius.

$$
\text{Overall score} =
60 \times \text{mean service confidence}
+ 40 \times 0.5^{\,d/25}
$$

Here, $d$ is distance in kilometers. Each selected service counts equally in the evidence average. For example, when a user selects two services and a campus has high evidence for one and no match for the other, its evidence component is $60 \times (1+0)/2 = 30$ points. Distance contributes 40 points at 0 km, 20 at 25 km, and 10 at 50 km.

### Why we chose 60:40

We weighted service evidence more heavily because users first need a credible reason to believe a facility offers the care they are looking for. We kept distance at 40% so a substantially closer facility with medium-confidence evidence can still rank ahead of a much farther facility with stronger evidence.

These hypothetical single-service results illustrate the trade-off:

| Facility | Evidence points | Distance points | Overall score |
| --- | ---: | ---: | ---: |
| High confidence, 25 km away | 60 | 20.0 | **80.0** |
| Medium confidence, 10 km away | 42 | 30.3 | **72.3** |
| High confidence, 50 km away | 60 | 10.0 | **70.0** |

With the 25 km distance half-life fixed, both illustrated ordering preferences hold for evidence weights between about 46.2% and 62.9%, excluding the tie points. The 60% weight is a design choice within that range. The example shows how the weighting behaves. Establishing an empirically optimal weight would require independent relevance judgments across representative searches and a comparison on held-out cases.

### Ranking views

| View | Order | Eligibility |
| --- | --- | --- |
| Overall | Combined score, then evidence score, then distance | Up to 10. Requires medium or high confidence for at least one selected service. |
| Nearest first | Distance, then evidence score | Up to 5. Includes campuses with low-confidence matches. |
| Confidence first | Evidence score, then distance | Up to 5. Requires medium or high confidence for at least one selected service. |

Campus ID breaks any remaining ties. The app displays at most the stated number of distinct campuses in each view, with evidence shown separately for each requested service. The **Nearest first** view can surface low-confidence records with a warning.

## Maps and language

The results map uses Leaflet and OpenStreetMap tiles. It displays the search origin and the facilities in the active ranking view. Facilities with identical coordinates share a marker. Interface labels and service names have English and Hindi versions. Hindi mode attempts to translate facility details and excerpts with Databricks SQL. If translation is unavailable, the app falls back to the original text. The ranking always uses the source evidence.

## Reproduce and deploy

In Databricks, use a project schema named **workspace.datathon_silver** and ensure you can read the shared source tables and write the project tables. The setup scripts recreate their corresponding tables.

1. Import [clean_facilities.py](datathon_silver/clean_facilities.py) as a Python notebook. Set the output_schema widget to workspace.datathon_silver and run it.
2. Run [setup_pin_centers.sql](setup_pin_centers.sql), [setup_facility_contacts.sql](setup_facility_contacts.sql), and [setup_service_confidence.sql](setup_service_confidence.sql).
3. Run the demonstration cell in the [submission notebook](Find_Your_Nearest_Healthcare.ipynb).
4. To deploy the web app, use [india-facility-search-v22/](india-facility-search-v22/) as the Databricks App source directory. Bind a SQL warehouse resource named **sql-warehouse** with **Can use** permission. Give the app identity access to the project catalog and schema and read access to the three Gold tables.

| Source file | Responsibility |
| --- | --- |
| [search.sql](india-facility-search-v22/search.sql) | Candidate eligibility, evidence and distance scoring, and the three rankings |
| [pin_lookup.sql](india-facility-search-v22/pin_lookup.sql) | Optional PIN suggestion for a selected map point |
| [app.py](india-facility-search-v22/app.py) | Search inputs, SQL connection, results, maps, and evidence display |
| [locale_strings.py](india-facility-search-v22/locale_strings.py) | English and Hindi interface labels and messages |
| [map_picker.js](india-facility-search-v22/map_picker.js) | Map location picker and result markers |
