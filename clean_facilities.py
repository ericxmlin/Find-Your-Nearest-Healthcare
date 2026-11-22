# Databricks notebook source
"""Clean the Virtue Foundation snapshot or the corresponding Databricks tables."""

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
from urllib.parse import urlsplit
import uuid

CATALOG = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
FIELDS = ("description", "procedure", "capability", "equipment", "specialties")
DIALYSIS = re.compile(r"\b(?:dialysis|hemodialysis|haemodialysis)\b", re.I)
CITY_ALIASES = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru", "lucknow": "Lucknow"}
STATE_ALIASES = {"up": "Uttar Pradesh", "u.p.": "Uttar Pradesh", "uttar pradesh": "Uttar Pradesh",
                 "ghaziabad, uttar pradesh": "Uttar Pradesh", "orissa": "Odisha", "odisha": "Odisha",
                 "uttarakhand": "Uttarakhand", "uttaranchal": "Uttarakhand"}
ARAVIND_CONFLICT = "b8a5401f-42f1-422a-8cd9-686a15b4cb76"
CHARAK = "a45cac41-6d27-41ab-878b-7dfb89ec8f33"
CHARAK_ALIAS = "2b5d4240-8105-4e60-adb7-01f8cee3a622"
REVIEW_JSON = '''
[
  {
    "source_id": "8b1f6969-a3ce-492a-b855-2c04199f2e5c",
    "status": "supported",
    "location_conflict": false,
    "url": "https://portal.nabh.co/Documents/AccreditedList/Hospitals/H-2024-1427_5th%20Edition_Scope%20Correction.pdf",
    "quote": "Nephrology including Dialysis",
    "note": "NABH scope names Fatima Hospital, 35-C Mahanagar, Lucknow 226006, and covers dialysis. Listed validity runs to 2028-09-04. The raw coordinates are about 281 km from the PIN reference and are on hold.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "907f5a8b-088d-484d-82d6-b92a9465f160",
    "status": "historical",
    "location_conflict": false,
    "url": "https://www.dtf.in/wp-content/files/Updated_list_of_empanelled_HCOs__names_of_nodal_officers_nominated_by_the_HCOs_under_CGHS_Lucknow_as_on_04_June_2025_As_on_CGHS_website-16.07.2025.pdf",
    "quote": "Nephrology including dialysis",
    "note": "The CGHS listing names the Vikas Khand site and lists dialysis. Its listed coverage ended 2026-04-30.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "a45cac41-6d27-41ab-878b-7dfb89ec8f33",
    "status": "supported",
    "location_conflict": false,
    "url": "https://www.charakhospital.org/procedures/dialysis",
    "quote": "we provide comprehensive hemodialysis and peritoneal dialysis services with expert nephrology care",
    "note": "Provider confirms both services. The Hardoi Road Dubagga address matches the same campus as the other Charak record.",
    "reviewed_on": "2026-11-21",
    "location_url": "https://www.charakhospital.org/contactus"
  },
  {
    "source_id": "d4066f5a-ad1f-48b9-92cf-6b32431939a8",
    "status": "unverified",
    "location_conflict": false,
    "url": "https://www.drrmlims.ac.in/about/",
    "quote": null,
    "note": "The institute confirms the Vibhuti Khand campus and nephrology. A training-course listing does not independently establish a patient dialysis service at this campus.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "2b5d4240-8105-4e60-adb7-01f8cee3a622",
    "status": "supported",
    "location_conflict": false,
    "url": "https://www.charakhospital.org/procedures/dialysis",
    "quote": "we provide comprehensive hemodialysis and peritoneal dialysis services with expert nephrology care",
    "note": "Same Hardoi Road Dubagga campus as Charak Hospital And Research Centre. The source corroboration is stored once per campus.",
    "reviewed_on": "2026-11-21",
    "location_url": "https://www.charakhospital.org/contactus"
  },
  {
    "source_id": "4e3a5fb5-df76-4d34-81bd-b3448a372f48",
    "status": "conflict",
    "location_conflict": true,
    "url": "https://max-website20-images.s3.ap-south-1.amazonaws.com/Half_Yearly_Report_of_LKO_Apr_25_Sep_25_94c2bac5c0.pdf",
    "quote": null,
    "note": "Operator identifies former Sahara Hospital in Viraj Khand, Gomti Nagar 226010. The dataset row gives Hardoi Road 226003. Hold site and service attribution.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "5fe4b03b-9b0b-4c21-8004-04fdd08ed3c9",
    "status": "conflict",
    "location_conflict": true,
    "url": "https://www.suneyehospital.com/",
    "quote": null,
    "note": "The provider lists Alambagh and Gomti Nagar eye-care sites. The row gives Kakori/Mohan Road and a bare dialysis label. No provider source ties that claim to Sun Eye.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "705cc566-7ec3-40f3-aaec-4b114fc6d2da",
    "status": "supported",
    "location_conflict": true,
    "url": "https://www.balrampurhospital.com/",
    "quote": "A 10-beded dialysis unit",
    "note": "Provider describes a dialysis unit. Corrected PIN 224176 to 226018 using the provider contact page. Facility coordinates still need direct verification.",
    "reviewed_on": "2026-11-21",
    "verified_pin": "226018",
    "location_url": "https://www.balrampurhospital.com/Contact.aspx"
  },
  {
    "source_id": "84f06705-ee19-4ee1-a974-4bc46a797271",
    "status": "supported",
    "location_conflict": false,
    "url": "https://www.sewahospitallko.com/who-we-are.php",
    "quote": "the hospital provisions 100 beds, ICU centre, NICU, PBU, Dialysis, X-Ray",
    "note": "Provider names the service and the Sewa Nagar, Sitapur Road campus.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "a02093bd-9617-4be4-910d-687db2b99a61",
    "status": "conflict",
    "location_conflict": true,
    "url": "https://nishathospital.com/contact-us/",
    "quote": null,
    "note": "The dataset dialysis excerpt explicitly names Isha Hospital Jaunpur. Nishat's official contact page gives Kaisarbagh, Lucknow versus Meerut Road in the row.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "c80ad4c1-cdaa-4254-a07b-7cc0364d7c5d",
    "status": "unverified",
    "location_conflict": false,
    "url": "https://www.krishnamedicalcentre.org/contact-us",
    "quote": null,
    "note": "Provider confirms 1 Rana Pratap Marg. The equipment claim needs a site-specific dialysis source.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "1980afa5-d795-4260-a066-33f36e51aded",
    "status": "unverified",
    "location_conflict": true,
    "url": "https://portal.nabh.co/Documents/AccreditedList/Hospitals/H-2023-1135_5th%20Edition_Surveillance.pdf",
    "quote": null,
    "note": "A dialysis unit appears in the dataset equipment field. The reviewed accreditation source does not establish the service at the dataset's Vishal Khand address.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "bfa6780d-a589-493c-b846-834f232d4efd",
    "status": "conflict",
    "location_conflict": true,
    "url": "https://mau.nic.in/en/public-utility/sharda-narayan-hospital/",
    "quote": null,
    "note": "The district government lists Sharda Narayan in Mau. The dataset labels the city Lucknow and the service excerpt itself mentions Mau. Hold location and service attribution.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "49e46a47-07ec-4234-aabe-07fa94223806",
    "status": "supported",
    "location_conflict": false,
    "url": "https://www.miruscriticalcare.com/mirus-hospital-facilities",
    "quote": "Continuous Renal Replacement Therapy and regular dialysis available 24x7.",
    "note": "The provider confirms dialysis. Its contact page matches the TCV-84-A/86/87 site in Vibhuti Khand.",
    "reviewed_on": "2026-11-21",
    "location_url": "https://www.miruscriticalcare.com/contact-mirus-hospital-lucknow"
  },
  {
    "source_id": "25c6a2b2-af5d-48c7-9ae7-605f04ee3b60",
    "status": "supported",
    "location_conflict": false,
    "url": "https://jims.edu.in/javitri_hospital.aspx",
    "quote": "specialized unit of ICU, NICU, dialysis & Trauma",
    "note": "The operator identifies the dialysis unit at the Telibagh site and separately mentions a fertility unit in Badshah Nagar. The raw address matches Telibagh.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "3a3ce4a6-6a09-4c9d-a8c4-de1ab65754d8",
    "status": "conflict",
    "location_conflict": true,
    "url": "https://www.charakhospital.org/Satellite-opd",
    "quote": null,
    "note": "The operator identifies Charak Polyclinic as a satellite OPD in Raebareli. The dialysis page belongs to the main Lucknow hospital. Keep this site separate and hold the service claim.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "3eea04cf-d1a5-4ac9-8e40-4c7ee0f52858",
    "status": "supported",
    "location_conflict": false,
    "url": "https://precisionuro.com/areas-of-excellance/nephrology-services/renal-failure-management",
    "quote": "At Precision Hospital, ESRD patients are given RRT which includes dialysis and kidney transplantation.",
    "note": "The provider describes dialysis for patients at Precision Hospital. Campus matched by provider identity and Ring Road address.",
    "reviewed_on": "2026-11-21",
    "location_url": "https://precisionuro.com/"
  },
  {
    "source_id": "dbc80639-dbf4-4eb1-bb1e-a4142c4cf41f",
    "status": "unverified",
    "location_conflict": true,
    "url": "https://familyhospitallko.in/",
    "quote": null,
    "note": "The provider confirms the Sitapur Road facility but does not substantiate the equipment excerpt. A directory lists a different PIN, so hold the location pending confirmation.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "413c1fbc-9765-4881-8422-f44601851939",
    "status": "supported",
    "location_conflict": false,
    "url": "https://freseniuskidneycare.asia/center-detail/ind1004/",
    "quote": "Standard hemodialysis (HD)",
    "note": "The service operator lists hemodialysis at Regency Hospital on Tedhi Pulia Ring Road, matching PIN 226022.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "8983f199-31f7-4c8e-b253-79175d2a4f23",
    "status": "unverified",
    "location_conflict": false,
    "url": "https://www.linkedin.com/company/ekana-hospital-and-research-centre",
    "quote": null,
    "note": "The public profile identifies the Sector 4 campus. The dataset service claim needs a verifiable site-specific dialysis source.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "d93e5058-3819-47e3-aaae-49e6d9cfbafb",
    "status": "conflict",
    "location_conflict": true,
    "url": "https://www.practo.com/lucknow/hospital/bnk-hospital-1-csir-colony/services",
    "quote": null,
    "note": "The directory lists dialysis but gives B-1/196 versus B-1/96 in the row. A separate NABH document gives A-3/A-4/A-5 and PIN 226020. Location needs reconciliation.",
    "reviewed_on": "2026-11-21"
  },
  {
    "source_id": "f67f6103-b4a2-451c-ae59-d52cd4696534",
    "status": "supported",
    "location_conflict": false,
    "url": "https://brajrajhospital.com/",
    "quote": "24/7 Dialysis Facility",
    "note": "Provider advertises dialysis and the contact page identifies the Tahseenganj Crossing campus.",
    "reviewed_on": "2026-11-21",
    "location_url": "https://brajrajhospital.com/contact/"
  }
]
'''


