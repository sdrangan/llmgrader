// analytics.js


// data structure to hold current analytics state (last query, results, etc.) 
// if we want to persist it across view changes in the future
const analyticsState = {
    initializedOnce: false,  // if false, we'll run a default query on first load. Set to true after that.
    sqlText: "",  // last SQL query text that was run
    tableHTML: "",  // innerHTML of the results table, so we can restore it if we navigate away and back
    csvEnabled: false, // whether the "Download CSV" link should be shown/enabled
    schemaTables: null,  // [{name, columns}] from /admin/dbviewer/schema; fetched once per page load
    schemaCollapsed: false,  // whether the whole column reference is hidden
    collapsedTables: {}  // table name -> true when that list of columns is folded away
};

function initializeAnalyticsView() {
    const sqlInput = document.getElementById("analytics-sql-input");
    const runBtn = document.getElementById("analytics-run-btn");
    const downloadLink = document.getElementById("analytics-download-link");
    const table = document.getElementById("analytics-results-table");
    const schemaToggle = document.getElementById("analytics-schema-toggle");

    // Always rebind buttons
    runBtn.onclick = runAnalyticsQuery;
    downloadLink.onclick = downloadAnalyticsCSV;
    schemaToggle.onclick = toggleAnalyticsSchemaPanel;

    console.log("Analytics view initialized");

    // The column reference outlives a single query, so it is restored (or
    // fetched) on every entry to the view, before the early return below.
    applyAnalyticsSchemaCollapse();
    loadAnalyticsSchema();

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
    // Only the table: the error and no-results boxes belong to the caller,
    // which hides them before a run and shows one of them afterwards. Clearing
    // them here would wipe the error message that was just displayed.
    const table = document.getElementById("analytics-results-table");
    table.querySelector("thead").innerHTML = "";
    table.querySelector("tbody").innerHTML = "";
}

// --- Column reference -----------------------------------------------------

async function loadAnalyticsSchema() {
    // Cached for the life of the page: columns only change on a redeploy.
    if (analyticsState.schemaTables) {
        renderAnalyticsSchema(analyticsState.schemaTables);
        return;
    }

    try {
        const response = await fetch("/admin/dbviewer/schema");
        const data = await response.json();

        if (data.error) {
            showAnalyticsSchemaMessage(data.error);
            return;
        }

        const tables = data.tables || [];

        // First load only: open the table people actually query, fold the rest.
        if (Object.keys(analyticsState.collapsedTables).length === 0) {
            const primary = tables.some(t => t.name === "submissions")
                ? "submissions"
                : (tables[0] && tables[0].name);
            tables.forEach(t => {
                analyticsState.collapsedTables[t.name] = t.name !== primary;
            });
        }

        analyticsState.schemaTables = tables;
        renderAnalyticsSchema(tables);

    } catch (err) {
        console.log("Error loading schema:", err);
        showAnalyticsSchemaMessage("Could not load columns.");
    }
}

function showAnalyticsSchemaMessage(text) {
    const body = document.getElementById("analytics-schema-body");
    body.innerHTML = "";

    const message = document.createElement("p");
    message.className = "info-text";
    message.textContent = text;
    body.appendChild(message);
}

function renderAnalyticsSchema(tables) {
    const body = document.getElementById("analytics-schema-body");

    if (!tables || tables.length === 0) {
        showAnalyticsSchemaMessage("No tables found.");
        return;
    }

    body.innerHTML = "";

    tables.forEach(table => {
        const isCollapsed = !!analyticsState.collapsedTables[table.name];

        const section = document.createElement("div");
        section.className = isCollapsed ? "schema-table collapsed" : "schema-table";

        const nameBtn = document.createElement("button");
        nameBtn.type = "button";
        nameBtn.className = "schema-table-name";
        nameBtn.textContent = (isCollapsed ? "▸ " : "▾ ") + table.name;
        nameBtn.title = "Show or hide the columns of " + table.name;
        nameBtn.onclick = () => {
            analyticsState.collapsedTables[table.name] = !isCollapsed;
            renderAnalyticsSchema(analyticsState.schemaTables);
        };
        section.appendChild(nameBtn);

        const columnWrap = document.createElement("div");
        columnWrap.className = "schema-columns";

        (table.columns || []).forEach(column => {
            const colBtn = document.createElement("button");
            colBtn.type = "button";
            colBtn.className = "schema-column";
            colBtn.textContent = column;
            colBtn.title = "Insert " + table.name + "." + column;
            colBtn.onclick = () => insertAnalyticsSchemaText(column);
            columnWrap.appendChild(colBtn);
        });

        section.appendChild(columnWrap);
        body.appendChild(section);
    });
}

function insertAnalyticsSchemaText(text) {
    const sqlInput = document.getElementById("analytics-sql-input");
    const value = sqlInput.value;
    const start = sqlInput.selectionStart;
    const end = sqlInput.selectionEnd;

    // Space it off the preceding word so two columns clicked in a row do not
    // run together, but leave "(" and "." and existing whitespace alone.
    const before = value.slice(0, start);
    const previous = before.slice(-1);
    const needsSpace = before.length > 0 && !/[\s(.]/.test(previous);
    const insert = (needsSpace ? " " : "") + text;

    sqlInput.value = before + insert + value.slice(end);

    const caret = start + insert.length;
    sqlInput.setSelectionRange(caret, caret);
    sqlInput.focus();

    saveAnalyticsState();
}

function toggleAnalyticsSchemaPanel() {
    analyticsState.schemaCollapsed = !analyticsState.schemaCollapsed;
    applyAnalyticsSchemaCollapse();
}

function applyAnalyticsSchemaCollapse() {
    const panel = document.getElementById("analytics-schema-panel");
    const toggle = document.getElementById("analytics-schema-toggle");

    if (analyticsState.schemaCollapsed) {
        panel.classList.add("collapsed");
        toggle.textContent = "Show";
    } else {
        panel.classList.remove("collapsed");
        toggle.textContent = "Hide";
    }
}

// --- Results --------------------------------------------------------------

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
