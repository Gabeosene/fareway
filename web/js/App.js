import { WindowManager } from './WindowManager.js';

class App {
    constructor() {
        this.apiBase = window.location.origin;
        this.wm = new WindowManager();
        this.map = null;
        this.polylines = {};
        this.liveMarkers = {};
        this.chart = null;
        this.isChartRequestInFlight = false;
        this.isPollRequestInFlight = false;
        this.isRoutePollInFlight = false;
        this.pollIntervalMs = 1500;
        this.focusedPollIntervalMs = 6000;
        this.routePollIntervalMs = 333;
        this.chartPollIntervalMs = 10000;
        this.uiRefreshMs = 2000;
        this.lastUiRefreshAt = 0;
        this.liveStaleThresholdSec = 10;
        this.adminLinks = [];
        this.liveLinkIds = new Set();
        this.adminSelectionDirty = false;
        this.geometryLoaded = false;
        this.linkMeta = new Map();
        this.linkStateCache = new Map();
        this.linkStyleCache = new Map();
        this.lastLinks = [];
        this.lastFullPollAt = 0;
        this.lastRouteStyleIds = new Set();
        this.focusedMode = false;
        this.route = {
            startLinkId: null,
            endLinkId: null,
            plannedLinkIds: [],
            plannedLinkSet: new Set(),
            plannedLengthM: null,
            activeLinkIds: new Set(),
            activeLengthM: null,
            planMessage: null
        };

        this.state = {
            paused: false,
            speed: 1.0,
            simTime: "00:00",
            viewMode: "live",
            showLiveMarkers: true
        };

        this.pollInterval = null;
        this.routePollInterval = null;
        this.chartPollInterval = null;
    }

    async bootstrap() {
        this.initMap();
        this.initChart();
        this.initListeners();
        await this.initAdminLinks();
        await this.fetchActiveRoute();
        this.setViewMode(this.state.viewMode);
        this.pollState();

        // Start Loops
        this.pollInterval = setInterval(() => this.pollState(), this.pollIntervalMs);
        if (this.route.activeLinkIds.size > 0) {
            this.startRoutePolling();
        }
        this.chartPollInterval = setInterval(() => this.updateCharts(), this.chartPollIntervalMs);
    }

