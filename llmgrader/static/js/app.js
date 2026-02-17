// Grade/Admin selection sync implemented
console.log("UI loaded.");

//
// GLOBAL STATE
//
let currentUnitQtags = [];          // list of qtags
let currentUnitItems = {};          // dict: qtag -> question object
let currentUnitName = null;         // current unit name
let currentStudentSolutions = {};   // dict: qtag -> student solution
let currentQtagName = null;
let currentActiveView = null;

// sessionState[unitName][qtag] = {
//     student_solution: "...",
//     parts: {
//         [part_label]: { feedback: "", explanation: "", grade_status: "" }
//     }
// }
let sessionState = {};

// Create menu system on page load
document.addEventListener("DOMContentLoaded", () => {
    initializeMenuSystem();
    loadView("grade");   // or whatever your default view is
});

//
// ---------------------------
//  SESSION STATE PERSISTENCE
// ---------------------------
function loadSessionState() {
    const stored = localStorage.getItem("llmgrader_session");
    if (stored) {
        try {
            sessionState = JSON.parse(stored);
            console.log("Session state loaded from localStorage");
        } catch (e) {
            console.error("Failed to parse session state:", e);
            sessionState = {};
        }
    } else {
        sessionState = {};
    }
}

function saveSessionState() {
    try {
        localStorage.setItem("llmgrader_session", JSON.stringify(sessionState));
        console.log("Session state saved to localStorage");
    } catch (e) {
        console.error("Failed to save session state:", e);
    }
}

function getSessionData(unitName, qtag) {
    if (!sessionState[unitName]) {
        sessionState[unitName] = {};
    }
    if (!sessionState[unitName][qtag]) {
        sessionState[unitName][qtag] = {
            student_solution: "",
            parts: {}
        };
    }
    // Ensure parts object exists
    if (!sessionState[unitName][qtag].parts) {
        sessionState[unitName][qtag].parts = {};
    }
    return sessionState[unitName][qtag];
}

function updateSessionData(unitName, qtag, updates, partLabel = null) {
    const data = getSessionData(unitName, qtag);
    
    // If partLabel is provided, update the part-specific data
    if (partLabel) {
        if (!data.parts[partLabel]) {
            data.parts[partLabel] = {
                feedback: "",
                explanation: "",
                grade_status: ""
            };
        }
        Object.assign(data.parts[partLabel], updates);
    } else {
        // Otherwise, update qtag-level data (e.g., student_solution)
        Object.assign(data, updates);
    }
    
    saveSessionState();
}

function pruneSessionState(unitName, currentQtags) {
    // Remove any qtags from sessionState[unit] that are not in currentQtags
    if (!sessionState[unitName]) {
        return; // Nothing to prune
    }
    
    const existingQtags = Object.keys(sessionState[unitName]);
    const currentQtagSet = new Set(currentQtags);
    
    let pruned = false;
    existingQtags.forEach(qtag => {
        if (!currentQtagSet.has(qtag)) {
            console.log(`Pruning stale qtag: ${qtag} from unit: ${unitName}`);
            delete sessionState[unitName][qtag];
            pruned = true;
        }
    });
    
    if (pruned) {
        saveSessionState();
        console.log(`Session state pruned for unit: ${unitName}`);
    }
}


//
// ---------------------------
//  OpenAI KEY MANAGEMENT
// ---------------------------
function getApiKey() {
    return localStorage.getItem("openai_api_key") || "";
}


//
// ---------------------------
//  VIEW LOADING
// ---------------------------
async function loadView(name) {
    try {
        const response = await fetch(`/static/views/${name}.html`);
        const html = await response.text();
        document.getElementById("view-container").innerHTML = html;

        // Update global active view state
        currentActiveView = name;
        
        // Set the active view state (updates body attribute and dropdown visibility)
        if (typeof setActiveView === 'function') {
            setActiveView(name);
        }
        
        initializeView(name);
    } catch (error) {
        console.error(`Failed to load view: ${name}`, error);
    }
}