def clean(value):
    if value is None:
        return None
    result = " ".join(str(value).split())
    return None if result.casefold() in {"", "null", "none", "nan", "n/a", "na"} else result


def key(value):
    return (clean(value) or "").casefold()


def place(value, aliases):
    return aliases.get(key(value), clean(value))


def pin(value):
    compact = re.sub(r"[\s-]", "", clean(value) or "")
    return compact if re.fullmatch(r"[1-9][0-9]{5}", compact) else None


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def array(value):
    if clean(value) is None:
        return []
    try:
        parsed = value if isinstance(value, (list, tuple)) else json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in parsed if isinstance(item, str) and clean(item)] if isinstance(parsed, (list, tuple)) else []


def website(value):
    value = clean(value) or ""
    try:
        return (urlsplit(value if "://" in value else "//" + value).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def csv_rows(path):
    csv.field_size_limit(2**27)
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream, strict=True)


def build_pin_index(rows):
    areas, points = defaultdict(set), defaultdict(set)
    for row in rows:
        code = pin(row.get("pincode"))
        state = place(row.get("statename"), STATE_ALIASES)
        district = place(row.get("district"), CITY_ALIASES)
        if code and state and district:
            areas[code].add((key(state), key(district)))
            lat, lon, status = coordinate_status(row)
            if status == "in_bounds":
                points[code].add((lat, lon))
    return areas, points


