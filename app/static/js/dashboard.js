// LiteLLM Dashboard Interactive Script
let dailyChartInstance = null;
let modelChartInstance = null;

document.addEventListener("DOMContentLoaded", () => {
    initDateInputs();
    fetchDashboardMetrics();

    document.getElementById("btn-apply-filter")?.addEventListener("click", () => {
        fetchDashboardMetrics();
    });

    document.getElementById("btn-dismiss-error")?.addEventListener("click", () => {
        hideErrorBanner();
    });

    document.getElementById("btn-logout")?.addEventListener("click", async () => {
        try {
            await fetch("/api/auth/logout", { method: "POST" });
            window.location.href = "/login";
        } catch (e) {
            window.location.href = "/login";
        }
    });
});

function showErrorBanner(message) {
    const banner = document.getElementById("dashboard-error-banner");
    const textEl = document.getElementById("dashboard-error-text");
    if (banner && textEl) {
        textEl.innerText = message;
        banner.style.display = "flex";
    }
}

function hideErrorBanner() {
    const banner = document.getElementById("dashboard-error-banner");
    if (banner) {
        banner.style.display = "none";
    }
}

function initDateInputs() {
    const endDateInput = document.getElementById("end-date");
    const startDateInput = document.getElementById("start-date");

    if (!endDateInput || !startDateInput) return;

    const today = new Date();
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(today.getDate() - 6);

    endDateInput.value = formatDate(today);
    startDateInput.value = formatDate(sevenDaysAgo);
}

function formatDate(dateObj) {
    const year = dateObj.getFullYear();
    const month = String(dateObj.getMonth() + 1).padStart(2, '0');
    const day = String(dateObj.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

async function fetchDashboardMetrics() {
    const startDate = document.getElementById("start-date")?.value;
    const endDate = document.getElementById("end-date")?.value;

    const queryParams = new URLSearchParams();
    if (startDate) queryParams.append("start_date", startDate);
    if (endDate) queryParams.append("end_date", endDate);

    try {
        const response = await fetch(`/api/dashboard/stats?${queryParams.toString()}`);
        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        const data = await response.json();
        if (!response.ok || data.error) {
            const errorMsg = data.detail || (typeof data.error === 'string' ? data.error : `Server returned status ${response.status}`);
            showErrorBanner(errorMsg);
            return;
        }

        hideErrorBanner();
        updateKPICards(data.summary, data.model_breakdown);
        renderDailyChart(data.daily_trend);
        renderModelChart(data.model_breakdown);
        renderDetailedTable(data.daily_trend, data.model_breakdown, data.detailed_logs);

    } catch (error) {
        console.error("Failed to load dashboard metrics:", error);
        showErrorBanner("Could not connect to dashboard API: " + error.message);
    }
}

function getAggregatedModelBreakdown(modelBreakdown) {
    const aggregated = {};
    (modelBreakdown || []).forEach(m => {
        const raw = String(m.model || "unknown");
        const cleanName = raw.includes("/") ? raw.split("/").pop().trim() : raw.trim();
        if (!aggregated[cleanName]) {
            aggregated[cleanName] = {
                model: cleanName,
                tokens: 0,
                prompt_tokens: 0,
                completion_tokens: 0,
                spend: 0,
                requests: 0
            };
        }
        aggregated[cleanName].tokens += (m.tokens || 0);
        aggregated[cleanName].prompt_tokens += (m.prompt_tokens || 0);
        aggregated[cleanName].completion_tokens += (m.completion_tokens || 0);
        aggregated[cleanName].spend += (m.spend || 0);
        aggregated[cleanName].requests += (m.requests || 0);
    });
    return Object.values(aggregated).filter(m => (m.tokens || 0) > 0 || (m.spend || 0) > 0);
}

function updateKPICards(summary, modelBreakdown) {
    if (!summary) return;

    const activeModels = getAggregatedModelBreakdown(modelBreakdown);

    document.getElementById("kpi-total-spend").innerText = `$${(summary.total_spend || 0).toFixed(2)}`;
    document.getElementById("kpi-total-tokens").innerText = (summary.total_tokens || 0).toLocaleString();
    document.getElementById("kpi-prompt-tokens").innerText = (summary.prompt_tokens || 0).toLocaleString();
    document.getElementById("kpi-completion-tokens").innerText = (summary.completion_tokens || 0).toLocaleString();
    document.getElementById("kpi-active-models").innerText = activeModels.length;
}

function renderDailyChart(dailyTrend) {
    const ctx = document.getElementById("dailyChart")?.getContext("2d");
    if (!ctx) return;

    const labels = dailyTrend.map(d => d.date);
    const promptTokens = dailyTrend.map(d => d.prompt_tokens);
    const completionTokens = dailyTrend.map(d => d.completion_tokens);
    const spendData = dailyTrend.map(d => d.spend);

    if (dailyChartInstance) {
        dailyChartInstance.destroy();
    }

    dailyChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Prompt Tokens',
                    data: promptTokens,
                    backgroundColor: 'rgba(99, 102, 241, 0.75)',
                    borderColor: '#6366f1',
                    borderWidth: 1,
                    stack: 'tokens',
                    yAxisID: 'y'
                },
                {
                    label: 'Completion Tokens',
                    data: completionTokens,
                    backgroundColor: 'rgba(6, 182, 212, 0.75)',
                    borderColor: '#06b6d4',
                    borderWidth: 1,
                    stack: 'tokens',
                    yAxisID: 'y'
                },
                {
                    label: 'Daily Spend ($)',
                    data: spendData,
                    type: 'line',
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: false,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    labels: { color: '#9ca3af', font: { family: 'Inter' } }
                },
                tooltip: {
                    padding: 12,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#9ca3af' }
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#9ca3af' },
                    title: { display: true, text: 'Tokens', color: '#9ca3af' }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#10b981', callback: value => '$' + value.toFixed(3) },
                    title: { display: true, text: 'Spend ($)', color: '#10b981' }
                }
            }
        }
    });
}

