// analytics.js

function initializeAnalyticsView() {
    const sqlInput = document.getElementById("analytics-sql-input");
    const runBtn = document.getElementById("analytics-run-btn");
    const downloadLink = document.getElementById("analytics-download-link");

    sqlInput.value = `
SELECT id, timestamp, unit_name, qtag, result, model
FROM submissions
ORDER BY id DESC
LIMIT 20
`.trim();

    runBtn.onclick = runAnalyticsQuery;
    downloadLink.onclick = downloadAnalyticsCSV;
    downloadLink.style.display = "none";

    clearAnalyticsResults();
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
    const downloadLink = document.getElementById("analytics-download-link");

    errorBox.style.display = "none";
    noResults.style.display = "none";
    downloadLink.style.display = "none";

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

        if (data.rows && data.rows.length > 0) {
            downloadLink.style.display = "inline-block";
        }

    } catch (err) {
        console.log("Error running analytics query:", err);
        errorBox.textContent = "Failed to run query.";
        errorBox.style.display = "block";
    }
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