def distance_km(first_lat, first_lon, second_lat, second_lon):
    dlat = math.radians(second_lat - first_lat)
    dlon = math.radians(second_lon - first_lon)
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(first_lat)) * math.cos(math.radians(second_lat)) * math.sin(dlon / 2) ** 2)
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(h)))


def coordinate_status(row):
    lat = number(row.get("latitude"))
    lon = number(row.get("longitude"))
    if lat is None or lon is None:
        if clean(row.get("latitude")) is None or clean(row.get("longitude")) is None:
            return lat, lon, "missing"
        return lat, lon, "invalid"
    if not (6 <= lat <= 38 and 68 <= lon <= 98):
        return lat, lon, "out_of_india_bounds"
    return lat, lon, "in_bounds"


def pin_lookup(code, state, city, index):
    areas = sorted(index.get(code, ()))
    states = sorted({s for s, _ in areas})
    if not code:
        status = "invalid_or_missing"
    elif not states:
        status = "not_found"
    elif key(state) and key(state) not in states:
        status = "state_mismatch"
    elif len(areas) > 1:
        status = "ambiguous"
    elif key(city) == areas[0][1]:
        status = "state_and_city_match"
    else:
        status = "state_match_city_unchecked"
    return status, states, [f"{s} / {d}" for s, d in areas]


