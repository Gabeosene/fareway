import { WindowManager } from './WindowManager.js';

class App {
    constructor() {
        this.apiBase = window.location.origin;
        this.wm = new WindowManager();
        this.map = null;
        this.polylines = {};
        this.chart = null;

        this.state = {
            paused: false,
            speed: 1.0,
            simTime: "00:00"
        };

        this.initMap();
        this.initChart();
        this.initListeners();

        // Start Loops
        this.pollInterval = setInterval(() => this.pollState(), 500);
    }

    initMap() {
        this.map = L.map('map', {
            zoomControl: false,
            attributionControl: false
        }).setView([47.4979, 19.0402], 13);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(this.map);
    }

    initChart() {
        const ctx = document.getElementById('mainChart').getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(0, 242, 255, 0.5)');
        gradient.addColorStop(1, 'rgba(0, 242, 255, 0.0)');

        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Congestion (CI)',
                        borderColor: '#ff0055',
                        data: [],
                        tension: 0.4,
                        borderWidth: 2,
                        pointRadius: 0
                    },
                    {
                        label: 'Sensitivity',
                        borderColor: '#00f2ff',
                        backgroundColor: gradient,
                        fill: true,
                        data: [],
                        yAxisID: 'y1',
                        tension: 0.4,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: { display: false },
                    y: { min: 0, max: 1.0, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y1: { min: 0, max: 10, position: 'right', grid: { display: false } }
                },
                plugins: { legend: { display: false } }
            }
        });
    }

    initListeners() {
        // Time Controls
        document.getElementById('btn-play').onclick = () => this.sendControl('PLAY');
        document.getElementById('btn-pause').onclick = () => this.sendControl('PAUSE');
        document.getElementById('btn-step').onclick = () => this.sendControl('STEP');

        document.getElementById('btn-speed-1').onclick = () => this.sendControl('SPEED', 1.0);
        document.getElementById('btn-speed-2').onclick = () => this.sendControl('SPEED', 2.0);
        document.getElementById('btn-speed-5').onclick = () => this.sendControl('SPEED', 5.0);

        // God Mode
        window.triggerAccident = async () => {
            await fetch(`${this.apiBase}/simulate/accident`, { method: 'POST' });
        };

        window.setWeather = async (w) => {
            await fetch(`${this.apiBase}/admin/weather/${w}`, { method: 'POST' });
        };

        document.getElementById('btn-quote').onclick = () => this.generateQuote();
    }

    async generateQuote() {
        // Hardcoded for demo simplicity as per UI "Active User: Szabó Éva"
        const userId = "u_eq";
        const linkId = "link_szechenyi"; // Default target

        try {
            const resp = await fetch(`${this.apiBase}/api/quote`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, link_id: linkId })
            });
            const data = await resp.json();
            console.log("Quote:", data);

            // Update UI
            document.getElementById('quote-result').style.display = 'block';
            document.getElementById('quote-help').style.display = 'none';
            document.getElementById('quote-price').innerText = `${data.final_price} HUF`;

            const discEl = document.getElementById('quote-discount');
            if (data.discount_amount > 0) {
                discEl.innerText = `Saved ${data.discount_amount} HUF (Green Disc.)`;
            } else {
                discEl.innerText = 'Standard Rate';
            }

        } catch (e) {
            console.error(e);
            // alert("Error generating quote");
        }
    }

    async sendControl(action, speed = null) {
        const payload = { action };
        if (speed) payload.speed = speed;

        try {
            const resp = await fetch(`${this.apiBase}/sim/control`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();
            this.updateControlUI(data);
        } catch (e) {
            console.error("Control failed", e);
        }
    }

    updateControlUI(data) {
        this.state.paused = data.paused;
        this.state.speed = data.speed;

        // Update Buttons state
        const playBtn = document.getElementById('btn-play');
        const pauseBtn = document.getElementById('btn-pause');

        if (this.state.paused) {
            pauseBtn.classList.add('active');
            playBtn.classList.remove('active');
        } else {
            playBtn.classList.add('active');
            pauseBtn.classList.remove('active');
        }

        // Speed
        document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
        if (this.state.speed >= 5) document.getElementById('btn-speed-5').classList.add('active');
        else if (this.state.speed >= 2) document.getElementById('btn-speed-2').classList.add('active');
        else document.getElementById('btn-speed-1').classList.add('active');
    }

    async pollState() {
        try {
            const response = await fetch(`${this.apiBase}/live`);
            const data = await response.json();

            // Global Updates
            document.getElementById('sim-time').innerText = data.sim_time;

            // Sync Controls if externall changed
            if (data.control) this.updateControlUI(data.control);

            // Links
            this.updateMap(data.links);

            // Charts
            this.updateCharts();

            // Stats Panels
            this.updateStats(data);

        } catch (e) {
            console.error("Poll Error:", e);
        }
    }

    updateMap(links) {
        links.forEach(link => {
            let polyGroup = this.polylines[link.id];

            if (!polyGroup && link.coordinates && link.coordinates.length > 1) {
                // 1. Glow Line (RESTORING NEON GLOW)
                const glowColor = link.type === 'transit' ? '#a855f7' : (link.ci > 0.8 ? '#ff0055' : '#00f2ff');
                const glow = L.polyline(link.coordinates, {
                    color: glowColor,
                    weight: link.type === 'transit' ? 8 : 12,
                    opacity: 0.2,
                    lineCap: 'round',
                    className: 'glow-layer'
                }).addTo(this.map);

                // 2. Core Line
                let weight = link.type === 'transit' ? 3 : (link.capacity > 2000 ? 5 : 3);
                const dash = link.type === 'transit' ? '5, 8' : null;

                const core = L.polyline(link.coordinates, {
                    color: '#444',
                    weight: weight,
                    opacity: 1.0,
                    lineCap: 'round',
                    dashArray: dash
                }).addTo(this.map);

                this.polylines[link.id] = { core: core, glow: glow };
                polyGroup = this.polylines[link.id];
            }

            if (!polyGroup) return;

            // Color Logic Matches Style.css Neon
            let color = '#334155'; // Dark Grey (flow)
            let glowColor = '#334155';

            if (link.ci > 0.4) { color = '#00f2ff'; glowColor = '#00f2ff'; } // Cyan (Active)
            if (link.ci > 0.6) { color = '#ffcc00'; glowColor = '#ffcc00'; } // Warning
            if (link.ci > 0.8) { color = '#ff0055'; glowColor = '#ff0055'; } // Danger

            if (link.type === 'transit') {
                color = '#a855f7';
                glowColor = '#a855f7';
            }

            // Update Core
            polyGroup.core.setStyle({
                color: color,
                weight: link.ci > 0.8 ? 6 : (link.type === 'transit' ? 3 : 5),
                opacity: link.ci > 0.1 ? 1.0 : 0.4
            });

            // Update Glow
            polyGroup.glow.setStyle({
                color: glowColor,
                opacity: link.ci > 0.1 ? 0.25 : 0.05
            });

            // Popup / Tooltip
            const content = document.createElement('div');
            content.style.fontFamily = "'Courier New'";
            content.style.fontSize = '12px';

            const nameEl = document.createElement('strong');
            nameEl.textContent = link.name;
            content.appendChild(nameEl);
            content.appendChild(document.createElement('br'));

            const badge = document.createElement('span');
            badge.textContent = link.is_live ? '[LIVE FEED]' : '[SIMULATED]';
            badge.style.color = link.is_live ? '#00ff00' : '#888';
            if (link.is_live) {
                badge.style.fontWeight = 'bold';
            }
            content.appendChild(badge);
            content.appendChild(document.createElement('br'));

            const flowLine = document.createElement('div');
            flowLine.append('Flow: ', String(link.flow), ' / ', String(link.capacity));
            content.appendChild(flowLine);

            const ciLine = document.createElement('div');
            const ciValue = Number.isFinite(link.ci) ? link.ci.toFixed(2) : String(link.ci);
            ciLine.append('CI: ', ciValue);
            content.appendChild(ciLine);

            const priceLine = document.createElement('div');
            const priceLabel = document.createElement('span');
            priceLabel.textContent = 'Price: ';
            const priceValue = document.createElement('b');
            priceValue.textContent = String(link.price);
            priceLine.append(priceLabel, priceValue, ' HUF');
            content.appendChild(priceLine);

            if (!polyGroup.core.getPopup()) {
                polyGroup.core.bindPopup(content, { closeButton: false, autoPan: false });
            } else {
                polyGroup.core.setPopupContent(content);
            }
        });
    }

    async updateCharts() {
        try {
            const resp = await fetch(`${this.apiBase}/stats/history`);
            const history = await resp.json();

            this.chart.data.labels = history.map(() => '');
            this.chart.data.datasets[0].data = history.map(h => h.avg_ci);
            this.chart.data.datasets[1].data = history.map(h => h.sensitivity);
            this.chart.update();
        } catch (e) { }
    }

    updateStats(data) {
        // Update Policy Panel
        const pol = data.policy;
        document.getElementById('sens-display').innerText = pol.sensitivity.toFixed(1);

        let aggr = "NORMAL";
        if (pol.aggressiveness > 1.5) aggr = "HIGH";
        if (pol.aggressiveness < 0.5) aggr = "LOW";
        document.getElementById('aggr-display').innerText = aggr;

        // Weather
        document.getElementById('weather-display').innerText = data.weather;
    }
}

// Boot
window.onload = () => {
    window.app = new App();
};
