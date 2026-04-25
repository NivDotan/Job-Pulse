/**
 * Scraper Dashboard - JavaScript
 * Handles navigation, data fetching, chart rendering, and real-time updates
 * Version: 5.0
 */

console.log('=== Dashboard JS loaded - Version 7.0 ===');

// Chart instances
let pipelineChart = null;
let companiesBarChart = null;
let analyticsTrendChart = null;

const chartColors = {
    gold:    '#c9a847',
    green:   '#34d058',
    blue:    '#6b9df2',
    purple:  '#8b7cc8',
    orange:  '#e07a50',
    red:     '#e05f5f',
    muted:   '#524e5d',
    cyan:    '#c9a847',   // legacy alias
    magenta: '#c9a847',   // legacy alias
    yellow:  '#c9a847',   // legacy alias
};

const atsColors = {
    'green':        '#34d058',
    'lever':        '#6b9df2',
    'smart':        '#8b7cc8',
    'comeet':       '#c9a847',
    'bamboohr':     '#e07a50',
    'workday':      '#5ba4cf',
    'ashby':        '#c9a847',
    'icims':        '#e05f5f',
    'jobvite':      '#9b7cc8',
    'other':        '#524e5d',
};

let currentEmailDate = new Date().toISOString().split('T')[0];

// Page title mapping
const pageTitles = {
    'dashboard': 'Market Pulse',
    'today-jobs': 'Live Jobs',
    'email-history': 'Job History',
    'run-history': 'System Status',
    'analytics': 'AI Insights',
};

/* ============================================
   Navigation
   ============================================ */

function navigateTo(page) {
    // Hide all pages
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));

    // Show target page
    const target = document.getElementById('page-' + page);
    if (target) target.classList.add('active');

    // Update sidebar active state
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });

    // Update page title
    const titleEl = document.getElementById('page-title');
    if (titleEl) titleEl.textContent = pageTitles[page] || 'Dashboard';

    // Lazy-load Today Jobs data the first time its page is opened
    if (page === 'today-jobs' && !todayJobsLoaded) {
        loadTodayJobs();
    }
    if (page === 'analytics') {
        loadAnalyticsData();
    }

    // Close mobile sidebar
    closeMobileSidebar();

    // Resize charts if switching to a page/tab that contains them
    requestAnimationFrame(() => {
        resizeVisibleCharts();
    });
}

function switchTab(page, tab) {
    const pageEl = document.getElementById('page-' + page);
    if (!pageEl) return;

    // Hide all tab panels within this page
    pageEl.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    // Show the target tab panel
    const panel = document.getElementById('tab-' + tab);
    if (panel) panel.classList.add('active');

    // Update tab bar active state within this page
    pageEl.querySelectorAll('.tab-bar .tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tab);
    });

    // Charts rendered in hidden containers have zero size; trigger resize
    requestAnimationFrame(() => {
        resizeVisibleCharts();
    });
}

function resizeVisibleCharts() {
    if (pipelineChart) pipelineChart.resize();
    if (companiesBarChart) companiesBarChart.resize();
    if (analyticsTrendChart) analyticsTrendChart.resize();
}

/* ============================================
   Sidebar collapse / mobile
   ============================================ */

function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.getElementById('sidebar-toggle');
    const mobileBtn = document.getElementById('mobile-menu-btn');

    if (toggle) {
        toggle.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
        });
    }

    if (mobileBtn) {
        mobileBtn.addEventListener('click', () => {
            sidebar.classList.toggle('mobile-open');
            toggleOverlay(true);
        });
    }

    // Create mobile overlay
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    overlay.id = 'sidebar-overlay';
    overlay.addEventListener('click', closeMobileSidebar);
    document.body.appendChild(overlay);
}

function closeMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.remove('mobile-open');
    toggleOverlay(false);
}

function toggleOverlay(show) {
    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.classList.toggle('active', show);
}

/* ============================================
   Initialize
   ============================================ */

async function initDashboard() {
    console.log('initDashboard called!');
    try {
        initSidebar();
        initDatePicker();
        const refreshBtn = document.getElementById('today-jobs-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async () => {
                todayJobsLoaded = false;
                await loadTodayJobs();
            });
        }
        await fetchAndUpdateDashboard();
        setInterval(fetchAndUpdateDashboard, 500000);
        await loadEmailHistoryStats();
        initAnalytics();
        await loadAnalyticsData();
    } catch (error) {
        console.error('Failed to initialize dashboard:', error);
    }
}


/* ============================================
   Date Picker
   ============================================ */

function initDatePicker() {
    const datePicker = document.getElementById('email-date-picker');
    const todayBtn = document.getElementById('today-btn');

    if (datePicker) {
        datePicker.value = currentEmailDate;
        datePicker.addEventListener('change', async (e) => {
            currentEmailDate = e.target.value;
            await loadEmailedJobsByDate(currentEmailDate);
        });
    }

    if (todayBtn) {
        todayBtn.addEventListener('click', async () => {
            currentEmailDate = new Date().toISOString().split('T')[0];
            if (datePicker) datePicker.value = currentEmailDate;
            await loadEmailedJobsByDate(currentEmailDate);
        });
    }
}

/* ============================================
   Data fetching
   ============================================ */

async function loadEmailedJobsByDate(date) {
    try {
        const data = await fetchAPI(`/api/emailed-jobs/by-date/${date}`);
        updateEmailedJobs(data);
    } catch (error) {
        console.error('Error loading emailed jobs by date:', error);
        updateEmailedJobs({});
    }
}