function initializeView(name) {
    if (name === "grade") {
        // Reattach grade view event listeners, splitters, dropdowns
        initializeGradeView();
    } else if (name === "admin") {
        // Reattach admin view dropdowns and splitters
        initializeAdminView();
    } else if (name === "dashboard") {
        // Initialize dashboard view
        initializeDashboardView();
    } else if (name === "analytics") {
        // Initialize analytics view
        initializeAnalyticsView();
    }
}


function initVerticalDivider(dividerId) {
    const divider = document.getElementById(dividerId);
    if (!divider) return;

    const row = divider.closest(".layout-row");
    if (!row) return;

    const columns = row.querySelectorAll(":scope > .column");
    const leftCol = columns[0];
    const rightCol = columns[1];
    if (!leftCol || !rightCol) return;

    const storageKey = `llmgrader:divider:${dividerId}:leftWidth`;
    const storedWidth = Number(localStorage.getItem(storageKey));

    const applyWidth = (width) => {
        const rect = row.getBoundingClientRect();
        const min = 200;
        const max = rect.width - 200;
        const clamped = Math.max(min, Math.min(max, width));
        leftCol.style.flex = `0 0 ${clamped}px`;
    };

    if (Number.isFinite(storedWidth)) {
        applyWidth(storedWidth);
    }

    let isDragging = false;

    divider.addEventListener("mousedown", () => {
        isDragging = true;
    });

    document.addEventListener("mouseup", () => {
        if (!isDragging) return;
        isDragging = false;
        const leftWidth = leftCol.getBoundingClientRect().width;
        localStorage.setItem(storageKey, String(leftWidth));
    });

    document.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        const rect = row.getBoundingClientRect();
        const offset = e.clientX - rect.left;
        applyWidth(offset);
    });
}

function initializeGradeView() {
    // Reattach horizontal divider (question/solution splitter)
    const grade_hdivider = document.querySelector(".divider");
    const topPanel = document.getElementById("grade-question-panel");
    const bottomPanel = document.getElementById("grade-solution-panel");

    if (grade_hdivider && topPanel && bottomPanel) {
        let dragging = false;

        grade_hdivider.addEventListener("mousedown", () => {
            dragging = true;
            document.body.style.userSelect = "none";
        });

        document.addEventListener("mouseup", () => {
            dragging = false;
            document.body.style.userSelect = "";
        });

        document.addEventListener("mousemove", (e) => {
            if (!dragging) return;

            const containerHeight = grade_hdivider.parentElement.offsetHeight;
            const newTopHeight = e.clientY - grade_hdivider.parentElement.offsetTop;

            if (newTopHeight < 100 || newTopHeight > containerHeight - 100) return;

            topPanel.style.flex = `0 0 ${newTopHeight}px`;
            bottomPanel.style.flex = `1`;
        });
    }

    
    // Reattach grade_vdivider controls left/right split in Grade view
    initVerticalDivider("grade-vertical-divider");

    if (currentUnitName && currentUnitQtags.length > 0) {
        populateQuestionDropdown(currentUnitQtags, currentQtagName);

        // After populating, restore the correct question from global state
        const qSelect = document.getElementById("question-number");
        if (qSelect && currentQtagName && currentUnitQtags.includes(currentQtagName)) {
            qSelect.value = currentQtagName;
            displayQuestion(currentQtagName);
        }
    }


    // Initialize global selection state from Grade View dropdowns
    const unitSelect = document.getElementById("unit-select");
    const questionSelect = document.getElementById("question-number");

    if (unitSelect && questionSelect) {
        currentUnitName = unitSelect.value;
        currentQtagName = questionSelect.value;
    }

}

// Admin View now matches Grade View layout and splitter behavior
function initializeAdminView() {
    setupAdminDropdowns();
    setupAdminSplitters();
}

