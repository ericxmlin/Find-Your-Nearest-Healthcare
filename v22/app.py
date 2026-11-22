from base64 import b64encode
from contextlib import contextmanager
from html import escape
from itertools import groupby
import json
import logging
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from databricks import sql
from databricks.sdk.core import Config
import streamlit as st

from locale_strings import FIELDS, MESSAGES, SERVICES

DISTANCE_HALF_LIFE_KM = 25
RANKINGS = ("overall", "nearest", "confidence")
RANKING_CSS = Path(__file__).with_name("ranking.css").read_text(encoding="utf-8")
SEARCH_SQL = Path(__file__).with_name("search.sql").read_text(encoding="utf-8")
PIN_LOOKUP_SQL = Path(__file__).with_name("pin_lookup.sql").read_text(encoding="utf-8")
MAP_PIN_URL = "data:image/png;base64," + b64encode(
    Path(__file__).with_name("favicon.png").read_bytes()
).decode("ascii")
MAP_PICKER = st.components.v2.component(
    "india_pin_picker",
    html="""
        <link rel="stylesheet" class="picker-leaflet-css">
        <div class="picker-frame">
            <div class="picker-map" role="region"></div>
            <img class="picker-pin" alt="" aria-hidden="true">
        </div>
        <div class="picker-actions">
            <span class="picker-status" role="status"></span>
            <button type="button" class="picker-confirm" disabled></button>
        </div>
    """,
    css=Path(__file__).with_name("map_picker.css").read_text(encoding="utf-8"),
    js=Path(__file__).with_name("map_picker.js").read_text(encoding="utf-8"),
)
TRANSLATE_SQL = """
WITH originals AS (
    SELECT DISTINCT EXPLODE(FROM_JSON(:texts, 'ARRAY<STRING>')) AS original
)
SELECT original, ai_translate(original, 'hi') AS hindi
FROM originals
"""


@contextmanager
def warehouse_cursor():
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    config = Config()
    with sql.connect(
        server_hostname=urlsplit(config.host).hostname,
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        credentials_provider=lambda: config.authenticate,
    ) as connection:
        with connection.cursor() as cursor:
            yield cursor


def search_facilities(pin, services, origin):
    latitude, longitude = origin if origin is not None else (0.0, 0.0)
    with warehouse_cursor() as cursor:
        cursor.execute(
            SEARCH_SQL,
            parameters={
                "pin": pin,
                "use_map_point": int(origin is not None),
                "origin_lat": latitude,
                "origin_lon": longitude,
                "services": json.dumps(services),
                "distance_half_life_km": DISTANCE_HALF_LIFE_KM,
            },
        )
        return cursor.fetchall()


def find_pin(latitude, longitude):
    with warehouse_cursor() as cursor:
        cursor.execute(PIN_LOOKUP_SQL, parameters={"latitude": latitude, "longitude": longitude})
        return cursor.fetchone()


def map_labels(tr, title):
    return {
        "title": title,
        "pinIcon": MAP_PIN_URL,
        "loading": tr("map_loading"),
        "loadError": tr("map_load_error"),
        "tilesError": tr("map_tile_error"),
        "zoomIn": tr("map_zoom_in"),
        "zoomOut": tr("map_zoom_out"),
    }


def show_results_map(facilities, translations, tr, from_map, excluded_location_count):
    @st.dialog(tr("results_map_title"), width="large")
    def dialog():
        st.caption(tr("results_map_note"))
        if excluded_location_count:
            st.caption(tr("location_excluded", count=excluded_location_count))
        origin_label = tr("results_map_origin_pin" if from_map else "results_map_origin_postal")
        st.caption(tr("results_map_legend", origin=origin_label))
        first = facilities[0][0]
        origin = {
            "lat": float(first.origin_latitude),
            "lon": float(first.origin_longitude),
            "label": origin_label,
        }
        markers = [
            {
                "lat": float(row.latitude),
                "lon": float(row.longitude),
                "rank": int(row.result_rank),
                "name": translations.get(row.facility_name, row.facility_name),
                "distance": tr("distance", km=row.straight_line_km),
                "locationWarning": tr("location_warning") if row.location_flags else "",
            }
            for row in (facility[0] for facility in facilities)
        ]
        MAP_PICKER(
            key="facility_results_map",
            data={**map_labels(tr, tr("results_map_title")), "markers": markers, "origin": origin},
        )

    dialog()