def excerpts(row, field):
    if field == "description":
        raw = row.get(field) or ""
        parts = re.split(r"(?<=[.!?])\s+|\r?\n+", raw)
    else:
        parts = array(row.get(field))
    return list(dict.fromkeys(p.strip() for p in parts if DIALYSIS.search(p)))


def clean_data(facility_rows, pin_rows, reviews):
    pin_index, pin_points = build_pin_index(pin_rows)
    groups = defaultdict(dict)
    audit = []
    for i, row in enumerate(facility_rows, 1):
        raw_id = clean(row.get("unique_id"))
        fingerprint = digest(row)
        try:
            raw_id = str(uuid.UUID(raw_id or ""))
        except ValueError:
            audit.append(dict(input_record=i, row_sha256=fingerprint, source_id=None, reason="invalid_facility_id"))
            continue
        if key(row.get("organization_type")) != "facility" or key(row.get("address_countryCode")) != "in":
            audit.append(dict(input_record=i, row_sha256=fingerprint, source_id=raw_id, reason="outside_india_facility_scope"))
            continue
        if fingerprint in groups[raw_id]:
            audit.append(dict(input_record=i, row_sha256=fingerprint, source_id=raw_id, reason="exact_duplicate"))
            continue
        groups[raw_id][fingerprint] = row

    review_by_id = {entry["source_id"]: entry for entry in reviews}
    def chosen(source_id):
        variants = groups[source_id]
        return variants[min(variants)]

    def address_signature(row):
        return (key(row.get("address_line1")), key(row.get("address_line2")),
                pin(row.get("address_zipOrPostcode")), website(row.get("officialWebsite")))

    merged = (CHARAK in groups and CHARAK_ALIAS in groups
              and address_signature(chosen(CHARAK)) == address_signature(chosen(CHARAK_ALIAS))
              and address_signature(chosen(CHARAK)) == ("hardoi road", "dubagga", "226003", "charakhospital.org"))
    duplicate_blocks = defaultdict(list)
    for source_id in groups:
        row = chosen(source_id)
        signature = address_signature(row)
        if all(signature):
            duplicate_blocks[signature].append(source_id)
    duplicate_candidates = {source_id: [other for other in block if other != source_id]
                            for block in duplicate_blocks.values() if len(block) > 1 for source_id in block}
    campus_for = {raw_id: CHARAK if merged and raw_id == CHARAK_ALIAS else raw_id for raw_id in groups}
    campuses = defaultdict(list)
    for raw_id, campus_id in campus_for.items():
        campuses[campus_id].append(raw_id)

    facilities, evidence, review_output = [], [], []
    corroborated = set()
    for campus_id, ids in sorted(campuses.items()):
        ids.sort()
        row = chosen(campus_id)
        name = clean(row.get("name"))
        city = place(row.get("address_city"), CITY_ALIASES)
        state = place(row.get("address_stateOrRegion"), STATE_ALIASES)
        current_review = review_by_id.get(campus_id, {})
        reviewed_pin = current_review.get("verified_pin")
        code = pin(reviewed_pin or row.get("address_zipOrPostcode"))
        pin_status, pin_states, pin_areas = pin_lookup(code, state, city, pin_index)
        lat, lon, status = coordinate_status(row)
        location_notes = []
        pin_reference_km = None
        points = pin_points.get(code)
        if status == "in_bounds" and points and len(pin_areas) == 1 and pin_status != "state_mismatch":
            center_lat = median(x for x, _ in points)
            center_lon = median(y for _, y in points)
            if max(distance_km(center_lat, center_lon, x, y) for x, y in points) <= 30:
                pin_reference_km = round(distance_km(lat, lon, center_lat, center_lon), 3)
                if pin_reference_km > 30:
                    location_notes.append("pin_coordinate_disagreement")
        if pin_status == "state_mismatch":
            location_notes.append("pin_state_mismatch")
        if any(len(groups[raw_id]) > 1 for raw_id in ids):
            location_notes.append("conflicting_source_id_variants")
        if any(review_by_id.get(raw_id, {}).get("location_conflict") for raw_id in ids):
            location_notes.append("reviewed_location_conflict")
        if ARAVIND_CONFLICT in ids:
            location_notes.append("mixed_facility_and_address")
        if status == "in_bounds" and location_notes:
            status = "needs_review"

        possible_duplicates = sorted({campus_for[other] for source_id in ids
                                      for other in duplicate_candidates.get(source_id, [])} - {campus_id})
        facilities.append(dict(
            campus_id=campus_id, name=name, name_key=key(name), city=city, city_key=key(city),
            state=state, state_key=key(state), pin_clean=code, pin_status=pin_status,
            pin_correction_url=current_review.get("location_url") if reviewed_pin else None,
            pin_format_status=("valid" if code else "missing" if clean(row.get("address_zipOrPostcode")) is None else "invalid"),
            pin_states=pin_states, pin_state_district_candidates=pin_areas, pin_reference_km=pin_reference_km,
            latitude=lat if status == "in_bounds" else None,
            longitude=lon if status == "in_bounds" else None, coordinate_status=status,
            location_flags=location_notes, eligible_for_distance=status == "in_bounds",
            official_domain=website(row.get("officialWebsite")), source_ids=ids,
            address_line1=clean(row.get("address_line1")), address_line2=clean(row.get("address_line2")),
            address_line3=clean(row.get("address_line3")), possible_duplicate_campus_ids=possible_duplicates,
            duplicate_review=("confirmed_same_campus" if len(ids) > 1 else
                              "possible_duplicate" if possible_duplicates else "single_source_id"),
            raw_locations=[
                {**{k: str(item[k]) if item.get(k) is not None else None for k in
                    ("name", "address_line1", "address_line2", "address_line3", "address_city", "address_stateOrRegion",
                     "address_zipOrPostcode", "latitude", "longitude", "officialWebsite")},
                 "source_id": source_id, "row_sha256": fp}
                for source_id in ids for fp, item in sorted(groups[source_id].items())
            ],
        ))
        for raw_id in ids:
            review = review_by_id.get(raw_id)
            found = False
            for fingerprint, source_row in sorted(groups[raw_id].items()):
                hits = [(field, excerpt) for field in FIELDS for excerpt in excerpts(source_row, field)]
                for field, excerpt in hits:
                    found = True
                    evidence.append(dict(
                        campus_id=campus_id, source_id=raw_id, service="dialysis", source_field=field,
                        evidence_kind="dataset_excerpt", evidence_text=excerpt, row_sha256=fingerprint,
                        source_url=None, candidate_source_urls=array(source_row.get("source_urls")),
                        evidence_status=("conflict" if raw_id == ARAVIND_CONFLICT or
                                         (review and review["status"] == "conflict") else "unverified"),
                        note=(review["note"] if review else
                              "Mixed providers and addresses in the source record." if raw_id == ARAVIND_CONFLICT else
                              "Keyword match. Verify service and campus together."),
                    ))
            if review and found:
                review_output.append({**review, "campus_id": campus_id, "facility_name": name})
                corroboration_key = (campus_id, review["url"], review["quote"])
                if review.get("quote") and corroboration_key not in corroborated:
                    corroborated.add(corroboration_key)
                    evidence.append(dict(
                        campus_id=campus_id, source_id=raw_id, service="dialysis", source_field="external_page",
                        evidence_kind="external_corroboration", evidence_text=review["quote"], row_sha256=None,
                        source_url=review["url"], candidate_source_urls=[],
                        evidence_status=review["status"], note=review["note"],
                    ))
    for item in evidence:
        item["evidence_id"] = digest(item)
    assert len({r["campus_id"] for r in facilities}) == len(facilities)
    assert len({r["evidence_id"] for r in evidence}) == len(evidence)
    assert all(r["campus_id"] in campuses for r in evidence)
    assert all(r["source_url"] and r["evidence_text"] for r in evidence if r["evidence_status"] == "supported")
    return {"silver_facilities": facilities, "silver_service_evidence": evidence,
            "lucknow_dialysis_review": sorted(review_output, key=lambda r: (r["facility_name"], r["source_id"])),
            "facility_cleaning_audit": audit}


