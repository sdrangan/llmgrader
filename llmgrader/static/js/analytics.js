// analytics.js

// The databases the view can query (plans/mcp_usage.md, decision 8).  The key
// is the `db` value the /admin/dbviewer routes take; the server refuses any
// other.  Each one has its own default query and presets.
const ANALYTICS_DATABASES = {
    grade: {
        label: "Grade DB",
        primaryTable: "submissions",
        // A submissions row opens in /admin/submission/<id>; usage rows have
        // no such page.
        viewLinks: true,
        defaultQuery: () => defaultAnalyticsQuery(),
        presets: () => gradePresets()
    },
    mcp: {
        label: "MCP DB",
        primaryTable: "mcp_calls",
        viewLinks: false,
        defaultQuery: () => defaultMcpQuery(),
        presets: () => mcpPresets()
    }
};

// Where the database choice is kept between page loads.  Per viewer and
// optional: the view works the same when storage is blocked.
const ANALYTICS_DB_STORAGE_KEY = "llmgrader_analytics_db";

function emptyDbState() {
    return {
        sqlText: "",  // last query run (or typed) against this database
        schemaTables: null,  // [{name, columns}] from /admin/dbviewer/schema; fetched once per page load
        collapsedTables: {}  // table name -> true when that list of columns is folded away
    };
}

// data structure to hold current analytics state (last query, results, etc.)
// so it persists across view changes
const analyticsState = {
    initializedOnce: false,  // if false, we'll run a default query on first load. Set to true after that.
    activeDb: loadAnalyticsDbChoice(),
    perDb: { grade: emptyDbState(), mcp: emptyDbState() },
    tableHTML: "",  // innerHTML of the results table, so we can restore it if we navigate away and back
    csvEnabled: false, // whether the "Download CSV" link should be shown/enabled
    schemaCollapsed: false  // whether the whole column reference is hidden
};

function loadAnalyticsDbChoice() {
    try {
        const saved = window.localStorage.getItem(ANALYTICS_DB_STORAGE_KEY);
        return Object.prototype.hasOwnProperty.call(ANALYTICS_DATABASES, saved) ? saved : "grade";
    } catch (err) {
        return "grade";
    }
}

function saveAnalyticsDbChoice(db) {
    try {
        window.localStorage.setItem(ANALYTICS_DB_STORAGE_KEY, db);
    } catch (err) {
        // Private window or blocked storage: the choice lasts this page only.
    }
}

function activeDbState() {
    return analyticsState.perDb[analyticsState.activeDb];
}

function initializeAnalyticsView() {
    const sqlInput = document.getElementById("analytics-sql-input");
    const runBtn = document.getElementById("analytics-run-btn");
    const downloadLink = document.getElementById("analytics-download-link");
    const table = document.getElementById("analytics-results-table");
    const schemaToggle = document.getElementById("analytics-schema-toggle");
    const presetSelect = document.getElementById("analytics-preset-select");

    // Always rebind buttons
    runBtn.onclick = runAnalyticsQuery;
    downloadLink.onclick = downloadAnalyticsCSV;
    schemaToggle.onclick = toggleAnalyticsSchemaPanel;
    presetSelect.onchange = applyAnalyticsPreset;

    console.log("Analytics view initialized");

    // Which database is active shows in the menu, the header and the
    // preset list, all of which outlive a single query.
    renderAnalyticsDbChoice();

    // The column reference outlives a single query, so it is restored (or
    // fetched) on every entry to the view, before the early return below.
    applyAnalyticsSchemaCollapse();
    loadAnalyticsSchema();

    // If we have saved state, restore it
    if (analyticsState.initializedOnce) {
        sqlInput.value = activeDbState().sqlText;
        table.innerHTML = analyticsState.tableHTML;

        if (analyticsState.csvEnabled) {
            enableAnalyticsDownload();
        } else {
            disableAnalyticsDownload();
        }

        return; // Done — no default query
    }

    // First time only: set default query and run it
    sqlInput.value = ANALYTICS_DATABASES[analyticsState.activeDb].defaultQuery();

    runAnalyticsQuery();
    analyticsState.initializedOnce = true;
}

// --- Choosing the database --------------------------------------------------