def pick_pin_on_map(tr):
    @st.dialog(tr("map_title"), width="large")
    def dialog():
        st.caption(tr("map_help"))
        picker = MAP_PICKER(
            key="india_pin_map",
            data={
                **map_labels(tr, tr("map_title")),
                "confirm": tr("map_confirm"),
                "zoomForPin": tr("map_zoom_hint"),
                "checking": tr("map_checking"),
                "start": st.session_state.get("map_view"),
            },
        )
        point = getattr(picker, "confirmed", None)
        if point is None:
            return

        try:
            latitude, longitude, zoom = float(point["lat"]), float(point["lon"]), int(point["zoom"])
            if not (
                math.isfinite(latitude) and math.isfinite(longitude)
                and 11 <= zoom <= 19 and -90 <= latitude <= 90 and -180 <= longitude <= 180
            ):
                raise ValueError("Invalid map point")
        except (TypeError, KeyError, ValueError, OverflowError):
            st.warning(tr("map_invalid_point"))
            return

        st.session_state["map_view"] = {"lat": latitude, "lon": longitude, "zoom": zoom}
        match = None
        try:
            with st.spinner(tr("map_checking")):
                match = find_pin(latitude, longitude)
        except Exception:
            logging.exception("Optional map PIN lookup failed")
        pin = str(match.pin) if match else ""
        st.session_state["pending_map_pin"] = (pin, latitude, longitude)
        st.rerun()

    dialog()


def translate_details(rows):
    originals = {
        text
        for row in rows
        for text in (row.facility_name, row.address_line1, row.city, row.state, row.evidence_text, row.counter_evidence_text)
        if text
    }
    if not originals:
        return {}, False
    try:
        with warehouse_cursor() as cursor:
            cursor.execute(TRANSLATE_SQL, parameters={"texts": json.dumps(sorted(originals))})
            translations = {
                row.original: row.hindi.strip()
                for row in cursor.fetchall()
                if row.hindi and row.hindi.strip()
            }
    except Exception:
        logging.exception("Hindi translation of facility details failed")
        return {}, True
    return translations, bool(originals.difference(translations))


def render():
    hindi = st.session_state.get("language") == "हिन्दी"

    def tr(key, **values):
        return MESSAGES[key][hindi].format(**values)

    def service_label(service):
        return SERVICES[service][hindi]

    logo_path = str(Path(__file__).with_name("favicon.png"))
    st.set_page_config(
        page_title=tr("title"),
        page_icon=logo_path,
        layout="centered",
    )
    pending_pin = st.session_state.pop("pending_map_pin", None)
    if pending_pin is not None:
        st.session_state["pin"] = pending_pin[0]
        st.session_state["mapped_pin"] = pending_pin
        st.session_state.pop("search_result", None)

    _, language_column = st.columns([3, 1])
    with language_column:
        st.selectbox("Language / भाषा", ("English", "हिन्दी"), key="language", label_visibility="collapsed")
    with st.container(key="page_hero"):
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.html(
                     f'<img src="{MAP_PIN_URL}" alt="" '
                     'width="76" height="76" style="display:block;margin:auto;">'
                   )
        st.title(tr("title"), text_alignment="center")
        st.caption(tr("intro"), text_alignment="center")

    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="bottom"):
            pin = st.text_input(
                tr("pin"), placeholder=tr("pin_example"), key="pin", width="stretch"
            ).strip()
            open_map = st.button(tr("open_map"), icon=":material/location_on:", width="content")
        mapped_pin = st.session_state.get("mapped_pin")
        origin = None
        if mapped_pin is not None and pin == mapped_pin[0]:
            origin = mapped_pin[1:]
            st.caption(tr("map_pin_filled", pin=pin) if pin else tr("map_without_pin"))
        elif mapped_pin is not None:
            st.session_state.pop("mapped_pin", None)
        services = st.multiselect(
            tr("services"),
            options=list(SERVICES),
            format_func=service_label,
            placeholder=tr("choose"),
            help=tr("help"),
            select_all=False,
            key="services",
        )
        submit = st.button(tr("search"), type="primary")

    if open_map:
        pick_pin_on_map(tr)

    if submit:
        st.session_state.pop("search_result", None)
        st.session_state["ranking_mode"] = "overall"
        if origin is None and not re.fullmatch(r"[1-9][0-9]{5}", pin):
            st.session_state["search_result"] = {"notice": "invalid_pin"}
        elif not services:
            st.session_state["search_result"] = {"notice": "no_services"}
        else:
            try:
                with st.spinner(tr("searching")):
                    rows = search_facilities(pin, services, origin)
                st.session_state["search_result"] = {"pin": pin, "from_map": origin is not None, "services": services, "rows": rows}
            except Exception:
                logging.exception("Facility lookup failed")
                st.session_state["search_result"] = {"notice": "search_failed"}

    render_results(st.session_state.get("search_result"), tr, service_label, hindi)
    st.html(
        '<footer style="border-top:1px solid var(--st-border-color, #d8d4d0);'
        'padding-top:.65rem;text-align:center;font-size:.85rem;opacity:.8">'
        f'{escape(tr("page_credit"))}</footer>'
    )