def write_local(results, target):
    target.mkdir(parents=True, exist_ok=True)
    for name, rows in results.items():
        with (target / f"{name}.jsonl").open("w", encoding="utf-8") as output:
            for row in rows:
                print(json.dumps(row, ensure_ascii=False), file=output)


def run_local():
    parser = argparse.ArgumentParser()
    parser.add_argument("facilities", type=Path)
    parser.add_argument("pin_directory", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    reviews = json.loads(REVIEW_JSON)
    results = clean_data(csv_rows(args.facilities), csv_rows(args.pin_directory), reviews)
    write_local(results, args.output)
    return {name: len(rows) for name, rows in results.items()}

# COMMAND ----------

# Set output_schema to an existing writable catalog.schema before using Run all.
# The project-specific table names in that schema are replaced on a rerun.
if "spark" in globals() and "dbutils" in globals():
    dbutils.widgets.text("output_schema", "")
    output_schema = dbutils.widgets.get("output_schema").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*\.[A-Za-z_][A-Za-z_0-9]*", output_schema):
        raise ValueError("Set output_schema to an existing writable catalog.schema.")

    reviews = json.loads(REVIEW_JSON)
    facility_source = spark.table(CATALOG + ".facilities").toLocalIterator()
    pin_source = spark.table(CATALOG + ".india_post_pincode_directory").toLocalIterator()
    results = clean_data((r.asDict(recursive=True) for r in facility_source),
                         (r.asDict(recursive=True) for r in pin_source), reviews)
    for name, rows in results.items():
        if not rows:
            if name == "facility_cleaning_audit":
                empty = spark.createDataFrame([], "input_record INT, row_sha256 STRING, source_id STRING, reason STRING")
                empty.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{output_schema}.{name}")
            else:
                raise ValueError(f"Unexpected empty result for {name}. Check the source tables.")
            print(f"{name}: 0 rows")
            continue
        lines = [json.dumps(row, ensure_ascii=False) for row in rows]
        # Serverless supports Spark Connect DataFrame APIs. Use SQL JSON parsing
        # with an explicit schema inferred from the Cleansing output below.
        from pyspark.sql import functions as F
        from pyspark.sql.types import (ArrayType, BooleanType, DoubleType, IntegerType,
                                       StringType, StructField, StructType)
        def infer(values):
            populated = [v for v in values if v is not None]
            if not populated:
                return StringType()
            example = populated[0]
            if isinstance(example, dict):
                return StructType([StructField(k, infer([v.get(k) for v in populated]))
                                   for k in sorted(set().union(*(v.keys() for v in populated)))])
            if isinstance(example, list):
                return ArrayType(infer([item for v in populated for item in v]))
            if isinstance(example, bool):
                return BooleanType()
            if isinstance(example, int):
                return IntegerType()
            if isinstance(example, float):
                return DoubleType()
            return StringType()
        table = spark.createDataFrame([(line,) for line in lines], "record STRING")
        parsed = table.select(F.from_json("record", infer(rows)).alias("row")).select("row.*")
        parsed.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{output_schema}.{name}")
        print(f"{name}: {len(rows)} rows")
elif __name__ == "__main__":
    print(json.dumps(run_local(), indent=2))