async function loadEmailHistoryStats() {
    try {
        const data = await fetchAPI('/api/emailed-jobs/history');
        updateEmailHistoryStats(data);
        updatePipelineChart(data);
    } catch (error) {
        console.error('Error loading email history stats:', error);
    }
}

function updateEmailHistoryStats(data) {
    const container = document.getElementById('history-dates-grid');
    if (!container) return;

    if (!data || !data.dates || data.dates.length === 0) {
        container.innerHTML = '<p class="empty-text">No email history available</p>';
        return;
    }

    const statsHtml = data.dates.slice(0, 14).map(date => {
        const stats = data.stats[date] || { total: 0, filtered: 0, unfiltered: 0 };
        const isToday = date === new Date().toISOString().split('T')[0];
        const isSelected = date === currentEmailDate;

        return `
            <div class="history-date-card ${isToday ? 'today' : ''} ${isSelected ? 'selected' : ''}"
                 onclick="selectHistoryDate('${date}', this)">
                <span class="date-label">${formatDateShort(date)}</span>
                <span class="date-total">${stats.total} jobs</span>
                <div class="date-breakdown">
                    <span class="filtered-badge">${stats.filtered} ✅</span>
                    <span class="unfiltered-badge">${stats.unfiltered} 📋</span>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = statsHtml;
}

async function selectHistoryDate(date, el) {
    currentEmailDate = date;

    const datePicker = document.getElementById('email-date-picker');
    if (datePicker) datePicker.value = date;

    document.querySelectorAll('.history-date-card').forEach(card => {
        card.classList.remove('selected');
    });
    if (el) el.classList.add('selected');

    await loadEmailedJobsByDate(date);
}

function formatDateShort(dateStr) {
    const date = new Date(dateStr);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (dateStr === today.toISOString().split('T')[0]) {
        return 'Today';
    } else if (dateStr === yesterday.toISOString().split('T')[0]) {
        return 'Yesterday';
    }
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

async function fetchAPI(endpoint) {
    const url = window.location.origin + endpoint;
    console.log('Fetching:', url);
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`${endpoint} failed: ${response.status}`);
    }
    return response.json();
}

/* ============================================
   Today Jobs
   ============================================ */

let todayJobsLoaded = false;

async function loadTodayJobs() {
    try {
        const data = await fetchAPI('/api/jobs/today');
        updateTodayJobsTable(data.jobs || []);
        todayJobsLoaded = true;
    } catch (error) {
        console.error('Error loading today jobs:', error);
        updateTodayJobsTable([]);
    }
}

async function loadJobDetails(link) {
    try {
        const data = await fetchAPI('/api/jobs/details?link=' + encodeURIComponent(link));
        updateTodayJobDetails(link, data);
    } catch (error) {
        console.error('Error loading job details:', error);
        updateTodayJobDetails(link, { has_details: false, error: error.message });
    }
}

function aiRatingBadge(suitable) {
    if (suitable === 'True') return '<span class="ai-pill ai-pill-junior">Junior ✓</span>';
    if (suitable === 'False') return '<span class="ai-pill ai-pill-senior">Senior</span>';
    if (suitable === 'Unclear') return '<span class="ai-pill ai-pill-unclear">Unclear</span>';
    return '<span class="ai-pill ai-pill-none">—</span>';
}

function updateTodayJobsTable(jobs) {
    const tbody = document.getElementById('today-jobs-body');
    if (!tbody) return;

    if (!jobs || jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading-row">No jobs found for today.</td></tr>';
        const title = document.getElementById('today-job-title');
        const meta = document.getElementById('today-job-meta');
        const desc = document.getElementById('today-job-desc');
        const reqs = document.getElementById('today-job-reqs');
        const msg = document.getElementById('today-job-message');
        if (title) title.textContent = 'No jobs available';
        if (meta) meta.textContent = '';
        if (desc) desc.innerHTML = '<p class="placeholder-text">When new jobs are scraped today, they will appear here.</p>';
        if (reqs) reqs.innerHTML = '<li class="placeholder-text">Requirements will appear here if available.</li>';
        if (msg) { msg.style.display = 'none'; msg.textContent = ''; }
        return;
    }

    tbody.innerHTML = jobs.map(job => {
        const createdAt = job.created_at ? new Date(job.created_at) : null;
        const timeStr = createdAt ? createdAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const safeLink = escapeHtml(job.link || '');
        const aiClass = job.suitable_for_junior === 'True' ? ' row-junior' :
                        job.suitable_for_junior === 'False' ? ' row-senior' : '';
        return `
            <tr class="today-job-row${aiClass}" data-link="${safeLink}" onclick="onTodayJobClick('${encodeURIComponent(job.link || '')}')">
                <td>${timeStr}</td>
                <td>${escapeHtml(job.company || '')}</td>
                <td>${escapeHtml(job.job_name || '')}</td>
                <td>${escapeHtml(job.city || '')}</td>
                <td>${aiRatingBadge(job.suitable_for_junior)}</td>
                <td>${job.link ? `<a href="${safeLink}" target="_blank" class="job-link">Open →</a>` : ''}</td>
            </tr>
        `;
    }).join('');
}

async function onTodayJobClick(encodedLink) {
    const link = decodeURIComponent(encodedLink || '');
    if (!link) return;

    // Highlight selected row
    document.querySelectorAll('.today-job-row').forEach(row => {
        row.classList.toggle('selected', decodeURIComponent(row.dataset.link || row.getAttribute('data-link')) === link);
    });

    await loadJobDetails(link);
}

function updateTodayJobDetails(link, data) {
    const titleEl = document.getElementById('today-job-title');
    const metaEl = document.getElementById('today-job-meta');
    const descEl = document.getElementById('today-job-desc');
    const reqsEl = document.getElementById('today-job-reqs');
    const msgEl = document.getElementById('today-job-message');

    if (!titleEl || !metaEl || !descEl || !reqsEl || !msgEl) return;

    // Clear previous message
    msgEl.style.display = 'none';
    msgEl.textContent = '';

    if (!data || data.has_details === false) {
        titleEl.textContent = 'No details available yet';
        metaEl.textContent = link || '';
        descEl.innerHTML = '<p class="placeholder-text">No description/requirements found yet for this job. The LLM may not have processed it.</p>';
        reqsEl.innerHTML = '<li class="placeholder-text">Requirements will appear here once processed.</li>';

        if (data && data.error) {
            msgEl.className = 'form-message error';
            msgEl.textContent = 'Error loading details: ' + data.error;
            msgEl.style.display = 'block';
        }
        return;
    }

    titleEl.textContent = data.job_name || 'Job details';
    const company = data.company || '';
    const city = data.city || '';
    const parts = [];
    if (company) parts.push(company);
    if (city) parts.push(city);
    metaEl.textContent = parts.join(' • ');

    // Description
    const descText = data.desc || '';
    if (descText.trim().length === 0) {
        descEl.innerHTML = '<p class="placeholder-text">No description stored for this job.</p>';
    } else {
        const paragraphs = descText.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
        descEl.innerHTML = paragraphs.map(p => `<p>${escapeHtml(p)}</p>`).join('');
    }

    // Requirements
    const reqs = data.reqs;
    if (!reqs || (Array.isArray(reqs) && reqs.length === 0) || (typeof reqs === 'string' && reqs.trim().length === 0)) {
        reqsEl.innerHTML = '<li class="placeholder-text">No requirements stored for this job.</li>';
    } else if (Array.isArray(reqs)) {
        reqsEl.innerHTML = reqs.map(r => `<li>${escapeHtml(String(r))}</li>`).join('');
    } else if (typeof reqs === 'string') {
        let lines = [];
        const trimmed = reqs.trim();

        // Try to parse JSON list, e.g. ["item1","item2",...]
        if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
            try {
                const parsed = JSON.parse(trimmed);
                if (Array.isArray(parsed)) {
                    lines = parsed.map(r => String(r).trim()).filter(Boolean);
                }
            } catch (e) {
                // fall back to simple splitting below
            }
        }

        if (lines.length === 0) {
            lines = reqs.split(/\n|;/).map(r => r.trim()).filter(Boolean);
        }

        reqsEl.innerHTML = lines.map(r => `<li>${escapeHtml(r)}</li>`).join('');
    } else {
        reqsEl.innerHTML = '<li class="placeholder-text">Requirements format not recognized.</li>';
    }

    // Optional junior badge
    if (Object.prototype.hasOwnProperty.call(data, 'suitable_for_junior')) {
        const val = data.suitable_for_junior;
        const badgeText = val === true || val === 'True' ? 'Junior-friendly' :
            val === false || val === 'False' ? 'Not suitable for juniors' : null;
        if (badgeText) {
            msgEl.className = 'form-message ' + ((val === true || val === 'True') ? 'success' : 'error');
            msgEl.textContent = badgeText;
            msgEl.style.display = 'block';
        }
    }
}

async function fetchAndUpdateDashboard() {
    console.log('fetchAndUpdateDashboard called');

    try {
        const [kpis, coverage, filter, companies, alerts, history, emailedJobs] = await Promise.all([
            fetchAPI('/api/kpis').catch(e => { console.error('KPIs error:', e); return {}; }),
            fetchAPI('/api/coverage').catch(e => { console.error('Coverage error:', e); return {}; }),
            fetchAPI('/api/filter').catch(e => { console.error('Filter error:', e); return {}; }),
            fetchAPI('/api/companies').catch(e => { console.error('Companies error:', e); return []; }),
            fetchAPI('/api/alerts').catch(e => { console.error('Alerts error:', e); return []; }),
            fetchAPI('/api/run-history').catch(e => { console.error('History error:', e); return []; }),
            fetchAPI('/api/emailed-jobs').catch(e => { console.error('Emailed jobs error:', e); return {}; }),
        ]);

        updateKPIs(kpis || {});
        updateCycleStatus(kpis?.cycle_state || 'idle');
        updateCompanyCoverage(coverage || {});
        updateFilterResults(filter || {});
        updateRunHistory(history || []);
        updateCompaniesBarChart(companies || []);
        updateLocations(filter?.locations || {});
        updateAlerts(alerts || []);
        updateATPills(coverage?.ats_breakdown || {});
        updateEmailedJobs(emailedJobs || {});

        // Snapshot strip
        updateSnapshotCards(kpis || {}, coverage || {}, emailedJobs || {});

        // Featured cards
        updatePicksFeed(emailedJobs || {});
        updateRecruitersList(companies || []);

        // Pipeline funnel — today's numbers
        const funnelRaw = document.getElementById('funnel-raw');
        const funnelFiltered = document.getElementById('funnel-filtered');
        if (funnelRaw) funnelRaw.textContent = formatNumber(kpis?.jobs_found_today || 0);
        if (funnelFiltered) funnelFiltered.textContent = formatNumber(kpis?.jobs_passed_filter || 0);

        document.getElementById('last-updated-time').textContent = new Date().toLocaleString();
    } catch (error) {
        console.error('Error fetching dashboard data:', error);
        updateAlerts([{ type: 'danger', message: `Failed to fetch data: ${error.message}` }]);
        updateCycleStatus('failed');
    }
}

/* ============================================
   UI Update Functions
   ============================================ */

function updateKPIs(kpis) {
    console.log('Updating KPIs:', kpis);
    document.getElementById('kpi-last-run').textContent = kpis?.last_run_time || 'N/A';
    document.getElementById('kpi-duration').textContent = kpis?.run_duration || 'N/A';

    const processed = kpis?.companies_processed || 0;
    const withResults = kpis?.companies_with_results || 0;
    const errorCount = kpis?.error_count || 0;
    document.getElementById('kpi-companies').textContent = `${processed} / ${withResults}`;

    const errorsEl = document.getElementById('kpi-errors');
    if (errorsEl) errorsEl.textContent = errorCount;

    document.getElementById('kpi-jobs-raw').textContent = formatNumber(kpis?.jobs_found_today);
    document.getElementById('kpi-jobs-filtered').textContent = formatNumber(kpis?.jobs_passed_filter);
    document.getElementById('kpi-success-rate').textContent = `${kpis?.success_rate || 0}%`;

    // Color the success rate card based on value
    const srCard = document.getElementById('kpi-success-rate')?.closest('.kpi-card');
    if (srCard) {
        srCard.classList.remove('highlight-success', 'highlight-danger');
        if ((kpis?.success_rate || 0) >= 80) {
            srCard.classList.add('highlight-success');
        } else {
            srCard.classList.add('highlight-danger');
        }
    }
}

function updateCycleStatus(state) {
    const badge = document.getElementById('cycle-status');
    if (!badge) return;
    const statusText = badge.querySelector('.status-text');
    badge.className = `status-badge ${state}`;
    if (statusText) statusText.textContent = state.charAt(0).toUpperCase() + state.slice(1);
}

function updateCompanyCoverage(coverage) {
    document.getElementById('stat-total-companies').textContent = formatNumber(coverage.total_companies);
    document.getElementById('stat-with-listings').textContent = formatNumber(coverage.companies_with_listings);
    document.getElementById('stat-failing').textContent = formatNumber(coverage.companies_failing);
}

function updateFilterResults(results) {
    document.getElementById('filter-israel').textContent = formatNumber(results.israel_jobs);
    document.getElementById('filter-non-israel').textContent = formatNumber(results.non_israel_jobs);
    document.getElementById('filter-raw').textContent = formatNumber(results.raw_count);
    document.getElementById('filter-deduped').textContent = formatNumber(results.deduped_count);
}

let runHistoryData = [];

function updateRunHistory(history) {
    const tbody = document.getElementById('history-table-body');
    runHistoryData = history || [];

    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="loading-row">No run history available</td></tr>';
        return;
    }

    tbody.innerHTML = history.map((run, idx) => `
        <tr class="history-row clickable" onclick="toggleRunDetail(${idx})">
            <td>${escapeHtml(run.log_file)}</td>
            <td>${run.start_time}</td>
            <td>${run.end_time}</td>
            <td>${run.duration}</td>
            <td>${run.companies_scanned}/${run.total_companies}</td>
            <td>${formatNumber(run.jobs_found)}</td>
            <td>${formatNumber(run.jobs_filtered)}</td>
            <td>${run.errors}</td>
            <td><span class="status-pill ${run.status}">${run.status}</span></td>
        </tr>
        <tr class="detail-row" id="detail-row-${idx}" style="display:none;">
            <td colspan="9">
                <div class="run-detail">${buildRunDetail(run)}</div>
            </td>
        </tr>
    `).join('');
}

function toggleRunDetail(idx) {
    const row = document.getElementById('detail-row-' + idx);
    if (!row) return;
    const isOpen = row.style.display !== 'none';
    document.querySelectorAll('.detail-row').forEach(r => r.style.display = 'none');
    document.querySelectorAll('.history-row').forEach(r => r.classList.remove('expanded'));
    if (!isOpen) {
        row.style.display = 'table-row';
        row.previousElementSibling?.classList.add('expanded');
    }
}

function buildRunDetail(run) {
    let html = '<div class="detail-grid">';

    html += `<div class="detail-item"><span class="detail-label">Log File</span><span class="detail-value">${escapeHtml(run.log_file)}</span></div>`;
    html += `<div class="detail-item"><span class="detail-label">Companies</span><span class="detail-value">${run.companies_scanned} processed / ${run.total_companies} total</span></div>`;
    html += `<div class="detail-item"><span class="detail-label">Jobs Found</span><span class="detail-value">${formatNumber(run.jobs_found)} raw, ${formatNumber(run.jobs_filtered)} filtered</span></div>`;
    html += `<div class="detail-item"><span class="detail-label">Errors</span><span class="detail-value ${run.errors > 0 ? 'text-danger' : ''}">${run.errors}</span></div>`;

    if (run.error_summary && run.error_summary.length > 0) {
        html += '<div class="detail-errors"><span class="detail-label">Error Details</span><ul>';
        run.error_summary.slice(0, 10).forEach(err => {
            html += `<li>${escapeHtml(String(err).substring(0, 150))}</li>`;
        });
        html += '</ul></div>';
    }

    if (run.top_locations && Object.keys(run.top_locations).length > 0) {
        const locs = Object.entries(run.top_locations).sort((a, b) => b[1] - a[1]).slice(0, 8);
        html += '<div class="detail-locations"><span class="detail-label">Top Locations</span><div class="detail-loc-list">';
        locs.forEach(([loc, count]) => {
            html += `<span class="detail-loc-tag">${escapeHtml(loc)}: ${count}</span>`;
        });
        html += '</div></div>';
    }

    html += '</div>';
    return html;
}

function updateCompaniesBarChart(companies) {
    const canvas = document.getElementById('companies-bar-chart');
    if (!canvas || !companies || companies.length === 0) return;

    const top10 = companies.slice(0, 10);
    const labels = top10.map(c => c[0]);
    const data = top10.map(c => c[1]);
    const colors = labels.map((_, i) => `hsla(${44 - i * 4}, ${68 - i * 3}%, ${58 - i * 2}%, 0.85)`);

    if (companiesBarChart) {
        companiesBarChart.data.labels = labels;
        companiesBarChart.data.datasets[0].data = data;
        companiesBarChart.data.datasets[0].backgroundColor = colors;
        companiesBarChart.update();
        return;
    }

    companiesBarChart = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Jobs Today',
                data,
                backgroundColor: colors,
                borderRadius: 4,
                borderSkipped: false,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#161616',
                    titleColor: '#e8eaed',
                    bodyColor: '#9ca3af',
                    borderColor: '#262626',
                    borderWidth: 1,
                    padding: 10,
                    titleFont: { family: "'Outfit', sans-serif", size: 13, weight: '600' },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    grid: { color: 'rgba(38,38,38,0.8)', drawBorder: false },
                    ticks: { color: '#6b7280', font: { family: "'JetBrains Mono', monospace", size: 11 } }
                },
                y: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { family: "'Outfit', sans-serif", size: 12 } }
                }
            }
        }
    });
}

function updateATPills(atsData) {
    const container = document.getElementById('ats-pills');
    if (!container || !atsData || Object.keys(atsData).length === 0) return;

    container.innerHTML = Object.entries(atsData)
        .sort((a, b) => b[1] - a[1])
        .map(([ats, count]) => {
            const color = atsColors[ats.toLowerCase()] || atsColors.other;
            return `<span class="ats-pill" style="--ats-color: ${color}">${ats} <strong>${count}</strong></span>`;
        }).join('');
}

function updateLocations(locations) {
    const container = document.getElementById('locations-list');

    if (!locations || Object.keys(locations).length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📍</div><p>No location data available</p></div>';
        return;
    }

    const sortedLocations = Object.entries(locations)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10);

    container.innerHTML = sortedLocations.map(([location, count]) => `
        <div class="location-item">
            <span class="location-name">${location}</span>
            <span class="location-count">${count}</span>
        </div>
    `).join('');
}

function updateAlerts(alerts) {
    const container = document.getElementById('alerts-container');

    if (!alerts || alerts.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = alerts.map(alert => `
        <div class="alert ${alert.type}">
            <span class="alert-icon">${alert.type === 'danger' ? '🚨' : '⚠️'}</span>
            <span class="alert-message">${alert.message}</span>
        </div>
    `).join('');
}

/* ============================================
   Snapshot Cards
   ============================================ */

function updateSnapshotCards(kpis, coverage, emailedJobs) {
    const snapCompanies = document.getElementById('snap-companies');
    const snapJobs = document.getElementById('snap-jobs-today');
    const snapPicks = document.getElementById('snap-junior-picks');
    const snapRate = document.getElementById('snap-success-rate');
    const snapRateCard = document.getElementById('snap-rate-card');

    if (snapCompanies) snapCompanies.textContent = formatNumber(coverage.total_companies);
    if (snapJobs) snapJobs.textContent = formatNumber(kpis.jobs_found_today);
    if (snapPicks) snapPicks.textContent = formatNumber(emailedJobs.filtered_count || 0);

    const rate = kpis.success_rate || 0;
    if (snapRate) snapRate.textContent = `${rate}%`;
    if (snapRateCard) {
        snapRateCard.classList.remove('snap-good', 'snap-bad');
        snapRateCard.classList.add(rate >= 80 ? 'snap-good' : 'snap-bad');
    }
}

/* ============================================
   Junior Picks Feed
   ============================================ */

function updatePicksFeed(emailedJobs) {
    const container = document.getElementById('picks-feed');
    if (!container) return;

    const jobs = emailedJobs.filtered_jobs || [];

    if (jobs.length === 0) {
        container.innerHTML = '<div class="picks-empty"><span>No junior picks sent today yet</span></div>';
        return;
    }

    container.innerHTML = jobs.slice(0, 8).map(job => {
        const timeStr = job.sent_at ? new Date(job.sent_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const title = job.title || '';
        const company = job.company ? job.company.replace(/([a-z])([A-Z])/g, '$1 $2') : '';
        const safeLink = escapeHtml(job.link || '');
        return `
            <div class="pick-item">
                <span class="pick-dot"></span>
                <div class="pick-body">
                    <div class="pick-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
                    <div class="pick-meta">
                        <span class="pick-company">${escapeHtml(company)}</span>
                        <span class="pick-sep">·</span>
                        <span>${escapeHtml(job.city || '')}</span>
                        <span class="pick-time">${timeStr}</span>
                    </div>
                </div>
                ${safeLink ? `<a href="${safeLink}" target="_blank" class="pick-link-btn" title="Open job">↗</a>` : ''}
            </div>
        `;
    }).join('');
}

/* ============================================
   Top Recruiters List
   ============================================ */

function updateRecruitersList(companies) {
    const container = document.getElementById('recruiters-list');
    if (!container || !companies || companies.length === 0) return;

    const top = companies.slice(0, 8);
    const maxCount = top[0]?.[1] || 1;

    container.innerHTML = top.map((company, index) => {
        const name = company[0] || '';
        const count = company[1] || 0;
        const pct = Math.round((count / maxCount) * 100);
        const barColor = index === 0 ? 'var(--accent-cyan)' :
                         index === 1 ? 'var(--accent-green)' :
                         index <= 3 ? 'var(--accent-blue)' : 'var(--accent-purple)';
        return `
            <div class="recruiter-item">
                <span class="recruiter-rank">${index + 1}</span>
                <div class="recruiter-info">
                    <div class="recruiter-name">${escapeHtml(name)}</div>
                    <div class="recruiter-bar-track">
                        <div class="recruiter-bar-fill" style="width: ${pct}%; background: ${barColor};"></div>
                    </div>
                </div>
                <span class="recruiter-count">${formatNumber(count)}</span>
            </div>
        `;
    }).join('');
}

/* ============================================
   Charts
   ============================================ */

function updatePipelineChart(historyData) {
    const canvas = document.getElementById('pipeline-chart');
    if (!canvas) return;

    if (!historyData || !historyData.dates || historyData.dates.length === 0) return;

    // dates array is newest-first; reverse for chronological display, take last 14
    const dates = [...historyData.dates].reverse().slice(-14);
    const labels = dates.map(d => formatDateShort(d));
    const juniorData = dates.map(d => (historyData.stats[d] || {}).filtered || 0);
    const otherData = dates.map(d => (historyData.stats[d] || {}).unfiltered || 0);

    if (pipelineChart) {
        pipelineChart.data.labels = labels;
        pipelineChart.data.datasets[0].data = juniorData;
        pipelineChart.data.datasets[1].data = otherData;
        pipelineChart.update();
        return;
    }

    pipelineChart = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Junior-Suitable',
                    data: juniorData,
                    backgroundColor: 'rgba(52, 208, 88, 0.78)',
                    borderRadius: 4,
                    borderSkipped: false,
                },
                {
                    label: 'Other Jobs',
                    data: otherData,
                    backgroundColor: 'rgba(201, 168, 71, 0.35)',
                    borderRadius: 4,
                    borderSkipped: false,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#9ca3af',
                        font: { family: "'Outfit', sans-serif", size: 12 },
                        usePointStyle: true,
                        pointStyle: 'circle',
                    }
                },
                tooltip: {
                    backgroundColor: '#161616',
                    titleColor: '#e8eaed',
                    bodyColor: '#9ca3af',
                    borderColor: '#262626',
                    borderWidth: 1,
                    padding: 12,
                    titleFont: { family: "'Outfit', sans-serif", size: 14, weight: '600' },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
                }
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { color: 'rgba(38,38,38,0.8)', drawBorder: false },
                    ticks: { color: '#6b7280', font: { family: "'Outfit', sans-serif", size: 11 } }
                },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    grid: { color: 'rgba(38,38,38,0.8)', drawBorder: false },
                    ticks: { color: '#6b7280', font: { family: "'JetBrains Mono', monospace", size: 11 } }
                }
            }
        }
    });
}

/* ============================================
   Emailed Jobs
   ============================================ */

function updateEmailedJobs(data) {
    console.log('Updating emailed jobs:', data);

    const filteredBody = document.getElementById('filtered-jobs-body');
    const unfilteredBody = document.getElementById('unfiltered-jobs-body');
    const filteredCount = document.getElementById('filtered-jobs-count');
    const unfilteredCount = document.getElementById('unfiltered-jobs-count');
    const filteredBadge = document.getElementById('filtered-jobs-count-badge');
    const unfilteredBadge = document.getElementById('unfiltered-jobs-count-badge');
    const emailSummary = document.getElementById('email-summary');

    const displayDate = data.date || currentEmailDate;
    const isToday = displayDate === new Date().toISOString().split('T')[0];
    const dateLabel = isToday ? 'Today' : formatDateShort(displayDate);

    if (emailSummary) {
        emailSummary.textContent = `- ${dateLabel} (${data.total_sent || 0} total)`;
    }

    const fc = data.filtered_count || 0;
    const uc = data.unfiltered_count || 0;
    if (filteredCount) filteredCount.textContent = fc;
    if (unfilteredCount) unfilteredCount.textContent = uc;
    if (filteredBadge) filteredBadge.textContent = fc;
    if (unfilteredBadge) unfilteredBadge.textContent = uc;

    // Update pipeline funnel sent count (today's junior-suitable jobs)
    const funnelSent = document.getElementById('funnel-sent');
    if (funnelSent && isToday) funnelSent.textContent = fc;

    const noJobsMessage = isToday ? 'No jobs sent today' : `No jobs sent on ${dateLabel}`;

    if (filteredBody) {
        const filteredJobs = data.filtered_jobs || [];
        if (filteredJobs.length === 0) {
            filteredBody.innerHTML = `<tr><td colspan="5" class="loading-row">${noJobsMessage}</td></tr>`;
        } else {
            filteredBody.innerHTML = filteredJobs.map(job => `
                <tr>
                    <td>${escapeHtml(job.company)}</td>
                    <td>${escapeHtml(job.title)}</td>
                    <td>${escapeHtml(job.city)}</td>
                    <td>${job.sent_at ? job.sent_at.split(' ')[1] || job.sent_at : 'N/A'}</td>
                    <td><a href="${escapeHtml(job.link)}" target="_blank" class="job-link">View →</a></td>
                </tr>
            `).join('');
        }
    }

    if (unfilteredBody) {
        const unfilteredJobs = data.unfiltered_jobs || [];
        if (unfilteredJobs.length === 0) {
            unfilteredBody.innerHTML = `<tr><td colspan="5" class="loading-row">${noJobsMessage}</td></tr>`;
        } else {
            unfilteredBody.innerHTML = unfilteredJobs.map(job => `
                <tr>
                    <td>${escapeHtml(job.company)}</td>
                    <td>${escapeHtml(job.title)}</td>
                    <td>${escapeHtml(job.city)}</td>
                    <td>${job.sent_at ? job.sent_at.split(' ')[1] || job.sent_at : 'N/A'}</td>
                    <td><a href="${escapeHtml(job.link)}" target="_blank" class="job-link">View →</a></td>
                </tr>
            `).join('');
        }
    }
}

/* ============================================
   Analytics
   ============================================ */

const analyticsState = {
    start: '',
    end: '',
    companies: '',
    keyword: '',
};

function initAnalytics() {
    const today = new Date();
    const start = new Date();
    start.setDate(today.getDate() - 30);

    const startInput = document.getElementById('analytics-start-date');
    const endInput = document.getElementById('analytics-end-date');
    const companiesInput = document.getElementById('analytics-companies');
    const keywordInput = document.getElementById('analytics-keyword');
    const applyBtn = document.getElementById('analytics-apply-btn');
    const resetBtn = document.getElementById('analytics-reset-btn');

    if (!startInput || !endInput || !applyBtn || !resetBtn) return;

    analyticsState.start = start.toISOString().split('T')[0];
    analyticsState.end = today.toISOString().split('T')[0];
    startInput.value = analyticsState.start;
    endInput.value = analyticsState.end;

    if (applyBtn) {
        applyBtn.addEventListener('click', async () => {
            analyticsState.start = startInput.value || analyticsState.start;
            analyticsState.end = endInput.value || analyticsState.end;
            analyticsState.companies = companiesInput ? companiesInput.value.trim() : '';
            analyticsState.keyword = keywordInput ? keywordInput.value.trim() : '';
            await loadAnalyticsData();
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            analyticsState.start = start.toISOString().split('T')[0];
            analyticsState.end = today.toISOString().split('T')[0];
            analyticsState.companies = '';
            analyticsState.keyword = '';
            startInput.value = analyticsState.start;
            endInput.value = analyticsState.end;
            if (companiesInput) companiesInput.value = '';
            if (keywordInput) keywordInput.value = '';
            await loadAnalyticsData();
        });
    }
}

function buildAnalyticsQuery() {
    const params = new URLSearchParams();
    if (analyticsState.start) params.set('start', analyticsState.start);
    if (analyticsState.end) params.set('end', analyticsState.end);
    if (analyticsState.companies) params.set('companies', analyticsState.companies);
    if (analyticsState.keyword) params.set('keyword', analyticsState.keyword);
    return params.toString();
}

async function loadAnalyticsData() {
    const errorEl = document.getElementById('analytics-error');
    if (errorEl) {
        errorEl.style.display = 'none';
        errorEl.textContent = '';
    }

    const query = buildAnalyticsQuery();
    try {
        const [overviewRes, companiesRes, titlesRes, reqsRes, trendRes, matchesRes] = await Promise.all([
            fetchAPI('/api/analytics/overview?' + query),
            fetchAPI('/api/analytics/top-companies?' + query),
            fetchAPI('/api/analytics/top-titles?' + query),
            fetchAPI('/api/analytics/top-requirements?' + query),
            fetchAPI('/api/analytics/trend?' + query),
            fetchAPI('/api/analytics/matching-jobs?' + query),
        ]);

        updateAnalyticsOverview(overviewRes.overview || {});
        updateAnalyticsTable('analytics-top-companies-body', companiesRes.items || [], 'company');
        updateAnalyticsTable('analytics-top-titles-body', titlesRes.items || [], 'title');
        updateAnalyticsTable('analytics-top-reqs-body', reqsRes.items || [], 'term');
        updateAnalyticsTrend(trendRes.items || []);
        updateAnalyticsMatchingJobs(matchesRes.items || []);
    } catch (error) {
        console.error('Analytics load error:', error);
        if (errorEl) {
            errorEl.textContent = 'Failed to load analytics data: ' + error.message;
            errorEl.style.display = 'block';
        }
    }
}

function updateAnalyticsOverview(overview) {
    document.getElementById('analytics-kpi-records').textContent = formatNumber(overview.total_records || 0);
    document.getElementById('analytics-kpi-companies').textContent = formatNumber(overview.unique_companies || 0);
    document.getElementById('analytics-kpi-titles').textContent = formatNumber(overview.unique_titles || 0);
    document.getElementById('analytics-kpi-with-reqs').textContent = formatNumber(overview.rows_with_requirements || 0);
}

function updateAnalyticsTable(tbodyId, items, labelKey) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="2" class="loading-row">No data for selected filters.</td></tr>';
        return;
    }
    tbody.innerHTML = items.map((item) => `
        <tr>
            <td>${escapeHtml(String(item[labelKey] || ''))}</td>
            <td>${formatNumber(item.count || 0)}</td>
        </tr>
    `).join('');
}

function updateAnalyticsTrend(items) {
    const canvas = document.getElementById('analytics-trend-chart');
    if (!canvas) return;

    const labels = (items || []).map(i => i.date || '');
    const values = (items || []).map(i => i.count || 0);

    if (analyticsTrendChart) {
        analyticsTrendChart.data.labels = labels;
        analyticsTrendChart.data.datasets[0].data = values;
        analyticsTrendChart.update();
        return;
    }

    analyticsTrendChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Records',
                data: values,
                borderColor: chartColors.blue,
                backgroundColor: 'rgba(67, 97, 238, 0.12)',
                fill: true,
                tension: 0.3,
                borderWidth: 2,
                pointRadius: 3,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#9ca3af' }
                }
            },
            scales: {
                x: { ticks: { color: '#6b7280' }, grid: { color: 'rgba(38,38,38,0.8)' } },
                y: { beginAtZero: true, ticks: { color: '#6b7280' }, grid: { color: 'rgba(38,38,38,0.8)' } }
            }
        }
    });
}

function updateAnalyticsMatchingJobs(items) {
    const tbody = document.getElementById('analytics-matching-jobs-body');
    if (!tbody) return;

    if (!analyticsState.keyword) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading-row">Add a keyword and click Apply to inspect matching jobs.</td></tr>';
        return;
    }

    if (!items || items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading-row">No jobs matched this keyword for the selected filters.</td></tr>';
        return;
    }

    tbody.innerHTML = items.map((item) => {
        const created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
        const reqs = Array.isArray(item.reqs) ? item.reqs.filter(Boolean).join('; ') : '';
        return `
            <tr>
                <td>${escapeHtml(item.company || '')}</td>
                <td>${escapeHtml(item.job_title || '')}</td>
                <td>${escapeHtml(created)}</td>
                <td class="analytics-long-cell">${escapeHtml(item.desc || '')}</td>
                <td class="analytics-long-cell">${escapeHtml(reqs)}</td>
                <td>${item.link ? `<a href="${escapeHtml(item.link)}" target="_blank" class="job-link">Open →</a>` : ''}</td>
            </tr>
        `;
    }).join('');
}

/* ============================================
   Utilities
   ============================================ */

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return num.toLocaleString();
}

/* ============================================
   Admin Panel
   ============================================ */

let supabaseClient = null;
let adminSession = null;

function initAdmin() {
    const url = window.__SUPABASE_URL__;
    const key = window.__SUPABASE_ANON_KEY__;

    if (!url || !key) {
        console.warn('Supabase config not provided; admin panel disabled.');
        const btn = document.getElementById('sidebar-admin-btn');
        if (btn) btn.style.display = 'none';
        return;
    }

    supabaseClient = window.supabase.createClient(url, key);

    supabaseClient.auth.getSession().then(({ data: { session } }) => {
        if (session) setAdminSession(session);
    });

    supabaseClient.auth.onAuthStateChange((_event, session) => {
        if (session) {
            setAdminSession(session);
        } else {
            clearAdminSession();
        }
    });

    document.getElementById('modal-close').addEventListener('click', closeAdminModal);
    document.getElementById('admin-modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeAdminModal();
    });
    document.getElementById('google-sign-in-btn').addEventListener('click', signInWithGoogle);
    document.getElementById('admin-sign-out-btn').addEventListener('click', adminSignOut);
    document.getElementById('add-company-form').addEventListener('submit', handleAddCompany);
}

async function setAdminSession(session) {
    const token = session.access_token;
    try {
        const res = await fetch('/api/admin/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!res.ok) {
            await supabaseClient.auth.signOut();
            clearAdminSession();
            const loginErr = document.getElementById('login-error');
            loginErr.textContent = 'Access denied. Only the admin can sign in here.';
            loginErr.style.display = 'block';
            return;
        }
    } catch (_) {
        // network error -- allow session so user can retry
    }

    adminSession = session;
    const email = session.user?.email || '';
    document.getElementById('admin-email-display').textContent = email;
    document.getElementById('admin-login-view').style.display = 'none';
    document.getElementById('admin-form-view').style.display = 'block';
    const adminBtn = document.getElementById('sidebar-admin-btn');
    if (adminBtn) adminBtn.classList.add('authenticated');
}

function clearAdminSession() {
    adminSession = null;
    document.getElementById('admin-login-view').style.display = 'block';
    document.getElementById('admin-form-view').style.display = 'none';
    const adminBtn = document.getElementById('sidebar-admin-btn');
    if (adminBtn) adminBtn.classList.remove('authenticated');
}

function openAdminModal() {
    document.getElementById('admin-modal').classList.add('active');
}

function closeAdminModal() {
    document.getElementById('admin-modal').classList.remove('active');
    hideFormMessage();
    document.getElementById('login-error').style.display = 'none';
}

async function signInWithGoogle() {
    if (!supabaseClient) return;
    const loginErr = document.getElementById('login-error');
    loginErr.style.display = 'none';

    const { error } = await supabaseClient.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin + '/' },
    });

    if (error) {
        loginErr.textContent = error.message;
        loginErr.style.display = 'block';
    }
}

async function adminSignOut() {
    if (!supabaseClient) return;
    await supabaseClient.auth.signOut();
    clearAdminSession();
}

function showFormMessage(text, isError) {
    const el = document.getElementById('form-message');
    el.textContent = text;
    el.className = 'form-message ' + (isError ? 'error' : 'success');
    el.style.display = 'block';
}

function hideFormMessage() {
    document.getElementById('form-message').style.display = 'none';
}

async function handleAddCompany(e) {
    e.preventDefault();
    hideFormMessage();

    if (!adminSession) {
        showFormMessage('Not authenticated. Please sign in again.', true);
        return;
    }

    const company = document.getElementById('company-name').value.trim();
    const linkType = document.getElementById('link-type').value;
    const uniqueId = document.getElementById('unique-id').value.trim();

    if (!company || !linkType) {
        showFormMessage('Company name and link type are required.', true);
        return;
    }

    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Adding...';

    try {
        const res = await fetch(window.location.origin + '/api/admin/companies', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + adminSession.access_token,
            },
            body: JSON.stringify({
                company: company,
                link_type: linkType,
                unique_identifier: uniqueId || undefined,
            }),
        });

        const data = await res.json();

        if (res.ok) {
            showFormMessage(`"${company}" added successfully!`, false);
            document.getElementById('add-company-form').reset();
        } else {
            showFormMessage(data.error || 'Failed to add company.', true);
        }
    } catch (err) {
        showFormMessage('Network error: ' + err.message, true);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Add Company';
    }
}

/* ============================================
   Bootstrap
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    initDashboard();
    initAdmin();
});