    initMap() {
        this.map = L.map('map', {
            zoomControl: false,
            attributionControl: false,
            preferCanvas: true
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

        const markerToggle = document.getElementById('toggle-markers');
        if (markerToggle) {
            markerToggle.checked = this.state.showLiveMarkers;
            markerToggle.onchange = () => {
                this.state.showLiveMarkers = markerToggle.checked;
                if (this.state.showLiveMarkers) {
                    this.updateLiveMarkers(this.lastLinks || []);
                } else {
                    this.clearLiveMarkers();
                }
            };
        }

        const planRouteBtn = document.getElementById('btn-route-plan');
        if (planRouteBtn) {
            planRouteBtn.onclick = () => this.planRoute();
        }

        const activateRouteBtn = document.getElementById('btn-route-activate');
        if (activateRouteBtn) {
            activateRouteBtn.onclick = () => this.activateRoute();
        }

        const clearRouteBtn = document.getElementById('btn-route-clear');
        if (clearRouteBtn) {
            clearRouteBtn.onclick = () => this.clearRouteSelection();
        }

        const focusRouteBtn = document.getElementById('btn-route-focus');
        if (focusRouteBtn) {
            focusRouteBtn.onclick = () => this.toggleFocusMode();
        }
    }

    async generateQuote() {
        // Hardcoded for demo simplicity as per UI "Active User: Szabó Éva"
        const userId = "u_eq";
        let linkId = this.route.startLinkId;
        if (!linkId && this.route.plannedLinkIds.length) {
            linkId = this.route.plannedLinkIds[0];
        }
        if (!linkId && this.route.activeLinkIds.size) {
            linkId = Array.from(this.route.activeLinkIds)[0];
        }
        if (!linkId) {
            linkId = "link_szechenyi";
        }

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

    async fetchActiveRoute() {
        try {
            const resp = await fetch(`${this.apiBase}/route/active`);
            const data = await resp.json();
            if (data.active && data.route) {
                this.setActiveRoute(data.route);
            } else {
                this.setActiveRoute(null);
            }
        } catch (e) {
            console.error("Active route fetch failed", e);
            this.updateRouteUI();
        }
    }

    handleLinkSelection(linkId) {
        if (!linkId) return;

        if (linkId === this.route.startLinkId) {
            this.route.startLinkId = null;
            this.route.endLinkId = null;
            this.clearPlannedRoute();
        } else if (linkId === this.route.endLinkId) {
            this.route.endLinkId = null;
            this.clearPlannedRoute();
        } else if (!this.route.startLinkId || this.route.endLinkId) {
            this.route.startLinkId = linkId;
            this.route.endLinkId = null;
            this.clearPlannedRoute();
        } else {
            this.route.endLinkId = linkId;
        }

        this.updateRouteUI();
        this.refreshRouteStyles();
    }

    clearRouteSelection() {
        this.route.startLinkId = null;
        this.route.endLinkId = null;
        this.clearPlannedRoute();
        this.updateRouteUI();
        this.refreshRouteStyles();
    }

    clearPlannedRoute() {
        this.route.plannedLinkIds = [];
        this.route.plannedLinkSet = new Set();
        this.route.plannedLengthM = null;
        this.route.planMessage = null;
    }

    setPlannedRoute(linkIds, lengthM) {
        const ids = Array.isArray(linkIds) ? linkIds : [];
        this.route.plannedLinkIds = ids;
        this.route.plannedLinkSet = new Set(ids);
        this.route.plannedLengthM = typeof lengthM === 'number' ? lengthM : null;
    }

    setActiveRoute(route) {
        if (!route || !Array.isArray(route.link_ids) || route.link_ids.length === 0) {
            this.route.activeLinkIds = new Set();
            this.route.activeLengthM = null;
            this.stopRoutePolling();
            this.setFocusedMode(false, true);
        } else {
            this.route.activeLinkIds = new Set(route.link_ids);
            this.route.activeLengthM = typeof route.total_length_m === 'number' ? route.total_length_m : null;
            if (route.start_link_id) {
                this.route.startLinkId = route.start_link_id;
            }
            if (route.end_link_id) {
                this.route.endLinkId = route.end_link_id;
            }
            this.startRoutePolling();
            this.setFocusedMode(true, true);
        }
        this.updateRouteUI();
        this.refreshRouteStyles();
    }

    updateRouteUI() {
        const startEl = document.getElementById('route-start');
        const endEl = document.getElementById('route-end');
        const planSummaryEl = document.getElementById('route-plan-summary');
        const activeSummaryEl = document.getElementById('route-active-summary');
        const focusBtn = document.getElementById('btn-route-focus');

        if (startEl) {
            startEl.textContent = this.route.startLinkId ? this.getLinkNameById(this.route.startLinkId) : '--';
        }
        if (endEl) {
            endEl.textContent = this.route.endLinkId ? this.getLinkNameById(this.route.endLinkId) : '--';
        }

        if (planSummaryEl) {
            planSummaryEl.classList.remove('route-summary-error');
            if (this.route.planMessage) {
                planSummaryEl.textContent = this.route.planMessage;
                planSummaryEl.classList.add('route-summary-error');
            } else if (this.route.plannedLinkIds.length) {
                const lengthLabel = this.formatDistance(this.route.plannedLengthM);
                planSummaryEl.textContent = `Planned: ${this.route.plannedLinkIds.length} links (${lengthLabel})`;
            } else {
                planSummaryEl.textContent = 'No route planned.';
            }
        }

        if (activeSummaryEl) {
            if (this.route.activeLinkIds.size) {
                const lengthLabel = this.formatDistance(this.route.activeLengthM);
                activeSummaryEl.textContent = `Active: ${this.route.activeLinkIds.size} links (${lengthLabel})`;
            } else {
                activeSummaryEl.textContent = 'No active route.';
            }
        }

        const planBtn = document.getElementById('btn-route-plan');
        if (planBtn) {
            planBtn.disabled = !(this.route.startLinkId && this.route.endLinkId);
        }
        const activateBtn = document.getElementById('btn-route-activate');
        if (activateBtn) {
            activateBtn.disabled = this.route.plannedLinkIds.length === 0;
        }
        const clearBtn = document.getElementById('btn-route-clear');
        if (clearBtn) {
            clearBtn.disabled = !(
                this.route.startLinkId ||
                this.route.endLinkId ||
                this.route.plannedLinkIds.length
            );
        }

        if (focusBtn) {
            const hasActive = this.route.activeLinkIds.size > 0;
            focusBtn.disabled = !hasActive;
            focusBtn.textContent = this.focusedMode ? 'Show Full Map' : 'Focus Route';
            focusBtn.classList.toggle('primary', this.focusedMode);
        }
    }

    formatDistance(meters) {
        if (typeof meters !== 'number' || Number.isNaN(meters)) {
            return '--';
        }
        if (meters < 1000) {
            return `${Math.round(meters)} m`;
        }
        return `${(meters / 1000).toFixed(2)} km`;
    }

    getRouteStyleIds() {
        const ids = new Set();
        if (this.route.startLinkId) ids.add(this.route.startLinkId);
        if (this.route.endLinkId) ids.add(this.route.endLinkId);
        this.route.plannedLinkSet.forEach(id => ids.add(id));
        this.route.activeLinkIds.forEach(id => ids.add(id));
        return ids;
    }

    updateRouteStyleById(linkId) {
        const polyGroup = this.polylines[linkId];
        if (!polyGroup) return;
        const state = this.linkStateCache.get(linkId) || this.getFallbackLinkState(linkId);
        if (!state) return;
        const style = this.getLinkStyle(state, state.type || 'road');
        this.applyLinkStyle(linkId, polyGroup, style);
    }

    refreshRouteStyles() {
        const nextIds = this.getRouteStyleIds();
        const affected = new Set([...nextIds, ...this.lastRouteStyleIds]);
        this.lastRouteStyleIds = nextIds;
        affected.forEach(linkId => this.updateRouteStyleById(linkId));
    }

    toggleFocusMode() {
        if (!this.route.activeLinkIds.size) return;
        this.setFocusedMode(!this.focusedMode, true);
    }

    setFocusedMode(enabled, force = false) {
        const hasActiveRoute = this.route.activeLinkIds.size > 0;
        const nextValue = Boolean(enabled) && hasActiveRoute;
        if (!force && nextValue === this.focusedMode) {
            this.updateRouteUI();
            return;
        }
        this.focusedMode = nextValue;
        this.applyFocusMode();
        this.updateRouteUI();
    }

    applyFocusMode() {
        if (!this.map) return;
        const hasActiveRoute = this.route.activeLinkIds.size > 0;
        if (!this.focusedMode || !hasActiveRoute) {
            Object.values(this.polylines).forEach(polyGroup => {
                if (!this.map.hasLayer(polyGroup.core)) {
                    polyGroup.core.addTo(this.map);
                }
                if (!this.map.hasLayer(polyGroup.glow)) {
                    polyGroup.glow.addTo(this.map);
                }
            });
            if (this.state.showLiveMarkers) {
                this.updateLiveMarkers(this.lastLinks || []);
            }
            return;
        }

        const keepIds = this.route.activeLinkIds;
        Object.entries(this.polylines).forEach(([linkId, polyGroup]) => {
            const shouldKeep = keepIds.has(linkId);
            if (shouldKeep) {
                if (!this.map.hasLayer(polyGroup.core)) {
                    polyGroup.core.addTo(this.map);
                }
                if (!this.map.hasLayer(polyGroup.glow)) {
                    polyGroup.glow.addTo(this.map);
                }
                return;
            }
            if (this.map.hasLayer(polyGroup.core)) {
                this.map.removeLayer(polyGroup.core);
            }
            if (this.map.hasLayer(polyGroup.glow)) {
                this.map.removeLayer(polyGroup.glow);
            }
        });

        this.clearLiveMarkers();
    }

    async planRoute() {
        if (!this.route.startLinkId || !this.route.endLinkId) {
            this.route.planMessage = 'Select start and end links.';
            this.updateRouteUI();
            return;
        }

        try {
            const resp = await fetch(`${this.apiBase}/route/plan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    start_link_id: this.route.startLinkId,
                    end_link_id: this.route.endLinkId
                })
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.detail || 'Route planning failed.');
            }
            this.setPlannedRoute(data.link_ids, data.total_length_m);
            this.route.planMessage = null;
        } catch (e) {
            console.error("Route planning failed", e);
            this.setPlannedRoute([], null);
            this.route.planMessage = e.message || 'Route planning failed.';
        }

        this.updateRouteUI();
        this.refreshRouteStyles();
    }

    async activateRoute() {
        if (!this.route.plannedLinkIds.length) {
            this.route.planMessage = 'Plan a route before activating.';
            this.updateRouteUI();
            return;
        }

        try {
            const resp = await fetch(`${this.apiBase}/route/activate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    link_ids: this.route.plannedLinkIds,
                    start_link_id: this.route.startLinkId,
                    end_link_id: this.route.endLinkId,
                    total_length_m: this.route.plannedLengthM
                })
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.detail || 'Route activation failed.');
            }
            this.route.planMessage = null;
            if (data.route) {
                this.setActiveRoute(data.route);
            } else {
                this.updateRouteUI();
            }

            this.adminSelectionDirty = false;
            await this.fetchLiveLinks();
            this.renderAdminLinks();
            this.pollState();
        } catch (e) {
            console.error("Route activation failed", e);
            this.route.planMessage = e.message || 'Route activation failed.';
            this.updateRouteUI();
        }
    }