function setupAdminDropdowns() {
    const unitSelect = document.getElementById("admin-unit-select");
    const qSelect = document.getElementById("admin-question-select");

    if (!unitSelect || !qSelect) return;

    // Populate units from currentUnitQtags data
    // We'll need to fetch units first
    fetch("/units").then(r => r.json()).then(units => {
        unitSelect.innerHTML = units.map(u => `<option value="${u}">${u}</option>`).join("");
        
        const firstUnit = units[0];
        unitSelect.value = currentUnitName;

        unitSelect.addEventListener("change", () => {
            currentUnitName = unitSelect.value;
            populateAdminQuestions();
            displayAdminCurrent();
        });

        qSelect.addEventListener("change", () => {
            currentQtagName = qSelect.value;
            displayAdminCurrent();
        });

        if (units.length > 0) {
            populateAdminQuestions();
        }
    });
}

function populateAdminQuestions() {
    const unit = document.getElementById("admin-unit-select").value;
    const qSelect = document.getElementById("admin-question-select");

    if (!unit) return;

    // Fetch unit data
    fetch(`/unit/${unit}`).then(r => r.json()).then(data => {
        qSelect.innerHTML = data.qtags.map(qtag => `<option value="${qtag}">${qtag}</option>`).join("");

        // ⭐ ADD THESE TWO LINES
        currentUnitQtags = data.qtags;
        currentUnitItems = data.items;

        // If the currentQtagName is not in this unit, fall back to the first qtag
        if (!data.qtags.includes(currentQtagName)) {
            qSelect.value = data.qtags[0];
            currentQtagName = data.qtags[0];   // <-- CRITICAL FIX
        } else {
            qSelect.value = currentQtagName;
        }

        // <-- REQUIRED to sync Admin → Grade
        displayAdminCurrent();
    });
}

function displayAdminCurrent() {
    displayAdminQuestion(currentUnitName, currentQtagName);
}

// Admin View: Display selected question with reference solution and grading notes
// Fixed: Uses q.solution_text (reference solution, not student solution)
// Fixed: Grading notes formatting preserved via CSS white-space: pre-wrap
function displayAdminQuestion(unit, qtag) {
    // Fetch unit data to get question details
    fetch(`/unit/${unit}`).then(r => r.json()).then(data => {
        const q = data.items[qtag];
        if (!q) return;

        document.getElementById("admin-question-text").innerHTML = q.question_text || "";
        document.getElementById("admin-solution-text").innerHTML = q.solution || "";
        document.getElementById("admin-grading-notes").textContent = q.grading_notes || "";

        if (window.MathJax) MathJax.typesetPromise();
    });
}

function setupAdminSplitters() {
    // Horizontal divider (question/solution splitter)
    const hdivider = document.querySelector("#admin-view .divider");
    const topPanel = document.getElementById("admin-question-panel");
    const bottomPanel = document.getElementById("admin-solution-panel");

    if (hdivider && topPanel && bottomPanel) {
        let dragging = false;

        hdivider.addEventListener("mousedown", () => {
            dragging = true;
            document.body.style.userSelect = "none";
        });

        document.addEventListener("mouseup", () => {
            dragging = false;
            document.body.style.userSelect = "";
        });

        document.addEventListener("mousemove", (e) => {
            if (!dragging) return;

            const containerHeight = hdivider.parentElement.offsetHeight;
            const newTopHeight = e.clientY - hdivider.parentElement.offsetTop;

            if (newTopHeight < 100 || newTopHeight > containerHeight - 100) return;

            topPanel.style.flex = `0 0 ${newTopHeight}px`;
            bottomPanel.style.flex = `1`;
        });
    }

    // Vertical divider (left/right column splitter)
    initVerticalDivider("admin-vertical-divider");
}

//
// ---------------------------
//  UNIT LOADING
// ---------------------------
document.addEventListener("DOMContentLoaded", () => {
    loadSessionState();
    loadView("grade").then(() => {
        loadUnits();
    });
});