function switchAnalyticsDb(db) {
    if (!Object.prototype.hasOwnProperty.call(ANALYTICS_DATABASES, db)) return;

    const sqlInput = document.getElementById("analytics-sql-input");
    if (db === analyticsState.activeDb) {
        renderAnalyticsDbChoice();
        return;
    }

    // Keep what is in the box for when this database is chosen again.
    if (sqlInput) activeDbState().sqlText = sqlInput.value;

    analyticsState.activeDb = db;
    saveAnalyticsDbChoice(db);
    renderAnalyticsDbChoice();

    // The menu is global but the view's elements exist only once it has
    // been loaded; before that, the choice is all there is to record.
    if (!sqlInput) return;

    // A result is never shown under the wrong database: clear it.
    document.getElementById("analytics-error").style.display = "none";
    document.getElementById("analytics-no-results").style.display = "none";
    clearAnalyticsResults();
    disableAnalyticsDownload();

    sqlInput.value = activeDbState().sqlText || ANALYTICS_DATABASES[db].defaultQuery();
    loadAnalyticsSchema();
    saveAnalyticsState();
}

function renderAnalyticsDbChoice() {
    const db = analyticsState.activeDb;
    const config = ANALYTICS_DATABASES[db];

    document.querySelectorAll(".analytics-db-item").forEach(item => {
        const active = item.dataset.db === db;
        item.setAttribute("aria-checked", active ? "true" : "false");
        const check = item.querySelector(".analytics-db-check");
        if (check) check.textContent = active ? "✓" : "";
    });

    document.querySelectorAll(".analytics-mcp-only").forEach(element => {
        element.style.display = db === "mcp" ? "" : "none";
    });

    const name = document.getElementById("analytics-db-name");
    if (name) name.textContent = config.label;

    const presetSelect = document.getElementById("analytics-preset-select");
    if (presetSelect) {
        presetSelect.innerHTML = "";
        const prompt = document.createElement("option");
        prompt.value = "";
        prompt.textContent = "Choose a preset query…";
        presetSelect.appendChild(prompt);
        config.presets().forEach((preset, index) => {
            const option = document.createElement("option");
            option.value = String(index);
            option.textContent = preset.label;
            presetSelect.appendChild(option);
        });
    }
}

function applyAnalyticsPreset() {
    const presetSelect = document.getElementById("analytics-preset-select");
    const index = presetSelect.value;
    if (index === "") return;

    const preset = ANALYTICS_DATABASES[analyticsState.activeDb].presets()[Number(index)];
    presetSelect.value = "";
    if (!preset) return;

    document.getElementById("analytics-sql-input").value = preset.sql;
    runAnalyticsQuery();
}

// --- Running a query --------------------------------------------------------

