const API_BASE = 'http://localhost:8000';
let currentLat = 52.52;
let currentLon = 13.41;
let currentLocationName = 'Berlin, Germany';
let forecastChartInstance = null;

document.addEventListener('DOMContentLoaded', () => {
	const searchButton = document.getElementById('searchButton');
	const locationInput = document.getElementById('locationInput');

	if (searchButton && locationInput) {
		searchButton.addEventListener('click', () => handleSearch(locationInput.value.trim()));
		locationInput.addEventListener('keydown', event => {
			if (event.key === 'Enter') {
				event.preventDefault();
				handleSearch(locationInput.value.trim());
			}
		});
	}

	initWeather();
});

async function initWeather() {
	if (navigator.geolocation) {
		showLoading(true);
		navigator.geolocation.getCurrentPosition(
			position => {
				const lat = position.coords.latitude;
				const lon = position.coords.longitude;
				currentLat = lat;
				currentLon = lon;
				fetchWeather(lat, lon);
				reverseGeocode(lat, lon);
			},
			error => {
				console.warn('Geolocation error:', error);
				fetchWeather(currentLat, currentLon);
				showError('Using default location. Please enable location permissions to use your current location.');
			}
		);
	} else {
		fetchWeather(currentLat, currentLon);
		showError('Geolocation is not supported by your browser. Using default location.');
	}
}

async function handleSearch(query) {
	if (!query) {
		showError('Please enter a city name or coordinates.');
		return;
	}

	hideError();
	showLoading(true);

	try {
		const response = await fetch(`${API_BASE}/search?location=${encodeURIComponent(query)}`);
		const data = await response.json();

		if (!response.ok || !data.success) {
			throw new Error(data.message || 'Location not found.');
		}

		currentLat = data.latitude;
		currentLon = data.longitude;
		currentLocationName = data.name || query;
		fetchWeather(currentLat, currentLon, currentLocationName);
	} catch (error) {
		showError(error.message || 'Unable to search location.');
		console.error(error);
		showLoading(false);
	}
}

async function fetchWeather(latitude, longitude, locationName = null) {
	try {
		showLoading(true);
		hideError();

		const response = await fetch(`${API_BASE}/weather?latitude=${latitude}&longitude=${longitude}`);
		if (!response.ok) {
			throw new Error('Failed to fetch weather data.');
		}

		const data = await response.json();

		if (locationName) {
			currentLocationName = locationName;
		}

		displayWeather(data);
		fetchWarnings(latitude, longitude);
	} catch (error) {
		showError('Error fetching weather data: ' + error.message);
		console.error(error);
	} finally {
		showLoading(false);
	}
}

function displayWeather(data) {
	const container = document.getElementById('weatherContainer');
	if (!container) return;

	const latitude = Number(data.latitude ?? currentLat).toFixed(2);
	const longitude = Number(data.longitude ?? currentLon).toFixed(2);
	const elevation = data.elevation ?? 'N/A';
	const temperature = data.current?.temperature_2m ?? 'N/A';
	const showers = data.current?.showers ?? 0;
	const currentTime = data.current?.time ? formatTime(data.current.time) : 'N/A';

	const currentWeather = `
		<div class="current-weather">
			<div class="weather-header">
				<div class="location-info">
					<h2 id="locationName">${currentLocationName}</h2>
					<p>Koordinaten: ${Math.round(latitude * 10) / 10}°N, ${Math.round(longitude * 10) / 10}°E</p>
					<p>Elevation: ${elevation} m</p>
				</div>
				<div class="current-temp">${Math.round(temperature * 1000) / 1000}°C</div>
			</div>
			<div class="weather-details">
				<div class="detail-card">
					<label>Aktuelle Temperatur</label>
					<div class="value">${Math.round(temperature * 1000) / 1000}°C</div>
				</div>
				<div class="detail-card">
					<label>Niederschlag</label>
					<div class="value">${Math.round(showers * 1000) / 1000} mm</div>
				</div>
			</div>
		</div>
	`;

	const hourlyWeather = `
		<div class="hourly-forecast">
			<h3>Stundenprognose</h3>
			<div style="position: relative; height: 400px; margin-bottom: 30px;">
				<canvas id="forecastChart"></canvas>
			</div>
			<div class="hourly-container">
				${(data.hourly ?? []).slice(0, 24).map(hour => `
					<div class="hourly-card">
						<div class="time">${formatHourlyTime(hour.date)}</div>
						<div class="temp">${hour.temperature_2m.toFixed(1)}°C</div>
						<div class="rain">${hour.showers.toFixed(1)} mm</div>
					</div>
				`).join('')}
			</div>
		</div>
	`;

	container.innerHTML = currentWeather + hourlyWeather;
	renderForecastChart((data.hourly ?? []).slice(0, 24));
}