async function loadUnits() {
    const resp = await fetch("/units");
    const units = await resp.json();

    const dropdown = document.getElementById("unit-select");
    dropdown.innerHTML = "";

    units.forEach(unit => {
        const opt = document.createElement("option");
        opt.value = unit;
        opt.textContent = unit;
        dropdown.appendChild(opt);
    });

    if (units.length > 0) {
        const savedUnit = sessionStorage.getItem("selectedUnit");
        if (savedUnit && units.includes(savedUnit)) {
            dropdown.value = savedUnit;
            await loadUnit(savedUnit);   // <-- IMPORTANT
        } else {
            dropdown.value = units[0];
            await loadUnit(units[0]);    // <-- IMPORTANT
        }

        // NOW the Grade View dropdowns exist and are populated
        const unitSelect = document.getElementById("unit-select");
        const questionSelect = document.getElementById("question-number");

        if (unitSelect && questionSelect) {
            currentUnitName = unitSelect.value;
            currentQtagName = questionSelect.value;
        }
    }

    const unitSelect = dropdown;
    dropdown.onchange = () => {
        sessionStorage.setItem("selectedUnit", dropdown.value);
        currentUnitName = unitSelect.value;
        loadUnit(dropdown.value);
    };
}

async function loadUnit(unitName) {
    const resp = await fetch(`/unit/${unitName}`);
    const data = await resp.json();

    currentUnitName = unitName;
    currentUnitQtags = data.qtags;
    currentUnitItems = data.items;

    // Prune stale qtags from session state
    pruneSessionState(unitName, data.qtags);

    // Update the question dropdown.  This will be ignored if
    // we are in a view with no question dropdown (e.g., Dashboard)
    populateQuestionDropdown(currentUnitQtags);

    if (currentActiveView === "dashboard") {
        loadDashboardUnit(unitName);
    }
    
}


//
// ---------------------------
//  RESTORE PART UI
// ---------------------------
function restorePartUI(qtag, partLabel) {
    // Get session data for the question
    const sessionData = getSessionData(currentUnitName, qtag);
    
    // Get part-specific data if available
    let partData = null;
    if (partLabel && partLabel !== "all" && sessionData.parts[partLabel]) {
        partData = sessionData.parts[partLabel];
    } else if (partLabel === "all" && sessionData.parts["all"]) {
        partData = sessionData.parts["all"];
    }
    
    const explanationBox = document.getElementById("full-explanation-box");
    const feedbackBox = document.getElementById("feedback-box");
    const gradeStatus = document.getElementById("grade-status");
    
    // Restore from part-specific data if available
    if (partData) {
        if (partData.explanation) {
            explanationBox.textContent = partData.explanation;
        } else {
            explanationBox.textContent = "Not yet graded. No explanation yet.";
        }
        
        if (partData.feedback) {
            feedbackBox.textContent = partData.feedback;
        } else {
            feedbackBox.textContent = "Not yet graded. No feedback yet.";
        }
        
        if (partData.grade_status) {
            gradeStatus.textContent = 
                partData.grade_status === "pass" ? "Correct" :
                partData.grade_status === "fail" ? "Incorrect" :
                partData.grade_status === "error" ? "Error" :
                partData.grade_status;
            gradeStatus.className = 
                partData.grade_status === "pass" ? "status-correct" :
                partData.grade_status === "fail" ? "status-incorrect" :
                partData.grade_status === "error" ? "status-error" :
                "status-not-graded";
        } else {
            gradeStatus.textContent = "";
            gradeStatus.className = "status-not-graded";
        }
    } else {
        // No part data available - show default state
        explanationBox.textContent = "Not yet graded. No explanation yet.";
        feedbackBox.textContent = "Not yet graded. No feedback yet.";
        gradeStatus.textContent = "";
        gradeStatus.className = "status-not-graded";
    }
}