async function runAnalyticsQuery() {
    const sql = document.getElementById("analytics-sql-input").value;
    const errorBox = document.getElementById("analytics-error");
    const noResults = document.getElementById("analytics-no-results");
    const db = analyticsState.activeDb;

    errorBox.style.display = "none";
    noResults.style.display = "none";
    disableAnalyticsDownload();

    try {
        const response = await fetch("/admin/dbviewer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sql_query: sql, db: db })
        });

        const data = await response.json();

        // Switched database while this was running: its result belongs to
        // the other one, and is dropped rather than shown under this name.
        if (db !== analyticsState.activeDb) return;

        if (data.error) {
            errorBox.textContent = data.error;
            errorBox.style.display = "block";
            clearAnalyticsResults();
            return;   // <-- finally still runs
        }

        renderAnalyticsResults(data.columns, data.rows);
        analyticsState.perDb[db].sqlText = sql;

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

// The course id pattern from llmgrader_config.xsd, mirrored here.  The value
// is interpolated into SQL text, so it is checked rather than trusted even
// though the server minted it: anything that fails this is dropped and the
// query simply spans every course.
const COURSE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;

function currentCourseId() {
    const id = (window.LLMGRADER_COURSE_ID || "").trim();
    return COURSE_ID_PATTERN.test(id) ? id : "";
}

// The query the box opens with.  Scoped to the course being served, because
// submissions from every course share one table -- an unscoped default would
// quietly report another course's numbers once there is a second one.  Rows
// that predate the column are stamped with the default course on boot, and a
// row written outside a course keeps course_id NULL, so neither hides here by
// accident.  The clause is plain SQL in an editable box: widen it to all
// courses by deleting the WHERE line.
function defaultAnalyticsQuery() {
    const courseId = currentCourseId();
    const where = courseId ? `\nWHERE course_id = '${courseId}'` : "";
    return `
SELECT id, timestamp, course_id, unit_name, qtag, result, model
FROM submissions${where}
ORDER BY id DESC
LIMIT 20
`.trim();
}

// The MCP database's opening query: the latest calls.  Scoped like the grade
// default, but keeping rows with no course -- initialize, tools/list and
// list_courses name none, and they are most of what a session starts with.
function defaultMcpQuery() {
    const courseId = currentCourseId();
    const where = courseId ? `\nWHERE course_id = '${courseId}' OR course_id IS NULL` : "";
    return `
SELECT id, ts, client, method, tool, course_id, unit, qtag, deck, slide, status, result_items, duration_ms
FROM mcp_calls${where}
ORDER BY id DESC
LIMIT 20
`.trim();
}

// --- Presets ----------------------------------------------------------------

function courseClause(column, joiner) {
    const courseId = currentCourseId();
    return courseId ? `\n${joiner} ${column} = '${courseId}'` : "";
}

function gradePresets() {
    return [
        { label: "Latest submissions", sql: defaultAnalyticsQuery() },
        {
            label: "Submissions per day, by unit",
            sql: `
SELECT substr(timestamp, 1, 10) AS day, unit_name, COUNT(*) AS submissions,
       ROUND(AVG(points), 2) AS avg_points
FROM submissions${courseClause("course_id", "WHERE")}
GROUP BY day, unit_name
ORDER BY day DESC, submissions DESC
`.trim()
        },
        {
            label: "Submissions by package version",
            sql: `
SELECT COALESCE(package_version, '(none)') AS package_version, COUNT(*) AS submissions,
       MIN(timestamp) AS first, MAX(timestamp) AS last
FROM submissions${courseClause("course_id", "WHERE")}
GROUP BY package_version
ORDER BY last DESC
`.trim()
        },
        {
            label: "Timeouts and errors",
            sql: `
SELECT id, timestamp, unit_name, qtag, model, timed_out, result, latency_ms
FROM submissions
WHERE (timed_out = 1 OR result = 'error')${courseClause("course_id", "AND")}
ORDER BY id DESC
`.trim()
        }
    ];
}

// Sessions (decision 5): the minted session_id where the client echoed one;
// otherwise inferred -- same client, split where calls are more than 10
// minutes apart.  Two students on one client at the same time merge.
const MCP_SESSIONS_CTE = `
WITH gaps AS (
  SELECT id, ts, client, tool,
         LAG(ts) OVER (PARTITION BY COALESCE(client, '') ORDER BY ts) AS prev_ts
  FROM mcp_calls
  WHERE session_id IS NULL
), inferred AS (
  SELECT id, ts, client, tool,
         SUM(CASE WHEN prev_ts IS NULL
                    OR (julianday(ts) - julianday(prev_ts)) * 1440 > 10
                  THEN 1 ELSE 0 END)
           OVER (PARTITION BY COALESCE(client, '') ORDER BY ts ROWS UNBOUNDED PRECEDING) AS n
  FROM gaps
), tagged AS (
  SELECT session_id AS session, ts, client, tool FROM mcp_calls WHERE session_id IS NOT NULL
  UNION ALL
  SELECT 'inferred:' || COALESCE(client, 'unknown') || ':' || n, ts, client, tool FROM inferred
), sessions AS (
  SELECT session, MAX(client) AS client, MIN(ts) AS started, MAX(ts) AS ended,
         COUNT(*) AS requests, COUNT(tool) AS tool_calls, COUNT(DISTINCT tool) AS tools_used,
         GROUP_CONCAT(DISTINCT tool) AS tools
  FROM tagged
  GROUP BY session
)`.trim();

function mcpPresets() {
    const course = (joiner) => courseClause("course_id", joiner);
    return [
        { label: "Latest calls", sql: defaultMcpQuery() },
        {
            label: "Calls per day, by tool",
            sql: `
SELECT substr(ts, 1, 10) AS day, tool, COUNT(*) AS calls
FROM mcp_calls
WHERE method = 'tools/call'${course("AND")}
GROUP BY day, tool
ORDER BY day DESC, calls DESC
`.trim()
        },
        {
            label: "Most-viewed questions (with rubric and solution views)",
            sql: `
SELECT course_id, unit, qtag,
       SUM(tool = 'get_question') AS question_views,
       SUM(tool = 'get_rubric') AS rubric_views,
       SUM(tool = 'get_solution') AS solution_views
FROM mcp_calls
WHERE tool IN ('get_question', 'get_rubric', 'get_solution') AND status = 'ok'${course("AND")}
GROUP BY course_id, unit, qtag
ORDER BY question_views DESC, solution_views DESC
`.trim()
        },
        {
            label: "Solution views compared with rubric views",
            sql: `
SELECT course_id, unit, qtag,
       SUM(tool = 'get_rubric') AS rubric_views,
       SUM(tool = 'get_solution') AS solution_views,
       ROUND(1.0 * SUM(tool = 'get_solution') / NULLIF(SUM(tool = 'get_rubric'), 0), 2)
         AS solutions_per_rubric
FROM mcp_calls
WHERE tool IN ('get_rubric', 'get_solution') AND status = 'ok'${course("AND")}
GROUP BY course_id, unit, qtag
ORDER BY solution_views DESC
`.trim()
        },
        {
            label: "Most-viewed slides",
            sql: `
SELECT course_id, deck, slide, COUNT(*) AS views
FROM mcp_calls
WHERE tool = 'get_slide' AND status = 'ok'${course("AND")}
GROUP BY course_id, deck, slide
ORDER BY views DESC
`.trim()
        },
        {
            label: "Searches that found nothing",
            sql: `
SELECT substr(ts, 1, 10) AS day, COUNT(*) AS searches,
       SUM(result_items = 0) AS found_nothing
FROM mcp_calls
WHERE tool = 'search_slides' AND status = 'ok'${course("AND")}
GROUP BY day
ORDER BY day DESC
`.trim()
        },
        {
            label: "Errors and refusals",
            sql: `
SELECT id, ts, status, client, method, tool, course_id, unit, qtag, deck, slide, error
FROM mcp_calls
WHERE status <> 'ok'
ORDER BY id DESC
`.trim()
        },
        {
            label: "Calls by client",
            sql: `
SELECT COALESCE(client, 'unknown') AS client, protocol, COUNT(*) AS requests,
       SUM(method = 'tools/call') AS tool_calls
FROM mcp_calls
GROUP BY client, protocol
ORDER BY requests DESC
`.trim()
        },
        {
            label: "Sessions per day",
            sql: `
${MCP_SESSIONS_CTE}
SELECT substr(started, 1, 10) AS day, COUNT(*) AS sessions,
       ROUND(AVG(tool_calls), 1) AS calls_per_session,
       ROUND(AVG(tools_used), 1) AS tools_per_session
FROM sessions
GROUP BY day
ORDER BY day DESC
`.trim()
        },
        {
            label: "Sessions, one row each",
            sql: `
${MCP_SESSIONS_CTE}
SELECT session, client, started, ended, requests, tool_calls, tools_used, tools
FROM sessions
ORDER BY started DESC
`.trim()
        }
    ];
}

// --- Retention ----------------------------------------------------------------

async function deleteMcpUsageBefore() {
    if (analyticsState.activeDb !== "mcp") return;

    const before = window.prompt(
        "Delete MCP usage recorded before which date? (YYYY-MM-DD)\n\n"
        + "This removes usage rows only. Grades are not touched."
    );
    if (!before) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(before.trim())) {
        alert("Give the date as YYYY-MM-DD.");
        return;
    }
    if (!window.confirm("Delete every MCP usage row recorded before " + before.trim()
                        + "? This cannot be undone.")) {
        return;
    }

    try {
        const response = await fetch("/admin/dbviewer/mcp/delete_before", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ before: before.trim() })
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            alert(data.error || "Could not delete usage.");
            return;
        }
        alert("Deleted " + data.deleted + " usage row(s) recorded before " + data.before + ".");
        if (document.getElementById("analytics-sql-input")) runAnalyticsQuery();
    } catch (err) {
        console.log("Error deleting usage:", err);
        alert("Could not delete usage.");
    }
}

