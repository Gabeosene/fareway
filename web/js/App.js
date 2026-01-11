import { WindowManager } from './WindowManager.js';

class App {
    constructor() {
        this.apiBase = window.location.origin;
        this.wm = new WindowManager();
        this.map = null;
        this.polylines = {};
        this.chart = null;
        this.isChartRequestInFlight = false;
        this.liveStaleThresholdSec = 10;
        this.adminLinks = [];
        this.liveLinkIds = new Set();
        this.adminSelectionDirty = false;

        this.state = {
            paused: false,
            speed: 1.0,
            simTime: "00:00",
            viewMode: "live"
        };

        this.initMap();
        this.initChart();
        this.initListeners();
        this.initAdminLinks();
        this.setViewMode(this.state.viewMode);

        // Start Loops
        this.pollInterval = setInterval(() => this.pollState(), 500);
        this.chartPollInterval = setInterval(() => this.updateCharts(), 10000);
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
        // View Toggle
        const liveBtn = document.getElementById('btn-view-live');
        const simBtn = document.getElementById('btn-view-sim');
        if (liveBtn && simBtn) {
            liveBtn.onclick = () => this.setViewMode('live');
            simBtn.onclick = () => this.setViewMode('simulator');
        }

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

        const liveAllBtn = document.getElementById('btn-live-all');
        if (liveAllBtn) {
            liveAllBtn.onclick = () => this.enableAllLiveLinks();
        }

        const refreshAdminLinksBtn = document.getElementById('btn-admin-refresh-links');
        if (refreshAdminLinksBtn) {
            refreshAdminLinksBtn.onclick = () => this.initAdminLinks();
        }

        const applyAdminLinksBtn = document.getElementById('btn-admin-apply-links');
        if (applyAdminLinksBtn) {
            applyAdminLinksBtn.onclick = () => this.applyAdminLiveLinks();
        }
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

    async enableAllLiveLinks() {
        try {
            await fetch(`${this.apiBase}/admin/live-links`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'all' })
            });
            this.adminSelectionDirty = false;
            await this.fetchLiveLinks();
            this.renderAdminLinks();
            this.pollState();
        } catch (e) {
            console.error("Enable live links failed", e);
        }
    }

    async initAdminLinks() {
        await Promise.all([this.fetchAdminLinks(), this.fetchLiveLinks()]);
        this.adminSelectionDirty = false;
        this.renderAdminLinks();
    }

    async fetchAdminLinks() {
        const listEl = document.getElementById('admin-live-list');
        try {
            const resp = await fetch(`${this.apiBase}/admin/links`);
            const data = await resp.json();
            this.adminLinks = (data.links || []).slice().sort((a, b) => a.name.localeCompare(b.name));
        } catch (e) {
            console.error("Admin links fetch failed", e);
            if (listEl && !this.adminLinks.length) {
                listEl.innerHTML = '<div style="color: var(--text-dim); font-size: 12px;">Unable to load links.</div>';
            }
        }
    }

    async fetchLiveLinks() {
        try {
            const resp = await fetch(`${this.apiBase}/admin/live-links`);
            const data = await resp.json();
            this.liveLinkIds = new Set(data.live_mode_links || []);
        } catch (e) {
            console.error("Live links fetch failed", e);
        }
    }

    renderAdminLinks() {
        const listEl = document.getElementById('admin-live-list');
        if (!listEl) return;

        listEl.innerHTML = '';

        if (!this.adminLinks.length) {
            const empty = document.createElement('div');
            empty.style.color = 'var(--text-dim)';
            empty.style.fontSize = '12px';
            empty.textContent = 'No links available.';
            listEl.appendChild(empty);
            this.updateAdminSummary();
            return;
        }

        this.adminLinks.forEach(link => {
            const item = document.createElement('label');
            item.className = 'live-feed-item fresh';
            item.style.cursor = 'pointer';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = this.liveLinkIds.has(link.id);
            checkbox.dataset.linkId = link.id;
            checkbox.style.marginRight = '8px';
            checkbox.onchange = () => {
                this.adminSelectionDirty = true;
                if (checkbox.checked) {
                    this.liveLinkIds.add(link.id);
                } else {
                    this.liveLinkIds.delete(link.id);
                }
                this.updateAdminSummary();
            };

            const name = document.createElement('div');
            name.className = 'live-feed-name';
            name.textContent = link.name;

            const meta = document.createElement('div');
            meta.className = 'live-feed-meta';
            meta.textContent = link.type ? link.type.toUpperCase() : 'LINK';

            item.appendChild(checkbox);
            item.appendChild(name);
            item.appendChild(meta);
            listEl.appendChild(item);
        });

        this.updateAdminSummary();
    }

    updateAdminSummary() {
        const summaryEl = document.getElementById('admin-live-summary');
        if (!summaryEl) return;
        const total = this.adminLinks.length;
        const liveCount = this.liveLinkIds.size;
        summaryEl.innerText = `${liveCount} live link${liveCount === 1 ? '' : 's'} selected${total ? ` • ${total} total` : ''}`;
    }

    async applyAdminLiveLinks() {
        try {
            const resp = await fetch(`${this.apiBase}/admin/live-links`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ link_ids: Array.from(this.liveLinkIds) })
            });
            const data = await resp.json();
            this.liveLinkIds = new Set(data.live_mode_links || []);
            this.adminSelectionDirty = false;
            this.renderAdminLinks();
            this.pollState();
        } catch (e) {
            console.error("Apply live links failed", e);
        }
    }

    setViewMode(mode) {
        this.state.viewMode = mode;
        const isSim = mode === 'simulator';
        document.body.classList.toggle('sim-view', isSim);

        const liveBtn = document.getElementById('btn-view-live');
        const simBtn = document.getElementById('btn-view-sim');
        if (liveBtn) liveBtn.classList.toggle('active', !isSim);
        if (simBtn) simBtn.classList.toggle('active', isSim);
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
            const simTimeEl = document.getElementById('sim-time');
            if (simTimeEl) simTimeEl.innerText = data.sim_time;

            // Sync Controls if externall changed
            if (data.control) this.updateControlUI(data.control);

            // Links
            this.updateMap(data.links);

            // Stats Panels
            this.updateStats(data);

        } catch (e) {
            console.error("Poll Error:", e);
        }
    }

    updateMap(links) {
        const currentLinkIds = new Set(links.map(link => link.id));

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

            const updateLine = document.createElement('div');
            const sourceLabel = link.last_observation_source ? `Source: ${link.last_observation_source}` : 'Source: --';
            const ageLabel = this.formatAge(link.age_sec);
            updateLine.textContent = `${sourceLabel} • Updated: ${ageLabel}`;
            content.appendChild(updateLine);

            if (!polyGroup.core.getPopup()) {
                polyGroup.core.bindPopup(content, { closeButton: false, autoPan: false });
            } else {
                polyGroup.core.setPopupContent(content);
            }
        });

        Object.entries(this.polylines).forEach(([linkId, polyGroup]) => {
            if (currentLinkIds.has(linkId)) return;
            this.map.removeLayer(polyGroup.core);
            this.map.removeLayer(polyGroup.glow);
            delete this.polylines[linkId];
        });
    }

    async updateCharts() {
        if (this.isChartRequestInFlight) return;
        this.isChartRequestInFlight = true;
        try {
            const resp = await fetch(`${this.apiBase}/stats/history`);
            const history = await resp.json();

            this.chart.data.labels = history.map(() => '');
            this.chart.data.datasets[0].data = history.map(h => h.avg_ci);
            this.chart.data.datasets[1].data = history.map(h => h.sensitivity);
            this.chart.update();
        } catch (e) { 
            console.error("Chart update failed", e);
        } finally {
            this.isChartRequestInFlight = false;
        }
    }

    updateStats(data) {
        // Update Policy Panel
        const pol = data.policy;
        document.getElementById('sens-display').innerText = pol.sensitivity.toFixed(1);
        if (typeof pol.live_stale_threshold_sec === 'number') {
            this.liveStaleThresholdSec = pol.live_stale_threshold_sec;
        }

        let aggr = "NORMAL";
        if (pol.aggressiveness > 1.5) aggr = "HIGH";
        if (pol.aggressiveness < 0.5) aggr = "LOW";
        document.getElementById('aggr-display').innerText = aggr;

        // Weather
        document.getElementById('weather-display').innerText = data.weather;

        // Live Feed
        this.updateLiveFeed(data.links);
        this.syncAdminSelectionFromLive(data.links);
        this.updateLinkTelemetry(data.links);
    }

    updateLiveFeed(links) {
        const liveLinks = links.filter(link => link.is_live);
        const summaryEl = document.getElementById('live-feed-summary');
        const listEl = document.getElementById('live-feed-list');

        listEl.innerHTML = '';

        if (liveLinks.length === 0) {
            summaryEl.innerText = 'No live links configured';
            return;
        }

        let staleCount = 0;

        liveLinks.forEach(link => {
            const ageSec = link.age_sec;
            const isStale = typeof ageSec === 'number' ? ageSec > this.liveStaleThresholdSec : true;
            if (isStale) staleCount += 1;

            const item = document.createElement('div');
            item.className = `live-feed-item ${isStale ? 'stale' : 'fresh'}`;

            const dot = document.createElement('span');
            dot.className = 'live-feed-dot';
            item.appendChild(dot);

            const name = document.createElement('div');
            name.className = 'live-feed-name';
            name.textContent = link.name;
            item.appendChild(name);

            const meta = document.createElement('div');
            meta.className = 'live-feed-meta';
            meta.textContent = `${this.formatAge(ageSec)} • ${link.last_observation_source || 'unknown'}`;
            item.appendChild(meta);

            listEl.appendChild(item);
        });

        summaryEl.innerText = `${liveLinks.length} live link${liveLinks.length === 1 ? '' : 's'} • ${staleCount} stale (> ${this.liveStaleThresholdSec}s)`;
    }

    updateLinkTelemetry(links) {
        const bodyEl = document.getElementById('link-data-body');
        if (!bodyEl) return;

        bodyEl.innerHTML = '';

        if (!Array.isArray(links) || links.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'data-empty';
            empty.textContent = 'No telemetry available yet.';
            bodyEl.appendChild(empty);
            return;
        }

        const sorted = [...links].sort((a, b) => (b.ci ?? 0) - (a.ci ?? 0));
        sorted.slice(0, 10).forEach(link => {
            const row = document.createElement('div');
            row.className = 'data-row';

            const nameCell = document.createElement('div');
            nameCell.className = 'data-cell-name';
            nameCell.textContent = link.name;

            if (link.is_live) {
                const badge = document.createElement('span');
                badge.className = 'data-badge';
                badge.textContent = 'Live';
                nameCell.appendChild(badge);
            }

            const flowCell = document.createElement('div');
            flowCell.textContent = `${link.flow}/${link.capacity}`;

            const ciCell = document.createElement('div');
            const ciValue = Number.isFinite(link.ci) ? link.ci.toFixed(2) : '--';
            ciCell.textContent = ciValue;
            if (link.ci > 0.8) ciCell.classList.add('data-ci-high');
            else if (link.ci > 0.6) ciCell.classList.add('data-ci-mid');

            const priceCell = document.createElement('div');
            priceCell.textContent = `${link.price} HUF`;

            row.appendChild(nameCell);
            row.appendChild(flowCell);
            row.appendChild(ciCell);
            row.appendChild(priceCell);
            bodyEl.appendChild(row);
        });
    }

    syncAdminSelectionFromLive(links) {
        if (this.adminSelectionDirty) return;
        const liveIds = new Set(links.filter(link => link.is_live).map(link => link.id));
        let changed = false;
        if (liveIds.size !== this.liveLinkIds.size) {
            changed = true;
        } else {
            for (const id of liveIds) {
                if (!this.liveLinkIds.has(id)) {
                    changed = true;
                    break;
                }
            }
        }

        if (!changed) return;
        this.liveLinkIds = liveIds;
        const listEl = document.getElementById('admin-live-list');
        if (listEl) {
            listEl.querySelectorAll('input[type="checkbox"][data-link-id]').forEach(input => {
                input.checked = this.liveLinkIds.has(input.dataset.linkId);
            });
        }
        this.updateAdminSummary();
    }

    formatAge(ageSec) {
        if (typeof ageSec !== 'number') return 'no data';
        if (ageSec < 1) return 'just now';
        if (ageSec < 60) return `${Math.round(ageSec)}s ago`;
        const minutes = Math.floor(ageSec / 60);
        return `${minutes}m ago`;
    }
}

// Boot
window.onload = () => {
    window.app = new App();
};