//
// ---------------------------
//  DISPLAY QUESTION
// ---------------------------
function displayQuestion(qtag) {
    const questionBox = document.getElementById("question-text");
    if (!questionBox) {
        // We are not a view with a question box — abort cleanly
        return;
    }

    console.log("Displaying question:", qtag);
    const qdata = currentUnitItems[qtag];
    if (!qdata) {
        // Abort cleanly if qtag not found (e.g., due to stale session state)
        console.warn(`Question data not found for qtag: ${qtag}`);
        return;
    }

    // Update question text
    questionBox.innerHTML = qdata.question_text || "";
    
    // Trigger MathJax rendering if available
    if (window.MathJax) {
        MathJax.typesetPromise();
    }

    // Restore session state for this question
    const sessionData = getSessionData(currentUnitName, qtag);

    // Update student solution - prefer session state, then fall back to loaded file
    const solBox = document.getElementById("student-solution");
    solBox.value = sessionData.student_solution || 
                   currentStudentSolutions[qtag]?.solution || "";

    // ---------------------------
    // Update PART DROPDOWN
    // ---------------------------
    const partSelect = document.getElementById("part-select");
    partSelect.innerHTML = "";

    const parts = qdata.parts || [];

    // Always include "All"
    const optAll = document.createElement("option");
    optAll.value = "all";
    optAll.textContent = "All";
    partSelect.appendChild(optAll);

    parts.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.part_label;
        opt.textContent = p.part_label;
        partSelect.appendChild(opt);
    });

    // Add event listener for part selection changes
    partSelect.onchange = () => {
        restorePartUI(qtag, partSelect.value);
    };

    // Restore grading UI from session state for the currently selected part
    restorePartUI(qtag, partSelect.value);

    // Update grade points/optional display
    const gradePoints = document.getElementById("grade-points");
    if (qdata.grade === false) {
        gradePoints.textContent = "optional";
    } else if (qdata.grade === true) {
        const totalPoints = (qdata.parts || []).reduce((sum, part) => {
            return sum + parseInt(part.points || 0, 10);
        }, 0);
        gradePoints.textContent = `${totalPoints} points`;
    } else {
        gradePoints.textContent = "";
    }
}


//
// ---------------------------
//  QUESTION DROPDOWN
// ---------------------------
function populateQuestionDropdown(qtags, selectedQtag = null) {
    const dropdown = document.getElementById("question-number");
    if (!dropdown) {
        // We are in a view with no question dropdown — abort cleanly
        return;
    }

    dropdown.innerHTML = "";

    qtags.forEach(qtag => {
        const opt = document.createElement("option");
        opt.value = qtag;
        opt.textContent = qtag;   // display qtag directly
        dropdown.appendChild(opt);
    });

    if (qtags.length > 0) {
        let qtagToUse = qtags[0];

        if (selectedQtag && qtags.includes(selectedQtag)) {
            qtagToUse = selectedQtag;
        }

        dropdown.value = qtagToUse;
        displayQuestion(qtagToUse);
        currentQtagName = qtagToUse;   // keep global in sync
    }

    dropdown.onchange = () => {
        displayQuestion(dropdown.value);
        currentQtagName = dropdown.value;
    };

    // sessionState save/restore wiring restored after UI refactor
    // Add event listener to save student solution on input
    // This code only runs if the student-solution textarea exists
    const solBox = document.getElementById("student-solution");
    if (solBox) {
        solBox.addEventListener("input", () => {
            const qtag = dropdown.value;
            if (currentUnitName && qtag) {
                // Save student solution at qtag level (not per-part)
                updateSessionData(currentUnitName, qtag, {
                    student_solution: solBox.value
                }, null);
            }
        });
    }
}