    startRoutePolling() {
        if (this.routePollInterval) return;
        this.routePollInterval = setInterval(() => this.pollRouteState(), this.routePollIntervalMs);
        this.pollRouteState();
    }

    stopRoutePolling() {
        if (!this.routePollInterval) return;
        clearInterval(this.routePollInterval);
        this.routePollInterval = null;
    }

    async pollRouteState() {
        if (this.isRoutePollInFlight || document.hidden) return;
        if (!this.route.activeLinkIds.size) return;
        this.isRoutePollInFlight = true;
        try {
            const response = await fetch(`${this.apiBase}/route/live`);
            const data = await response.json();
            if (!data.active) {
                this.setActiveRoute(null);
                return;
            }

            if (data.route && Array.isArray(data.route.link_ids)) {
                const nextIds = data.route.link_ids;
                const changed = nextIds.length !== this.route.activeLinkIds.size ||
                    nextIds.some(id => !this.route.activeLinkIds.has(id));
                if (changed) {
                    this.setActiveRoute(data.route);
                } else if (typeof data.route.total_length_m === 'number') {
                    this.route.activeLengthM = data.route.total_length_m;
                    this.updateRouteUI();
                }
            }

            if (Array.isArray(data.links)) {
                this.updateRouteLinks(data.links);
            }
        } catch (e) {
            console.error("Route poll error:", e);
        } finally {
            this.isRoutePollInFlight = false;
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

    async initAdminLinks(includeCoords = null) {
        const shouldIncludeCoords = includeCoords ?? !this.geometryLoaded;
        await Promise.all([this.fetchAdminLinks(shouldIncludeCoords), this.fetchLiveLinks()]);
        this.adminSelectionDirty = false;
        this.renderAdminLinks();
    }

    async fetchAdminLinks(includeCoords = false) {
        const listEl = document.getElementById('admin-live-list');
        try {
            const url = includeCoords ? `${this.apiBase}/admin/links?include_coords=1` : `${this.apiBase}/admin/links`;
            const resp = await fetch(url);
            const data = await resp.json();
            const links = data.links || [];
            this.adminLinks = links.slice().sort((a, b) => a.name.localeCompare(b.name));
            this.applyNetworkGeometry(links);
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

    applyNetworkGeometry(links) {
        if (!Array.isArray(links)) return;
        let hasCoords = false;

        links.forEach(link => {
            if (!link || !link.id) return;
            const meta = this.getLinkMeta(link);
            if (Array.isArray(link.coordinates) && link.coordinates.length > 1) {
                meta.coordinates = link.coordinates;
                const center = this.getCenterPoint(link.coordinates);
                if (center) meta.center = center;
                this.linkMeta.set(link.id, meta);
                this.createPolylineForLink(link.id, link.coordinates, meta.type || link.type);
                hasCoords = true;
            }
        });

        if (hasCoords) {
            this.geometryLoaded = true;
            if (this.focusedMode && this.route.activeLinkIds.size) {
                this.applyFocusMode();
            }
        }
    }

    createPolylineForLink(linkId, coordinates, type) {
        if (!this.map || this.polylines[linkId]) return;
        if (!Array.isArray(coordinates) || coordinates.length < 2) return;

        const isTransit = type === 'transit';
        const baseColor = isTransit ? '#a855f7' : '#334155';

        const glow = L.polyline(coordinates, {
            color: baseColor,
            weight: isTransit ? 8 : 12,
            opacity: 0.15,
            lineCap: 'round',
            className: 'glow-layer',
            interactive: false
        }).addTo(this.map);

        const core = L.polyline(coordinates, {
            color: '#444',
            weight: isTransit ? 3 : 4,
            opacity: 0.6,
            lineCap: 'round',
            dashArray: isTransit ? '5, 8' : null
        }).addTo(this.map);

        const polyGroup = { core, glow };
        core.bindPopup('', { closeButton: false, autoPan: false });
        core.on('popupopen', () => this.refreshPopup(linkId));
        core.on('click', () => this.handleLinkSelection(linkId));
        this.polylines[linkId] = polyGroup;
    }

    getCenterPoint(coordinates) {
        if (!Array.isArray(coordinates) || coordinates.length === 0) return null;
        const mid = coordinates[Math.floor(coordinates.length / 2)];
        if (!Array.isArray(mid) || mid.length < 2) return null;
        return mid;
    }

    getLinkMeta(link) {
        if (!link || !link.id) return {};
        const existing = this.linkMeta.get(link.id) || {};
        let changed = false;

        if (link.name && link.name !== existing.name) {
            existing.name = link.name;
            changed = true;
        }
        if (link.type && link.type !== existing.type) {
            existing.type = link.type;
            changed = true;
        }
        if (changed) {
            this.linkMeta.set(link.id, existing);
        }
        return existing;
    }

    getLinkName(link) {
        if (!link) return 'Unknown';
        if (link.name) return link.name;
        const meta = this.linkMeta.get(link.id);
        return (meta && meta.name) ? meta.name : link.id;
    }

    getLinkNameById(linkId) {
        if (!linkId) return 'Unknown';
        const meta = this.linkMeta.get(linkId);
        return (meta && meta.name) ? meta.name : linkId;
    }

    getFallbackLinkState(linkId) {
        if (!linkId) return null;
        const meta = this.linkMeta.get(linkId);
        if (!meta) return null;
        return {
            id: linkId,
            name: meta.name || linkId,
            type: meta.type || 'road',
            is_live: this.liveLinkIds.has(linkId),
            flow: 0,
            capacity: 0,
            ci: 0,
            price: 0
        };
    }

    getLinkType(link) {
        if (!link) return 'road';
        if (link.type) return link.type;
        const meta = this.linkMeta.get(link.id);
        return (meta && meta.type) ? meta.type : 'road';
    }

    getLinkCenter(link) {
        if (!link || !link.id) return null;
        const meta = this.linkMeta.get(link.id);
        if (meta && Array.isArray(meta.center)) return meta.center;
        if (Array.isArray(link.coordinates) && link.coordinates.length > 1) {
            const center = this.getCenterPoint(link.coordinates);
            if (center) {
                const updated = meta ? { ...meta } : {};
                updated.coordinates = link.coordinates;
                updated.center = center;
                this.linkMeta.set(link.id, updated);
                return center;
            }
        }
        return null;
    }

    getLinkStyle(link, type) {
        const isSimView = this.state.viewMode === 'simulator';
        const isLive = Boolean(link.is_live);
        const shouldHighlight = isSimView ? !isLive : isLive;
        const baseColor = type === 'transit' ? '#a855f7' : '#334155';

        if (!shouldHighlight) {
            return this.applyRouteStyleOverrides({
                color: baseColor,
                glowColor: baseColor,
                weight: type === 'transit' ? 3 : 4,
                opacity: 0.35,
                glowOpacity: 0.05
            }, link.id);
        }

        const ci = typeof link.ci === 'number' ? link.ci : 0;
        let color = '#334155';
        let glowColor = '#334155';

        if (ci > 0.4) { color = '#00f2ff'; glowColor = '#00f2ff'; }
        if (ci > 0.6) { color = '#ffcc00'; glowColor = '#ffcc00'; }
        if (ci > 0.8) { color = '#ff0055'; glowColor = '#ff0055'; }

        if (type === 'transit') {
            color = '#a855f7';
            glowColor = '#a855f7';
        }

        return this.applyRouteStyleOverrides({
            color,
            glowColor,
            weight: ci > 0.8 ? 6 : (type === 'transit' ? 3 : 5),
            opacity: ci > 0.1 ? 1.0 : 0.4,
            glowOpacity: ci > 0.1 ? 0.25 : 0.05
        }, link.id);
    }

    applyRouteStyleOverrides(style, linkId) {
        if (!linkId) return style;
        const isStart = linkId === this.route.startLinkId;
        const isEnd = linkId === this.route.endLinkId;
        const isPlanned = this.route.plannedLinkSet.has(linkId);
        const isActive = this.route.activeLinkIds.has(linkId);

        if (isPlanned) {
            style.glowColor = '#38bdf8';
            style.glowOpacity = Math.max(style.glowOpacity, 0.35);
            style.weight = Math.max(style.weight, 6);
        }

        if (isActive) {
            style.glowColor = '#22c55e';
            style.glowOpacity = Math.max(style.glowOpacity, 0.45);
            style.weight = Math.max(style.weight, 6);
        }

        if (isStart) {
            style.color = '#22c55e';
            style.glowColor = '#22c55e';
            style.opacity = 1.0;
            style.glowOpacity = Math.max(style.glowOpacity, 0.6);
            style.weight = Math.max(style.weight, 7);
        }

        if (isEnd) {
            style.color = '#f43f5e';
            style.glowColor = '#f43f5e';
            style.opacity = 1.0;
            style.glowOpacity = Math.max(style.glowOpacity, 0.6);
            style.weight = Math.max(style.weight, 7);
        }

        return style;
    }

    refreshPopup(linkId) {
        const polyGroup = this.polylines[linkId];
        if (!polyGroup) return;
        const state = this.linkStateCache.get(linkId);
        if (!state) return;
        const content = this.buildPopupContent(state);
        if (!polyGroup.core.getPopup()) {
            polyGroup.core.bindPopup(content, { closeButton: false, autoPan: false });
            return;
        }
        polyGroup.core.setPopupContent(content);
    }

    buildPopupContent(state) {
        const content = document.createElement('div');
        content.style.fontFamily = "'Courier New'";
        content.style.fontSize = '12px';

        const nameEl = document.createElement('strong');
        nameEl.textContent = state.name || state.id;
        content.appendChild(nameEl);
        content.appendChild(document.createElement('br'));

        const badge = document.createElement('span');
        badge.textContent = state.is_live ? '[LIVE FEED]' : '[SIMULATED]';
        badge.style.color = state.is_live ? '#00ff00' : '#888';
        if (state.is_live) {
            badge.style.fontWeight = 'bold';
        }
        content.appendChild(badge);
        content.appendChild(document.createElement('br'));

        const flowLine = document.createElement('div');
        flowLine.append('Flow: ', String(state.flow), ' / ', String(state.capacity));
        content.appendChild(flowLine);

        const ciLine = document.createElement('div');
        const ciValue = Number.isFinite(state.ci) ? state.ci.toFixed(2) : String(state.ci);
        ciLine.append('CI: ', ciValue);
        content.appendChild(ciLine);

        const priceLine = document.createElement('div');
        const priceLabel = document.createElement('span');
        priceLabel.textContent = 'Price: ';
        const priceValue = document.createElement('b');
        priceValue.textContent = String(state.price);
        priceLine.append(priceLabel, priceValue, ' HUF');
        content.appendChild(priceLine);

        const updateLine = document.createElement('div');
        const sourceLabel = state.last_observation_source ? `Source: ${state.last_observation_source}` : 'Source: --';
        const ageLabel = this.formatAge(state.age_sec);
        updateLine.textContent = `${sourceLabel} -> Updated: ${ageLabel}`;
        content.appendChild(updateLine);

        return content;
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
        summaryEl.innerText = `${liveCount} live link${liveCount === 1 ? '' : 's'} selected${total ? ` - ${total} total` : ''}`;
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
        if (this.isPollRequestInFlight || document.hidden) return;
        const now = Date.now();
        const minInterval = this.route.activeLinkIds.size ? this.focusedPollIntervalMs : this.pollIntervalMs;
        if (now - this.lastFullPollAt < minInterval) return;
        this.lastFullPollAt = now;
        this.isPollRequestInFlight = true;
        const includeCoords = !this.geometryLoaded;
        const url = includeCoords ? `${this.apiBase}/live?include_coords=1` : `${this.apiBase}/live`;
        try {
            const response = await fetch(url);
            const data = await response.json();
            if (includeCoords) {
                this.applyNetworkGeometry(data.links);
            }

            // Global Updates
            const simTimeEl = document.getElementById('sim-time');
            if (simTimeEl) simTimeEl.innerText = data.sim_time;

            // Sync Controls if externall changed
            if (data.control) this.updateControlUI(data.control);

            // Links
            const links = Array.isArray(data.links) ? data.links : [];
            this.lastLinks = links;
            if (!this.focusedMode || !this.route.activeLinkIds.size) {
                this.updateMap(links);
            }

            // Stats Panels
            const now = Date.now();
            const refreshLists = (now - this.lastUiRefreshAt) >= this.uiRefreshMs;
            if (refreshLists) this.lastUiRefreshAt = now;
            this.updateStats(data, refreshLists);

        } catch (e) {
            console.error("Poll Error:", e);
        } finally {
            this.isPollRequestInFlight = false;
        }
    }

    applyLinkStyle(linkId, polyGroup, style) {
        const prevStyle = this.linkStyleCache.get(linkId);
        if (!prevStyle ||
            prevStyle.color !== style.color ||
            prevStyle.glowColor !== style.glowColor ||
            prevStyle.weight !== style.weight ||
            prevStyle.opacity !== style.opacity ||
            prevStyle.glowOpacity !== style.glowOpacity) {
            polyGroup.core.setStyle({
                color: style.color,
                weight: style.weight,
                opacity: style.opacity
            });

            polyGroup.glow.setStyle({
                color: style.glowColor,
                opacity: style.glowOpacity
            });
            this.linkStyleCache.set(linkId, style);
        }
    }

    updateLinkState(link) {
        if (!link || !link.id) return;
        const meta = this.getLinkMeta(link);
        const type = meta.type || link.type || 'road';
        const name = meta.name || link.name || link.id;

        let polyGroup = this.polylines[link.id];
        if (!polyGroup) {
            const coords = meta.coordinates || link.coordinates;
            if (coords && coords.length > 1) {
                this.createPolylineForLink(link.id, coords, type);
                polyGroup = this.polylines[link.id];
            }
        }

        if (!polyGroup) return;

        const style = this.getLinkStyle(link, type);
        this.applyLinkStyle(link.id, polyGroup, style);

        this.linkStateCache.set(link.id, {
            id: link.id,
            name: name,
            type: type,
            is_live: link.is_live,
            flow: link.flow,
            capacity: link.capacity,
            ci: link.ci,
            price: link.price,
            last_observation_source: link.last_observation_source,
            age_sec: link.age_sec
        });

        const popup = polyGroup.core.getPopup();
        if (popup && popup.isOpen && popup.isOpen()) {
            this.refreshPopup(link.id);
        }
    }

    updateMap(links, pruneMissing = true) {
        if (!Array.isArray(links)) return;
        const currentLinkIds = new Set();

        links.forEach(link => {
            if (!link || !link.id) return;
            currentLinkIds.add(link.id);
            this.updateLinkState(link);
        });

        if (pruneMissing) {
            this.updateLiveMarkers(links);
            Object.entries(this.polylines).forEach(([linkId, polyGroup]) => {
                if (currentLinkIds.has(linkId)) return;
                this.map.removeLayer(polyGroup.core);
                this.map.removeLayer(polyGroup.glow);
                delete this.polylines[linkId];
                this.linkStateCache.delete(linkId);
                this.linkStyleCache.delete(linkId);
            });
        }
    }

    updateRouteLinks(links) {
        if (!Array.isArray(links)) return;
        links.forEach(link => this.updateLinkState(link));
        this.updateLiveMarkers(links);
    }

    clearLiveMarkers() {
        Object.entries(this.liveMarkers).forEach(([, marker]) => {
            if (marker && this.map) this.map.removeLayer(marker);
        });
        this.liveMarkers = {};
    }

    updateLiveMarkers(links) {
        if (!this.state.showLiveMarkers) {
            this.clearLiveMarkers();
            return;
        }

        if (!Array.isArray(links)) return;
        const liveLinkIds = new Set();

        links.forEach(link => {
            if (!link.is_live) return;
            const latLng = this.getLinkCenter(link);
            if (!Array.isArray(latLng) || latLng.length < 2) return;

            liveLinkIds.add(link.id);
            const ageSec = link.age_sec;
            const isStale = typeof ageSec === 'number' ? ageSec > this.liveStaleThresholdSec : true;
            const markerClass = isStale ? 'live-marker live-marker-stale' : 'live-marker live-marker-fresh';
            const color = isStale ? '#64748b' : '#22c55e';
            const labelName = this.getLinkName(link);

            let marker = this.liveMarkers[link.id];
            if (!marker) {
                marker = L.circleMarker(latLng, {
                    radius: 5,
                    color: color,
                    weight: 2,
                    fillColor: color,
                    fillOpacity: 0.9,
                    className: markerClass
                }).addTo(this.map);
                marker.bindTooltip(`${labelName} -> ${isStale ? 'stale' : 'live'}`, {
                    direction: 'top',
                    offset: [0, -6],
                    opacity: 0.8
                });
                this.liveMarkers[link.id] = marker;
            } else {
                marker.setLatLng(latLng);
                marker.setStyle({
                    color: color,
                    fillColor: color,
                    className: markerClass
                });
                marker.setTooltipContent(`${labelName} -> ${isStale ? 'stale' : 'live'}`);
            }
        });

        Object.entries(this.liveMarkers).forEach(([linkId, marker]) => {
            if (liveLinkIds.has(linkId)) return;
            this.map.removeLayer(marker);
            delete this.liveMarkers[linkId];
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

    updateStats(data, refreshLists = true) {
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

        if (!refreshLists) return;

        // Live Feed
        this.updateLiveFeed(data.links);
        this.syncAdminSelectionFromLive(data.links);
        this.updateLinkTelemetry(data.links);
    }

    updateLiveFeed(links) {
        if (!Array.isArray(links)) return;
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
            name.textContent = this.getLinkName(link);
            item.appendChild(name);

            const meta = document.createElement('div');
            meta.className = 'live-feed-meta';
            meta.textContent = `${this.formatAge(ageSec)} -> ${link.last_observation_source || 'unknown'}`;
            item.appendChild(meta);

            listEl.appendChild(item);
        });

        summaryEl.innerText = `${liveLinks.length} live link${liveLinks.length === 1 ? '' : 's'} -> ${staleCount} stale (> ${this.liveStaleThresholdSec}s)`;
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
            nameCell.textContent = this.getLinkName(link);

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
    const app = new App();
    window.app = app;
    app.bootstrap().catch((err) => {
        console.error("App bootstrap failed", err);
    });
};
