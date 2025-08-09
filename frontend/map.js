/* global mapboxgl, Tabletop */

// Configure these constants before deploying. The Google Sheet must be
// published with read-only access to the "Events" tab. MAPBOX_TOKEN
// should be kept secret; consider loading it via a separate config file
// or environment injection during build.
//temp token for local testing
//const MAPBOX_TOKEN = 'YOUR_MAPBOX_ACCESS_TOKEN';
const MAPBOX_TOKEN = 'pk.eyJ1IjoiaGVscHNpZ25hbCIsImEiOiJjbWR2dmh2NWcwbDNuMmxxNThnMDA1OTg1In0.L5jlQuL3rmaWz3UpNrxo0g';
// Set Mapbox access token
mapboxgl.accessToken = MAPBOX_TOKEN;

// Create the Mapbox map
const map = new mapboxgl.Map({
  container: 'map',
  style: 'mapbox://styles/mapbox/light-v10',
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
    url: 'https://docs.google.com/spreadsheets/d/1vw2RrQee4Lt-xIKoOw3B-U60GVim7resu2-8LgdZbh0/export?format=csv&gid=0',
    callback: (data) => {
      console.log("Data received from Google Sheet:", data);
      eventsData = data;
      renderMarkers();
    },
  });
  // Add listeners for filters
  document.getElementById('typeFilter').addEventListener('change', renderMarkers);
  document.getElementById('severityFilter').addEventListener('input', renderMarkers);
  document.getElementById('severityFilter').addEventListener('input', updateSeverityLabel);
  
  // Initialize severity label
  updateSeverityLabel();
  
  // Initialize ticker
  updateTicker();
  setInterval(updateTicker, 30000); // Update every 30 seconds
}

// Update severity label
function updateSeverityLabel() {
  const severityValue = document.getElementById('severityFilter').value;
  document.getElementById('severityValue').textContent = severityValue;
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
  info.classList.add('active');
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

// Update ticker with continental crisis summaries
function updateTicker() {
  if (eventsData.length === 0) {
    document.getElementById('tickerContent').innerHTML = '<span class="ticker-item">Loading global crisis data...</span>';
    return;
  }
  
  // Group events by continent (simplified)
  const continents = {
    'Africa': { starving: 0, conflict: 0, displaced: 0 },
    'Asia': { starving: 0, conflict: 0, displaced: 0 },
    'Europe': { starving: 0, conflict: 0, displaced: 0 },
    'Americas': { starving: 0, conflict: 0, displaced: 0 },
    'Oceania': { starving: 0, conflict: 0, displaced: 0 }
  };
  
  eventsData.forEach(event => {
    const continent = getContinent(event.location);
    const peopleAffected = parseInt(event.people_affected, 10) || 0;
    
    if (event.event_type === 'Famine') {
      continents[continent].starving += peopleAffected;
    } else if (event.event_type === 'War') {
      continents[continent].conflict += peopleAffected;
    } else {
      continents[continent].displaced += peopleAffected;
    }
  });
  
  // Generate ticker content
  const tickerItems = Object.entries(continents).map(([continent, stats]) => {
    const parts = [];
    if (stats.starving > 0) parts.push(`${formatNumber(stats.starving)} starving`);
    if (stats.conflict > 0) parts.push(`${formatNumber(stats.conflict)} in conflict`);
    if (stats.displaced > 0) parts.push(`${formatNumber(stats.displaced)} displaced`);
    
    return parts.length > 0 ? `${continent}: ${parts.join(', ')}` : null;
  }).filter(Boolean);
  
  if (tickerItems.length === 0) {
    tickerItems.push('No active crises detected');
  }
  
  document.getElementById('tickerContent').innerHTML = 
    tickerItems.map(item => `<span class="ticker-item">${item}</span>`).join('');
}

// Simple continent mapping based on location
function getContinent(location) {
  const loc = location.toLowerCase();
  if (loc.includes('africa') || loc.includes('nigeria') || loc.includes('kenya') || loc.includes('ethiopia') || loc.includes('sudan')) return 'Africa';
  if (loc.includes('asia') || loc.includes('china') || loc.includes('india') || loc.includes('japan') || loc.includes('afghanistan')) return 'Asia';
  if (loc.includes('europe') || loc.includes('ukraine') || loc.includes('france') || loc.includes('germany') || loc.includes('uk')) return 'Europe';
  if (loc.includes('america') || loc.includes('usa') || loc.includes('canada') || loc.includes('brazil') || loc.includes('mexico')) return 'Americas';
  if (loc.includes('australia') || loc.includes('oceania') || loc.includes('new zealand')) return 'Oceania';
  return 'Africa'; // Default
}

// Format numbers for display
function formatNumber(num) {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + 'M';
  } else if (num >= 1000) {
    return (num / 1000).toFixed(0) + 'K';
  }
  return num.toString();
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
      'color': 'rgb(220, 220, 220)',
      'high-color': 'rgb(180, 180, 180)',
      'horizon-blend': 0.02,
      'space-color': 'rgb(240, 240, 240)',
      'star-intensity': 0.2
    });
  });
  
  // Hide info panel when clicking on map
  map.on('click', () => {
    document.getElementById('info').classList.remove('active');
  });
});