//
// ---------------------------
//  GRADE CURRENT QUESTION
// ---------------------------
async function gradeCurrentQuestion() {
    const dropdown = document.getElementById("question-number");
    const qtag = dropdown.value;

    const studentSolution = document.getElementById("student-solution").value;
    const partSelect = document.getElementById("part-select");
    const selectedPart = partSelect.value;

    const apiKey = getApiKey();
    if (!apiKey) {
        alert("Please set your OpenAI API key first.");
        return;
    }

    const timeout = Number(document.getElementById("timeout-input").value);

    const gradeBtn = document.getElementById("grade-button");
    gradeBtn.disabled = true;
    gradeBtn.textContent = "Grading...";

    const model = document.getElementById("model-select").value;

    const resp = await fetch("/grade", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            unit: currentUnitName,
            qtag: qtag,
            student_solution: studentSolution,
            part_label: selectedPart,
            model: model,
            api_key: apiKey,
            timeout: timeout
        })
    });

    const data = await resp.json();

    gradeBtn.disabled = false;
    gradeBtn.textContent = "Grade";

    const gradeStatusText = 
        data.result === "pass" ? "Correct" :
        data.result === "fail" ? "Incorrect" :
        "Error";

    const gradeStatusClass =
        data.result === "pass" ? "status-correct" :
        data.result === "fail" ? "status-incorrect" :
        "status-error";

    document.getElementById("grade-status").textContent = gradeStatusText;
    document.getElementById("grade-status").className = gradeStatusClass;
    document.getElementById("feedback-box").textContent = data.feedback;
    document.getElementById("full-explanation-box").textContent =
        data.full_explanation;

    // Save student solution at qtag level
    updateSessionData(currentUnitName, qtag, {
        student_solution: studentSolution
    });

    // Save grading results per part
    // If "all" is selected, we can store under "all" as a part_label
    // or handle it differently based on your requirements
    const partToSave = selectedPart === "all" ? "all" : selectedPart;
    updateSessionData(currentUnitName, qtag, {
        feedback: data.feedback || "",
        explanation: data.full_explanation || "",
        grade_status: data.result || ""
    }, partToSave);
}


//
// ---------------------------
//  UNIT RELOADING
// ---------------------------
async function reloadUnitData() {
    console.log("Reloading all units...");

    const res = await fetch("/reload", { method: "POST" });
    const data = await res.json();

    if (data.status === "ok") {
        console.log("Units reloaded.");

        await loadUnits();

        const unitName = document.getElementById("unit-select").value;
        if (unitName) {
            await loadUnit(unitName);
        }
    }
}


//
// ---------------------------
//  SAVE/LOAD RESULTS
// ---------------------------
function saveResultsForUnit() {
    if (!currentUnitName) {
        alert("No unit selected.");
        return;
    }

    // Get session state for current unit
    const unitData = sessionState[currentUnitName] || {};
    const jsonString = JSON.stringify(unitData, null, 2);

    // Create blob and download
    const blob = new Blob([jsonString], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${currentUnitName}_results.json`;
    a.click();
    URL.revokeObjectURL(url);

    console.log(`Saved results for unit: ${currentUnitName}`);
}

// Set up load results file handler
document.addEventListener("DOMContentLoaded", () => {
    const fileInput = document.getElementById("load-results-file");
    if (fileInput) {
        fileInput.addEventListener("change", async (event) => {
            const file = event.target.files[0];
            if (!file) return;

            if (!currentUnitName) {
                alert("No unit selected.");
                return;
            }

            try {
                const text = await file.text();
                const data = JSON.parse(text);

                // Assign loaded data to current unit
                sessionState[currentUnitName] = data;
                saveSessionState();

                console.log(`Loaded results for unit: ${currentUnitName}`);

                // Refresh UI with current question
                const dropdown = document.getElementById("question-number");
                const currentQtag = dropdown.value;
                if (currentQtag) {
                    displayQuestion(currentQtag);
                }

                alert("Results loaded successfully.");
            } catch (e) {
                console.error("Failed to load results:", e);
                alert("Failed to load results. Please check the file format.");
            }

            // Reset file input
            event.target.value = "";
        });
    }
});

function updateEditMenuState() {
    const active = document.activeElement;

    const isEditable =
        active &&
        (active.tagName === "INPUT" ||
         active.tagName === "TEXTAREA" ||
         active.isContentEditable);

    document.getElementById("menu-cut").disabled = !isEditable;
    document.getElementById("menu-copy").disabled = !isEditable;
    document.getElementById("menu-delete").disabled = !isEditable;

    // Paste is always enabled — browser will handle permission
    document.getElementById("menu-paste").disabled = false;
}

document.addEventListener("DOMContentLoaded", () => {

    document.getElementById("about-button").addEventListener("click", () => {
        document.getElementById("about-modal").classList.remove("hidden");
    });

    document.getElementById("about-close").addEventListener("click", () => {
        document.getElementById("about-modal").classList.add("hidden");
    });

});