def render_results(result, tr, service_label, hindi):
    if result is None:
        st.html("""
            <style>
            .stMainBlockContainer:has(.st-key-page_hero) {
                padding-block-start: 4.25rem;
                padding-block-end: 1rem;
            }
            .st-key-page_hero [data-testid="stVerticalBlock"] {
                gap: 0.35rem;
            }
            .st-key-page_hero h1 {
                padding-block: 0.1rem 0.3rem;
                font-size: clamp(1.6rem, 4.2vw, 2.65rem);
                line-height: 1.12;
            }
            </style>
        """)
        return
    notice = result.get("notice")
    if notice:
        show = st.error if notice == "search_failed" else st.warning
        show(tr(notice))
        return

    rows = result["rows"]
    if not rows:
        st.info(tr("no_results"))
        return
    first = rows[0]
    if first.status == "unknown_pin":
        st.info(tr("unknown_pin"))
        return

    excluded_location_count = first.excluded_location_count
    if excluded_location_count:
        st.caption(tr("location_excluded", count=excluded_location_count))

    searched_services = result["services"]
    if first.status == "no_matches":
        st.info(tr("no_service_records"))
        return

    unavailable = set(json.loads(first.unavailable_services_json))
    if unavailable:
        labels = ", ".join(service_label(service) for service in searched_services if service in unavailable)
        st.warning(tr("unsupported_services", services=labels))

    translations = {}
    if hindi:
        if "translations" not in result:
            with st.spinner(tr("translating")):
                result["translations"] = translate_details(rows)
        translations, incomplete = result["translations"]
        if translations:
            st.caption(tr("auto_translation"))
        if incomplete:
            st.caption(tr("translation_missing"))

    st.html(f"<style>{RANKING_CSS}</style>")
    st.session_state.setdefault("ranking_mode", "overall")
    heading, map_column = st.columns([3, 2], vertical_alignment="center")
    heading.subheader(tr("results_heading"))
    with map_column, st.container(horizontal=True, horizontal_alignment="right"):
        has_map_results = any(row.ranking == st.session_state["ranking_mode"] for row in rows)
        open_results_map = st.button(
            tr("results_map_button"), icon=":material/map:", key="results_map", disabled=not has_map_results
        )
    ranking = st.segmented_control(
        tr("ranking_label"), RANKINGS,
        format_func=lambda key: tr(f"ranking_{key}"),
        selection_mode="single", required=True, key="ranking_mode",
    )
    origin_label = "distance_origin_map" if result["from_map"] else "distance_origin"
    st.caption(tr(origin_label, pin=result["pin"]))
    st.caption(tr(f"ranking_note_{ranking}"))
    ranked_rows = (row for row in rows if row.ranking == ranking)
    facilities = [list(evidence) for _, evidence in groupby(ranked_rows, key=lambda row: row.result_rank)]
    if not facilities:
        st.warning(tr("no_recommendations"))
    if open_results_map and facilities:
        show_results_map(facilities, translations, tr, result["from_map"], excluded_location_count)
    for facility in facilities:
        render_facility(facility, searched_services, hindi, translations, tr, service_label, ranking)
    st.caption(tr("confirm"))


