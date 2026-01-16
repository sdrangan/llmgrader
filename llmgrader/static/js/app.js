console.log("UI loaded.");

//
// GLOBAL STATE
//
let currentUnitQtags = [];          // list of qtags
let currentUnitItems = {};          // dict: qtag -> question object
let currentUnitName = null;         // current unit name
let currentStudentSolutions = {};   // dict: qtag -> student solution

// sessionState[unitName][qtag] = { student_solution, feedback, explanation, grade_status }
let sessionState = {};

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
            feedback: "",
            explanation: "",
            grade_status: ""
        };
    }
    return sessionState[unitName][qtag];
}

function updateSessionData(unitName, qtag, updates) {
    const data = getSessionData(unitName, qtag);
    Object.assign(data, updates);
    saveSessionState();
}

//
// ---------------------------
//  LOAD STUDENT SOLUTIONS FILE
// ---------------------------
document.getElementById("load-student-file").onclick = function () {
    const fileInput = document.getElementById("student-file");
    if (!fileInput.files.length) {
        console.log("No file selected");
        return;
    }

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    fetch("/load_file", {
        method: "POST",
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            console.error("Server error:", data.error);
            return;
        }

        // Student solutions now keyed by qtag
        currentStudentSolutions = data || {};

        // Update student solution box if a question is selected
        const dropdown = document.getElementById("question-number");
        const qtag = dropdown.value;
        document.getElementById("student-solution").value =
            currentStudentSolutions[qtag]?.solution || "";
    });
};


//
// ---------------------------
//  OpenAI KEY MANAGEMENT
// ---------------------------
document.addEventListener("DOMContentLoaded", () => {
    // Load session state from localStorage
    loadSessionState();

    const input = document.getElementById("apiKeyInput");
    const saveBtn = document.getElementById("saveKeyBtn");

    const saved = localStorage.getItem("openai_api_key");
    if (saved) input.value = saved;

    saveBtn.addEventListener("click", () => {
        const key = input.value.trim();
        if (key) {
            localStorage.setItem("openai_api_key", key);
            alert("API key saved in your browser.");
        }
    });
});

function getApiKey() {
    return localStorage.getItem("openai_api_key") || "";
}


//
// ---------------------------
//  UNIT LOADING
// ---------------------------
document.addEventListener("DOMContentLoaded", () => {
    loadUnits();
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
        dropdown.value = units[0];
        loadUnit(units[0]);
    }

    dropdown.onchange = () => {
        loadUnit(dropdown.value);
    };
}

async function loadUnit(unitName) {
    const resp = await fetch(`/unit/${unitName}`);
    const data = await resp.json();

    currentUnitName = unitName;
    currentUnitQtags = data.qtags;
    currentUnitItems = data.items;

    populateQuestionDropdown(currentUnitQtags);
}


//
// ---------------------------
//  DISPLAY QUESTION
// ---------------------------
function displayQuestion(qtag) {
    console.log("Displaying question:", qtag);
    const qdata = currentUnitItems[qtag];

    // Update question text
    document.getElementById("question-text").textContent =
        qdata.question_text || "";

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

    // Restore grading UI from session state
    const explanationBox = document.getElementById("full-explanation-box");
    const feedbackBox = document.getElementById("feedback-box");
    const gradeStatus = document.getElementById("grade-status");
    const gradePoints = document.getElementById("grade-points");

    if (sessionData.explanation) {
        explanationBox.textContent = sessionData.explanation;
    } else {
        explanationBox.textContent = "Not yet graded. No explanation yet.";
    }

    if (sessionData.feedback) {
        feedbackBox.textContent = sessionData.feedback;
    } else {
        feedbackBox.textContent = "Not yet graded. No feedback yet.";
    }

    if (sessionData.grade_status) {
        gradeStatus.textContent = 
            sessionData.grade_status === "pass" ? "Correct" :
            sessionData.grade_status === "fail" ? "Incorrect" :
            sessionData.grade_status === "error" ? "Error" :
            sessionData.grade_status;
        gradeStatus.className = 
            sessionData.grade_status === "pass" ? "status-correct" :
            sessionData.grade_status === "fail" ? "status-incorrect" :
            sessionData.grade_status === "error" ? "status-error" :
            "status-not-graded";
    } else {
        gradeStatus.textContent = "";
        gradeStatus.className = "status-not-graded";
    }

    // Update grade points/optional display
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
//  DIVIDER DRAGGING
// ---------------------------
const divider = document.querySelector(".divider");
const topPanel = document.getElementById("question-panel");
const bottomPanel = document.getElementById("solution-panel");

let dragging = false;

divider.addEventListener("mousedown", () => {
    dragging = true;
    document.body.style.userSelect = "none";
});

document.addEventListener("mouseup", () => {
    dragging = false;
    document.body.style.userSelect = "";
});

document.addEventListener("mousemove", (e) => {
    if (!dragging) return;

    const containerHeight = divider.parentElement.offsetHeight;
    const newTopHeight = e.clientY - divider.parentElement.offsetTop;

    if (newTopHeight < 100 || newTopHeight > containerHeight - 100) return;

    topPanel.style.flex = `0 0 ${newTopHeight}px`;
    bottomPanel.style.flex = `1`;
});


//
// ---------------------------
//  QUESTION DROPDOWN
// ---------------------------
function populateQuestionDropdown(qtags) {
    const dropdown = document.getElementById("question-number");
    dropdown.innerHTML = "";

    qtags.forEach(qtag => {
        const opt = document.createElement("option");
        opt.value = qtag;
        opt.textContent = qtag;   // display qtag directly
        dropdown.appendChild(opt);
    });

    if (qtags.length > 0) {
        dropdown.value = qtags[0];
        displayQuestion(qtags[0]);
    }

    dropdown.onchange = () => {
        displayQuestion(dropdown.value);
    };

    // Add event listener to save student solution on input
    const solBox = document.getElementById("student-solution");
    solBox.addEventListener("input", () => {
        const qtag = dropdown.value;
        if (currentUnitName && qtag) {
            updateSessionData(currentUnitName, qtag, {
                student_solution: solBox.value
            });
        }
    });
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

    // Save grading results to session state
    updateSessionData(currentUnitName, qtag, {
        student_solution: studentSolution,
        feedback: data.feedback || "",
        explanation: data.full_explanation || "",
        grade_status: data.result || ""
    });
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