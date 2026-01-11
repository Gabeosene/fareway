import { WindowManager } from './WindowManager.js';

class App {
    constructor() {
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
            await fetch('http://localhost:8000/simulate/accident', { method: 'POST' });
        };

        window.setWeather = async (w) => {
            await fetch(`http://localhost:8000/admin/weather/${w}`, { method: 'POST' });
        };
    }

    async sendControl(action, speed = null) {
        const payload = { action };
        if (speed) payload.speed = speed;

        try {
            const resp = await fetch('http://localhost:8000/sim/control', {
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
            const response = await fetch('http://localhost:8000/live');
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
            // console.error(e);
        }
    }

    updateMap(links) {
        links.forEach(link => {
            let poly = this.polylines[link.id];

            if (!poly && link.coordinates && link.coordinates.length > 1) {
                let weight = link.type === 'transit' ? 4 : (link.capacity > 2000 ? 6 : 4);

                poly = L.polyline(link.coordinates, {
                    color: '#444', weight: weight, opacity: 0.8, lineCap: 'round'
                }).addTo(this.map);

                this.polylines[link.id] = poly;
            }

            if (!poly) return;

            // Color Logic
            let color = '#334155'; // Dark Grey (flow)
            if (link.ci > 0.4) color = '#00f2ff'; // Cyan (Active)
            if (link.ci > 0.6) color = '#ffcc00'; // Warning
            if (link.ci > 0.8) color = '#ff0055'; // Danger

            if (link.type === 'transit') color = '#a855f7'; // Purple

            poly.setStyle({
                color: color,
                weight: link.ci > 0.8 ? 6 : 4,
                opacity: link.ci > 0.1 ? 1.0 : 0.4
            });
        });
    }

    async updateCharts() {
        try {
            const resp = await fetch('http://localhost:8000/stats/history');
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
