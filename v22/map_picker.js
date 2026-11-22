const leafletUrl = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const leafletCssUrl = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
let leafletPromise;

function loadLeaflet() {
  if (window.L?.version === "1.9.4") return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = leafletUrl;
      script.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
      script.crossOrigin = "anonymous";
      script.onload = () => window.L ? resolve(window.L) : reject(new Error("Leaflet unavailable"));
      script.onerror = () => {
        script.remove();
        reject(new Error("Leaflet failed to load"));
      };
      document.head.append(script);
    }).catch((error) => {
      leafletPromise = undefined;
      throw error;
    });
  }
  return leafletPromise;
}

function showFacilityMarkers(L, map, markers, origin, pinIcon) {
  const locations = new Map();
  for (const marker of markers) {
    const key = `${marker.lat},${marker.lon}`;
    if (!locations.has(key)) locations.set(key, []);
    locations.get(key).push(marker);
  }

  const points = [];
  for (const group of locations.values()) {
    const point = [group[0].lat, group[0].lon];
    points.push(point);
    const ranks = group.map(item => Number(item.rank)).join(" / ");
    const popup = document.createElement("div");
    for (const item of group) {
      const entry = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `${item.rank}. ${item.name}`;
      const distance = document.createElement("div");
      distance.textContent = item.distance;
      entry.append(title, distance);
      if (item.locationWarning) {
        const warning = document.createElement("div");
        warning.className = "facility-location-warning";
        warning.textContent = item.locationWarning;
        entry.append(warning);
      }
      popup.append(entry);
    }
    L.marker(point, {
      title: group.map(item => item.name).join(" / "),
      icon: L.divIcon({
        className: "facility-map-marker",
        html: ranks,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -14],
      }),
    }).addTo(map).bindPopup(popup);
  }

  const originPoint = [origin.lat, origin.lon];
  const originLabel = document.createElement("strong");
  originLabel.textContent = origin.label;
  L.marker(originPoint, {
    title: origin.label,
    alt: origin.label,
    zIndexOffset: 1000,
    icon: L.icon({
      iconUrl: pinIcon,
      className: "search-origin-pin",
      iconSize: [52, 52],
      iconAnchor: [26, 46],
      popupAnchor: [0, -39],
    }),
  }).addTo(map).bindPopup(originLabel);
  points.push(originPoint);
  map.fitBounds(points, { padding: [36, 36], maxZoom: 14 });
}

export default function ({ parentElement, data, setTriggerValue }) {
  const frame = parentElement.querySelector(".picker-map");
  const button = parentElement.querySelector(".picker-confirm");
  const status = parentElement.querySelector(".picker-status");
  const css = parentElement.querySelector(".picker-leaflet-css");
  css.integrity = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=";
  css.crossOrigin = "anonymous";
  css.href = leafletCssUrl;
  const resultsMap = Array.isArray(data.markers);
  const pickerPin = parentElement.querySelector(".picker-pin");
  pickerPin.hidden = resultsMap;
  if (!resultsMap) pickerPin.src = data.pinIcon;
  button.hidden = resultsMap;
  button.textContent = resultsMap ? "" : data.confirm;
  button.disabled = true;
  frame.setAttribute("aria-label", data.title);
  status.textContent = data.loading;
  let map;
  let closed = false;

  loadLeaflet().then((L) => {
    if (closed) return;
    const start = data.start || { lat: 22.5, lon: 79.0, zoom: 5 };
    map = L.map(frame, { zoomControl: false, minZoom: 4, maxZoom: 19 });
    map.setView([start.lat, start.lon], start.zoom);
    L.control.zoom({ zoomInTitle: data.zoomIn, zoomOutTitle: data.zoomOut }).addTo(map);
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      noWrap: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    if (resultsMap) {
      status.textContent = "";
      tiles.on("tileerror", () => { status.textContent = data.tilesError; });
      tiles.on("load", () => {
        if (!tiles.getContainer()?.querySelector(".leaflet-tile-loaded")) {
          status.textContent = data.tilesError;
        } else {
          status.textContent = "";
        }
      });
      requestAnimationFrame(() => {
        if (closed) return;
        map.invalidateSize();
        showFacilityMarkers(L, map, data.markers, data.origin, data.pinIcon);
      });
      return;
    }
    let tileError = false;
    let hasTiles = false;
    let submitted = false;
    const refresh = () => {
      const zoomed = map.getZoom() >= 11;
      button.disabled = !zoomed || !hasTiles || submitted;
      status.textContent = tileError ? data.tilesError : zoomed ? "" : data.zoomForPin;
    };
    tiles.on("tileerror", () => { tileError = true; refresh(); });
    tiles.on("tileload", () => { hasTiles = true; tileError = false; refresh(); });
    map.on("zoomend", refresh);
    button.onclick = () => {
      const center = map.getCenter().wrap();
      submitted = true;
      refresh();
      status.textContent = data.checking;
      setTriggerValue("confirmed", { lat: center.lat, lon: center.lng, zoom: map.getZoom() });
    };
    requestAnimationFrame(() => { if (!closed) map.invalidateSize(); });
    refresh();
  }).catch(() => {
    if (!closed) status.textContent = data.loadError;
  });

  return () => {
    closed = true;
    button.onclick = null;
    if (map) map.remove();
  };
}