function renderModelChart(modelBreakdown) {
    const canvas = document.getElementById("modelChart");
    if (!canvas) return;
    const container = canvas.parentElement;

    const activeModels = getAggregatedModelBreakdown(modelBreakdown);

    if (activeModels.length === 0) {
        if (modelChartInstance) {
            modelChartInstance.destroy();
            modelChartInstance = null;
        }
        let emptyNotice = container.querySelector(".chart-empty-notice");
        if (!emptyNotice) {
            emptyNotice = document.createElement("div");
            emptyNotice.className = "chart-empty-notice";
            emptyNotice.style.cssText = "display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:0.875rem;";
            emptyNotice.innerText = "No model token consumption in selected range";
            container.appendChild(emptyNotice);
        }
        canvas.style.display = "none";
        emptyNotice.style.display = "flex";
        return;
    }

    const emptyNotice = container.querySelector(".chart-empty-notice");
    if (emptyNotice) {
        emptyNotice.style.display = "none";
    }
    canvas.style.display = "block";

    const labels = activeModels.map(m => m.model);
    const dataValues = activeModels.map(m => m.tokens || m.spend || 0);
    const colors = [
        '#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#a855f7', '#f43f5e', '#ec4899', '#8b5cf6', '#3b82f6', '#14b8a6'
    ];

    if (modelChartInstance) {
        modelChartInstance.destroy();
    }

    const ctx = canvas.getContext("2d");
    modelChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: dataValues,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 2,
                borderColor: '#111827'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#9ca3af', padding: 14, font: { family: 'Inter' } }
                }
            },
            cutout: '70%'
        }
    });
}

function renderDetailedTable(dailyTrend, modelBreakdown, rawLogs) {
    const tbody = document.getElementById("table-body-daily");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!dailyTrend || dailyTrend.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim);">No consumption logs found for the selected date range.</td></tr>`;
        return;
    }

    // Render daily aggregated rows
    dailyTrend.slice().reverse().forEach(row => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><strong>${row.date}</strong></td>
            <td><span class="badge-model">Daily Aggregate</span></td>
            <td>${row.prompt_tokens.toLocaleString()}</td>
            <td>${row.completion_tokens.toLocaleString()}</td>
            <td><strong>${row.total_tokens.toLocaleString()}</strong></td>
            <td style="color: var(--accent-emerald); font-weight: 600;">$${row.spend.toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}