def render_facility(evidence_rows, services, hindi, translations, tr, service_label, ranking):
    row = evidence_rows[0]
    evidence_by_service = {evidence.service: evidence for evidence in evidence_rows}

    with st.container(border=True):
        name = translations.get(row.facility_name, row.facility_name)
        rank = row.result_rank
        positive_count = row.high_count + row.medium_count
        medal = {1: "gold", 2: "silver", 3: "bronze"}.get(rank) if positive_count else None
        rank_label = tr(f"rank_{medal}") if medal else tr("rank_label", rank=rank)
        badge_class = f" rank-badge--{medal}" if medal else ""
        warning = ""
        if ranking == "nearest" and positive_count < len(services):
            warning_key = "rank_warning_partial" if positive_count else "rank_warning_low"
            label = escape(tr(warning_key))
            warning = (
                f' <span class="rank-evidence-warning" role="img" '
                f'aria-label="{label}" title="{label}">!</span>'
            )
        st.html(
            f'<div class="facility-rank-heading">'
            f'<span class="rank-badge{badge_class}" role="img" aria-label="{escape(rank_label)}">'
            f'<span class="rank-badge__number" aria-hidden="true">{rank}</span></span>'
            f'<h3>{escape(name)}{warning}</h3></div>'
        )
        address_parts = (row.address_line1, row.city, row.state, row.pin_clean)
        address = ", ".join(translations.get(part, part) for part in address_parts if part)
        if address:
            st.text(address)
        if row.location_flags:
            st.warning(tr("location_warning"))
        if row.phone:
            st.text(tr("facility_phone", phone=row.phone))
        distance = tr("distance", km=row.straight_line_km)
        if ranking == "overall":
            evidence_points = round(float(row.evidence_points), 1)
            distance_points = round(float(row.distance_points), 1)
            score = tr(
                "overall_breakdown", score=evidence_points + distance_points,
                evidence=evidence_points, distance=distance_points,
            )
            st.caption(f"{distance} · {score}")
        elif ranking == "confidence":
            st.caption(f'{distance} · {tr("confidence_score", score=100 * row.confidence_score)}')
        else:
            st.caption(distance)
        st.caption(tr("confidence_counts", high=row.high_count, medium=row.medium_count,
                      low=len(services) - row.high_count - row.medium_count))
        if len(services) > 1:
            supported = [service_label(service) for service in services
                         if evidence_by_service[service].confidence >= 2]
            uncertain = [service_label(service) for service in services
                         if evidence_by_service[service].confidence == 1]
            if supported:
                st.caption(tr("selected_supported", count=len(supported), total=len(services),
                              services=", ".join(supported)))
            if uncertain:
                st.caption(tr("selected_uncertain", services=", ".join(uncertain)))

        for service in services:
            evidence = evidence_by_service[service]
            color = {3: "#15803d", 2: "#b77905", 1: "#c24148"}[evidence.confidence]
            label = tr(f"confidence_{evidence.confidence}")
            reason = tr(f"reason_{evidence.evidence_reason}")
            st.html(
                f'<div style="border:1px solid color-mix(in srgb, {color} 60%, transparent);'
                f'border-left:4px solid {color};padding:.65rem .8rem;border-radius:.6rem">'
                f'<strong>{escape(service_label(service))}</strong> · {escape(label)}'
                f'<div>{escape(reason)}</div></div>'
            )
            if evidence.evidence_text:
                with st.expander(tr("view_evidence", service=service_label(service))):
                    render_excerpt(evidence.evidence_text, evidence.source_field,
                                   evidence.source_record_id, evidence.source_urls_json, hindi, translations, tr)
                    if evidence.counter_evidence_text:
                        st.caption(tr("counter_evidence"))
                        render_excerpt(evidence.counter_evidence_text, evidence.counter_source_field,
                                       evidence.counter_record_id, evidence.counter_source_urls_json,
                                       hindi, translations, tr)


def render_excerpt(text, field, source_id, source_urls_json, hindi, translations, tr):
    label = FIELDS.get(field, field) if hindi else field
    st.caption(tr("record_source", field=label, id=source_id))
    if text in translations and translations[text] != text:
        st.text(translations[text])
        st.caption(tr("original_excerpt"))
    st.text(text)
    urls = record_urls(source_urls_json)
    if urls:
        st.caption(tr("source_links"))
        st.html("<ul>" + "".join(
            f'<li><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">'
            f'{escape(urlsplit(url).netloc + urlsplit(url).path)}</a></li>'
            for url in urls
        ) + "</ul>")
        st.caption(tr("source_link_note"))


def record_urls(value):
    if not value:
        return []
    try:
        candidates = json.loads(value)
    except ValueError:
        candidates = value
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return []

    links = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        url = candidate.strip()
        if not url or re.search(r"[\s\\\x00-\x1f\x7f]", url):
            continue
        try:
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
                continue
        except ValueError:
            continue
        if url not in links:
            links.append(url)
    return links


if __name__ == "__main__":
    render()