async function fetchWarnings(latitude, longitude) {
	const container = document.getElementById('warningsContainer');
	if (!container) return;
	container.innerHTML = '<div class="warnings-loading">Warnungen werden geladen...</div>';

	try {
		const response = await fetch(`${API_BASE}/warnings?latitude=${latitude}&longitude=${longitude}`);
		const data = await response.json();
		displayWarnings(data);
	} catch (error) {
		container.innerHTML = `<div class="warnings-error">Fehler beim Laden der Warnungen: ${error.message}</div>`;
		console.error('Fehler beim Laden der Warnungen:', error);
	}
}

function displayWarnings(data) {
	const container = document.getElementById('warningsContainer');
	if (!container) return;

	if (!data.success) {
		container.innerHTML = `<div class="warnings-error">${data.message || 'Warnungen konnten nicht geladen werden.'}</div>`;
		return;
	}

	if (!data.warnings || data.warnings.length === 0) {
		container.innerHTML = `<div class="warnings-empty">Keine aktiven Warnungen für dieses Gebiet.</div>`;
		return;
	}

	const warningsHtml = data.warnings.map(warning => `
		<div class="warning-card">
			<h4>${warning.event || warning.headline || 'Wetterwarnung'}</h4>
<p><strong>Schweregrad:</strong> ${warning.severity || 'N/A'}</p>
				<p><strong>Beginn:</strong> ${warning.onset || 'N/A'}</p>
				<p><strong>Ende:</strong> ${warning.expires || 'N/A'}</p>
			<p>${warning.description || warning.instruction || ''}</p>
		</div>
	`).join('');

	container.innerHTML = `
		<div class="warnings-header">
			<h3>Wetterwarnungen</h3>
			<p>${data.warning_count || data.warnings.length} aktive Warnungen</p>
		</div>
		${warningsHtml}
	`;
}

function formatTime(value) {
	const date = parseDate(value);
	if (isNaN(date.getTime())) return String(value);
	return date.toLocaleString('de-de', {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
	});
}

function formatHourlyTime(value) {
	const date = parseDate(value);
	if (isNaN(date.getTime())) return String(value);
	return date.toLocaleString('de-de', {
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
	});
}

function parseDate(value) {
	if (typeof value === 'number') {
		return new Date(value < 1e12 ? value * 1000 : value);
	}

	if (typeof value === 'string') {
		if (/^\d{10}$/.test(value)) {
			return new Date(Number(value) * 1000);
		}
		if (/^\d{13}$/.test(value)) {
			return new Date(Number(value));
		}
	}

	return new Date(value);
}

function renderForecastChart(hourlyData) {
	const ctx = document.getElementById('forecastChart');
	if (!ctx) return;

	const labels = hourlyData.map(hour => formatHourlyTime(hour.date));
	const temperatures = hourlyData.map(hour => hour.temperature_2m);
	const showers = hourlyData.map(hour => hour.showers);

	if (forecastChartInstance) {
		forecastChartInstance.destroy();
	}

	forecastChartInstance = new Chart(ctx, {
		type: 'line',
		data: {
			labels,
			datasets: [
				{
					label: 'Temperatur (°C)',
					data: temperatures,
					borderColor: 'rgba(255, 99, 132, 1)',
					backgroundColor: 'rgba(255, 99, 132, 0.1)',
					tension: 0.3,
					yAxisID: 'y',
				},
				{
					label: 'Niederschlag (mm)',
					data: showers,
					borderColor: 'rgba(54, 162, 235, 1)',
					fill: false,
					tension: 0.3,
					yAxisID: 'y1',
				},
			],
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			plugins: {
				legend: {
					display: true,
					position: 'top',
				},
				title: {
					display: true,
					text: '24-Stunden-Vorhersage',
				},
			},
			scales: {
				y: {
					type: 'linear',
					display: true,
					position: 'left',
					title: {
						display: true,
						text: 'Temperatur (°C)',
					},
				},
				y1: {
					type: 'linear',
					display: true,
					position: 'right',
					title: {
						display: true,
						text: 'Niederschlag (mm)',
					},
					grid: {
						drawOnChartArea: false,
					},
				},
			},
		},
	});
}

function showLoading(show) {
	document.getElementById('loading').style.display = show ? 'block' : 'none';
}

function showError(message) {
	const errorDiv = document.getElementById('error');
	if (!message) {
		hideError();
		return;
	}
	errorDiv.innerHTML = `<div class="error">${message}</div>`;
	errorDiv.style.display = 'block';
}

function hideError() {
	const errorDiv = document.getElementById('error');
	errorDiv.innerHTML = '';
	errorDiv.style.display = 'none';
}

async function reverseGeocode(latitude, longitude) {
	try {
		const response = await fetch(`${API_BASE}/search?location=${latitude},${longitude}`);
		const data = await response.json();

		if (data.success && data.name) {
			currentLocationName = data.name;
			const locationNameElement = document.getElementById('locationName');
			if (locationNameElement) {
				locationNameElement.textContent = data.name;
			}
		}
	} catch (error) {
		console.error('Fehler bei der Rückwärtssuche:', error);
	}
}
