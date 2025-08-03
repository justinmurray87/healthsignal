/* global mapboxgl, Tabletop */

// Configure these constants before deploying. The Google Sheet must be
// published with read-only access to the "Events" tab. MAPBOX_TOKEN
// should be kept secret; consider loading it via a separate config file
// or environment injection during build.
const SHEET_ID = 'YOUR_GOOGLE_SHEET_ID';
const MAPBOX_TOKEN = 'YOUR_MAPBOX_ACCESS_TOKEN';

// Set Mapbox access token
mapboxgl.accessToken = MAPBOX_TOKEN;

// Create the Mapbox map
const map = new mapboxgl.Map({
  container: 'map',
  style: 'mapbox://styles/mapbox/light-v11',
  center: [0, 20],
  zoom: 1.5,
  projection: 'globe'
});

// Store markers globally so we can filter them later
let markers = [];
let eventsData = [];

// Initialize the application
function init() {
  // Fetch data from Google Sheets using Tabletop
  Tabletop.init({
    key: SHEET_ID,
    simpleSheet: true,
    wanted: ['Events'],
    callback: (data) => {
      eventsData = data;
      renderMarkers();
    },
  });
  // Add listeners for filters
  document.getElementById('typeFilter').addEventListener('change', renderMarkers);
  document.getElementById('severityFilter').addEventListener('input', renderMarkers);
  document.getElementById('safeZoneBtn').addEventListener('click', toggleSafeZones);
  document.getElementById('helpBtn').addEventListener('click', openHelp);
}

// Render markers on the map based on current filters
function renderMarkers() {
  // Clear existing markers from map
  markers.forEach((m) => m.remove());
  markers = [];

  const typeFilter = document.getElementById('typeFilter').value;
  const severityThreshold = parseInt(document.getElementById('severityFilter').value, 10) || 0;

  eventsData.forEach((event) => {
    const lat = parseFloat(event.lat);
    const lng = parseFloat(event.lng);
    if (!lat || !lng) return;
    if (typeFilter && event.event_type !== typeFilter) return;
    const severity = parseInt(event.severity_score, 10) || 0;
    if (severity < severityThreshold) return;
    
    // Create a marker with color and size scaled by severity and impact
    const color = getColorForSeverity(severity);
    const peopleAffected = parseInt(event.people_affected, 10) || 0;
    const markerSize = getMarkerSize(severity, peopleAffected);
    
    const el = document.createElement('div');
    el.className = 'marker';
    el.style.backgroundColor = color;
    el.style.width = `${markerSize}px`;
    el.style.height = `${markerSize}px`;
    el.style.borderRadius = '50%';
    el.style.border = '2px solid rgba(255, 255, 255, 0.8)';
    el.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.3)';
    el.style.cursor = 'pointer';
    el.style.transition = 'transform 0.2s ease';
    
    // Add hover effects
    el.addEventListener('mouseenter', () => {
      el.style.transform = 'scale(1.2)';
      el.style.zIndex = '1000';
    });
    
    el.addEventListener('mouseleave', () => {
      el.style.transform = 'scale(1)';
      el.style.zIndex = 'auto';
    });
    
    const marker = new mapboxgl.Marker(el)
      .setLngLat([lng, lat])
      .addTo(map);
    marker.getElement().addEventListener('click', () => showInfo(event));
    markers.push(marker);
  });
}

// Convert severity (0–100) to a color on a red-yellow-green gradient
function getColorForSeverity(severity) {
  // Enhanced color scheme for better visibility on light background
  if (severity >= 80) {
    return '#dc2626'; // Red for critical
  } else if (severity >= 60) {
    return '#ea580c'; // Orange-red for severe
  } else if (severity >= 40) {
    return '#d97706'; // Orange for high
  } else if (severity >= 20) {
    return '#ca8a04'; // Yellow-orange for moderate
  } else {
    return '#65a30d'; // Green for low
  }
}

// Calculate marker size based on severity and people affected
function getMarkerSize(severity, peopleAffected) {
  // Base size between 8-24px based on severity
  const baseSizeFromSeverity = 8 + (severity / 100) * 16;
  
  // Additional size based on people affected (logarithmic scale)
  let sizeFromImpact = 0;
  if (peopleAffected > 0) {
    sizeFromImpact = Math.min(8, Math.log10(peopleAffected) * 2);
  }
  
  return Math.max(8, Math.min(32, baseSizeFromSeverity + sizeFromImpact));
}

// Display details about a selected event
function showInfo(event) {
  const info = document.getElementById('info');
  const donationLinks = safeParseJSON(event.donation_links) || [];
  const linksList = donationLinks
    .map((url) => `<li><a href="${url}" target="_blank" rel="noopener">${url}</a></li>`) // sanitize by default
    .join('');
  
  const severity = parseInt(event.severity_score, 10) || 0;
  const severityClass = severity >= 60 ? 'severity-high' : severity >= 30 ? 'severity-medium' : 'severity-low';
  
  info.innerHTML = `
    <div class="event-header">
      <h2>${event.location}</h2>
      <span class="event-type ${event.event_type.toLowerCase()}">${event.event_type}</span>
    </div>
    <p>${event.summary || ''}</p>
    <div class="event-stats">
      <div class="stat">
        <span class="stat-label">People affected:</span>
        <span class="stat-value">${parseInt(event.people_affected, 10).toLocaleString()}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Severity:</span>
        <span class="stat-value ${severityClass}">${event.severity_score}/100</span>
      </div>
    </div>
    ${linksList ? `
      <div class="donation-section">
        <h3>How to Help</h3>
        <ul class="donation-links">${linksList}</ul>
      </div>
    ` : ''}
  `;
}

// Toggle safe zones view – show only events below a certain severity
let showingSafeZones = false;
function toggleSafeZones() {
  showingSafeZones = !showingSafeZones;
  const severityInput = document.getElementById('severityFilter');
  if (showingSafeZones) {
    severityInput.value = '50';
  } else {
    severityInput.value = '0';
  }
  renderMarkers();
}

// Open help page – for now simply scrolls to the first donation link if present
function openHelp() {
  if (eventsData.length === 0) return;
  const first = eventsData[0];
  const links = safeParseJSON(first.donation_links);
  if (links && links.length > 0) {
    window.open(links[0], '_blank');
  }
}

// Parse JSON strings safely
function safeParseJSON(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

// Initialise once the page loads
window.addEventListener('DOMContentLoaded', () => {
  init();
  
  // Add map interaction enhancements
  map.on('load', () => {
    // Enable 3D terrain if available
    map.addSource('mapbox-dem', {
      'type': 'raster-dem',
      'url': 'mapbox://mapbox.mapbox-terrain-dem-v1',
      'tileSize': 512,
      'maxzoom': 14
    });
    
    // Add subtle terrain exaggeration for better global view
    map.setTerrain({ 'source': 'mapbox-dem', 'exaggeration': 0.5 });
    
    // Add atmosphere for globe view
    map.setFog({
      'color': 'rgb(186, 210, 235)',
      'high-color': 'rgb(36, 92, 223)',
      'horizon-blend': 0.02,
      'space-color': 'rgb(11, 11, 25)',
      'star-intensity': 0.6
    });
  });
});