// --- Column reference -----------------------------------------------------

async function loadAnalyticsSchema() {
    const db = analyticsState.activeDb;
    const state = analyticsState.perDb[db];

    // Cached for the life of the page: columns only change on a redeploy.
    if (state.schemaTables) {
        renderAnalyticsSchema(state.schemaTables);
        return;
    }

    showAnalyticsSchemaMessage("Loading columns…");

    try {
        const response = await fetch("/admin/dbviewer/schema?db=" + encodeURIComponent(db));
        const data = await response.json();

        // Another database was chosen while this loaded; it renders its own.
        if (db !== analyticsState.activeDb) return;

        if (data.error) {
            showAnalyticsSchemaMessage(data.error);
            return;
        }

        const tables = data.tables || [];

        // First load only: open the table people actually query, fold the rest.
        if (Object.keys(state.collapsedTables).length === 0) {
            const preferred = ANALYTICS_DATABASES[db].primaryTable;
            const primary = tables.some(t => t.name === preferred)
                ? preferred
                : (tables[0] && tables[0].name);
            tables.forEach(t => {
                state.collapsedTables[t.name] = t.name !== primary;
            });
        }

        state.schemaTables = tables;
        renderAnalyticsSchema(tables);

    } catch (err) {
        console.log("Error loading schema:", err);
        if (db === analyticsState.activeDb) {
            showAnalyticsSchemaMessage("Could not load columns.");
        }
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
    const collapsedTables = activeDbState().collapsedTables;

    if (!tables || tables.length === 0) {
        showAnalyticsSchemaMessage("No tables found.");
        return;
    }

    body.innerHTML = "";

    tables.forEach(table => {
        const isCollapsed = !!collapsedTables[table.name];

        const section = document.createElement("div");
        section.className = isCollapsed ? "schema-table collapsed" : "schema-table";

        const nameBtn = document.createElement("button");
        nameBtn.type = "button";
        nameBtn.className = "schema-table-name";
        nameBtn.textContent = (isCollapsed ? "▸ " : "▾ ") + table.name;
        nameBtn.title = "Show or hide the columns of " + table.name;
        nameBtn.onclick = () => {
            collapsedTables[table.name] = !isCollapsed;
            renderAnalyticsSchema(activeDbState().schemaTables);
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
    const viewLinks = ANALYTICS_DATABASES[analyticsState.activeDb].viewLinks;

    thead.innerHTML = "";
    tbody.innerHTML = "";

    if (!columns || columns.length === 0) {
        document.getElementById("analytics-no-results").style.display = "block";
        return;
    }

    const headerRow = document.createElement("tr");

    if (viewLinks) {
        const actionTh = document.createElement("th");
        actionTh.textContent = "Action";
        headerRow.appendChild(actionTh);
    }

    columns.forEach(col => {
        const th = document.createElement("th");
        th.textContent = col;
        headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);

    rows.forEach(row => {
        const tr = document.createElement("tr");

        if (viewLinks) {
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
        }

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
    window.location.href = "/admin/dbviewer/download?db=" + encodeURIComponent(analyticsState.activeDb);
}

function enableAnalyticsDownload() {
    document.getElementById("analytics-download-link").style.display = "inline";
    document.getElementById("analytics-download-menu-item").disabled = false;
}

function disableAnalyticsDownload() {
    const link = document.getElementById("analytics-download-link");
    if (link) link.style.display = "none";
    document.getElementById("analytics-download-menu-item").disabled = true;
}

function saveAnalyticsState() {
    const sqlInput = document.getElementById("analytics-sql-input");
    const table = document.getElementById("analytics-results-table");
    const downloadLink = document.getElementById("analytics-download-link");

    if (sqlInput) activeDbState().sqlText = sqlInput.value;
    analyticsState.tableHTML = table ? table.innerHTML : "";
    analyticsState.csvEnabled = !!downloadLink && downloadLink.style.display !== "none";
}

// The menu is in the page from the start, before the view is ever opened:
// show the remembered choice there straight away.
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAnalyticsDbChoice);
} else {
    renderAnalyticsDbChoice();
}
