// analytics.js


// data structure to hold current analytics state (last query, results, etc.) 
// if we want to persist it across view changes in the future
const analyticsState = {
    initializedOnce: false,  // if false, we'll run a default query on first load. Set to true after that.
    sqlText: "",  // last SQL query text that was run
    tableHTML: "",  // innerHTML of the results table, so we can restore it if we navigate away and back
    csvEnabled: false // whether the "Download CSV" link should be shown/enabled
};

function initializeAnalyticsView() {
    const sqlInput = document.getElementById("analytics-sql-input");
    const runBtn = document.getElementById("analytics-run-btn");
    const downloadLink = document.getElementById("analytics-download-link");
    const table = document.getElementById("analytics-results-table");

    // Always rebind buttons
    runBtn.onclick = runAnalyticsQuery;
    downloadLink.onclick = downloadAnalyticsCSV;

    console.log("Analytics view initialized");

    // If we have saved state, restore it
    if (analyticsState.initializedOnce) {
        sqlInput.value = analyticsState.sqlText;
        table.innerHTML = analyticsState.tableHTML;

        if (analyticsState.csvEnabled) {
            enableAnalyticsDownload();
        } else {
            disableAnalyticsDownload();
        }

        return; // Done — no default query
    }

    // First time only: set default query and run it
    sqlInput.value = `
SELECT id, timestamp, unit_name, qtag, result, model
FROM submissions
ORDER BY id DESC
LIMIT 20
`.trim();

    runAnalyticsQuery();
    analyticsState.initializedOnce = true;
}

async function runAnalyticsQuery() {
    const sql = document.getElementById("analytics-sql-input").value;
    const errorBox = document.getElementById("analytics-error");
    const noResults = document.getElementById("analytics-no-results");

    errorBox.style.display = "none";
    noResults.style.display = "none";
    disableAnalyticsDownload();

    try {
        const response = await fetch("/admin/dbviewer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sql_query: sql })
        });

        const data = await response.json();

        if (data.error) {
            errorBox.textContent = data.error;
            errorBox.style.display = "block";
            clearAnalyticsResults();
            return;   // <-- finally still runs
        }

        renderAnalyticsResults(data.columns, data.rows);

        if (data.rows && data.rows.length > 0) {
            enableAnalyticsDownload();
        }

    } catch (err) {
        console.log("Error running analytics query:", err);
        errorBox.textContent = "Failed to run query.";
        errorBox.style.display = "block";
        clearAnalyticsResults();
    } finally {
        // ALWAYS runs — success, error, early return, anything
        saveAnalyticsState();
    }
}

function clearAnalyticsResults() {
    const table = document.getElementById("analytics-results-table");
    table.querySelector("thead").innerHTML = "";
    table.querySelector("tbody").innerHTML = "";

    document.getElementById("analytics-error").style.display = "none";
    document.getElementById("analytics-no-results").style.display = "none";
}

async function runAnalyticsQuery() {
    const sql = document.getElementById("analytics-sql-input").value;
    const errorBox = document.getElementById("analytics-error");
    const noResults = document.getElementById("analytics-no-results");

    errorBox.style.display = "none";
    noResults.style.display = "none";
    disableAnalyticsDownload();  // Hide download until we know if there are results

    try {
        const response = await fetch("/admin/dbviewer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sql_query: sql })
        });

        const data = await response.json();

        if (data.error) {
            errorBox.textContent = data.error;
            errorBox.style.display = "block";
            return;
        }

        renderAnalyticsResults(data.columns, data.rows);

        // Enable download if there are results 
        if (data.rows && data.rows.length > 0) {
            enableAnalyticsDownload();  
        }

    } catch (err) {
        console.log("Error running analytics query:", err);
        errorBox.textContent = "Failed to run query.";
        errorBox.style.display = "block";
    }

    saveAnalyticsState();  // Save the current state so we can restore it if needed
}

function renderAnalyticsResults(columns, rows) {
    const table = document.getElementById("analytics-results-table");
    const thead = table.querySelector("thead");
    const tbody = table.querySelector("tbody");

    thead.innerHTML = "";
    tbody.innerHTML = "";

    if (!columns || columns.length === 0) {
        document.getElementById("analytics-no-results").style.display = "block";
        return;
    }

    const headerRow = document.createElement("tr");

    const actionTh = document.createElement("th");
    actionTh.textContent = "Action";
    headerRow.appendChild(actionTh);

    columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);

    rows.forEach(row => {
        const tr = document.createElement("tr");

        const actionTd = document.createElement("td");
        const link = document.createElement("a");
        link.href = `/admin/submission/${row[0]}`;
        link.target = "_blank";
        link.textContent = "View";
        link.style.cssText = `
            padding: 4px 8px;
            background-color: #57068c;
            color: white;
            text-decoration: none;
            border-radius: 3px;
            font-size: 12px;
        `;
        actionTd.appendChild(link);
        tr.appendChild(actionTd);

        row.forEach(cell => {
            const td = document.createElement("td");
            td.textContent = cell;
            td.title = cell;
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });
}

function downloadAnalyticsCSV() {
    window.location.href = "/admin/dbviewer/download";
}

function enableAnalyticsDownload() {
    document.getElementById("analytics-download-link").style.display = "inline";
    document.getElementById("analytics-download-menu-item").disabled = false;
}

function disableAnalyticsDownload() {
    document.getElementById("analytics-download-link").style.display = "none";
    document.getElementById("analytics-download-menu-item").disabled = true;
}

function saveAnalyticsState() {
    const sqlInput = document.getElementById("analytics-sql-input");
    const table = document.getElementById("analytics-results-table");
    const downloadLink = document.getElementById("analytics-download-link");

    analyticsState.sqlText = sqlInput ? sqlInput.value : "";
    analyticsState.tableHTML = table ? table.innerHTML : "";
    analyticsState.csvEnabled = downloadLink && downloadLink.style.display !== "none";
}
