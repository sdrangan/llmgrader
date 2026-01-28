console.log("UI loaded.");

//
// GLOBAL STATE
//
let currentUnitQtags = [];          // list of qtags
let currentUnitItems = {};          // dict: qtag -> question object
let currentUnitName = null;         // current unit name
let currentStudentSolutions = {};   // dict: qtag -> student solution

// sessionState[unitName][qtag] = {
//     student_solution: "...",
//     parts: {
//         [part_label]: { feedback: "", explanation: "", grade_status: "" }
//     }
// }
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

    const providerSelect = document.getElementById("providerSelect");

    const modelSelect = document.getElementById("model-select");
    const modelInput = document.getElementById("model-input");
    const modelSelectContainer = document.getElementById("model-select-container");
    const modelInputContainer = document.getElementById("model-input-container");

    // Load saved provider and key
    const savedProvider = localStorage.getItem("llm_provider");
    if (savedProvider) providerSelect.value = savedProvider;

    const savedKey = localStorage.getItem("llm_api_key");
    if (savedKey) input.value = savedKey;

    // Load saved model (either from select or custom input)
    const savedModel = localStorage.getItem("llm_model");
    if (savedModel) {
        // If savedModel matches one of the options, select it, else populate custom input
        let matched = false;
        if (modelSelect) {
            for (let i = 0; i < modelSelect.options.length; i++) {
                if (modelSelect.options[i].value === savedModel) {
                    modelSelect.value = savedModel;
                    matched = true;
                    break;
                }
            }
        }
        if (!matched && modelInput) {
            modelInput.value = savedModel;
        }
    }

    // Initialize model input/select visibility based on provider
    function updateModelVisibility(provider) {
        if (provider === 'openai') {
            if (modelSelectContainer) modelSelectContainer.style.display = '';
            if (modelInputContainer) modelInputContainer.style.display = '';
        } else {
            // For non-OpenAI providers hide GPT dropdown and show custom input
            if (modelSelectContainer) modelSelectContainer.style.display = 'none';
            if (modelInputContainer) modelInputContainer.style.display = '';
        }
    }

    updateModelVisibility(providerSelect.value);

    // When provider changes, persist and update visibility
    providerSelect.addEventListener('change', (e) => {
        const prov = e.target.value;
        localStorage.setItem("llm_provider", prov);
        updateModelVisibility(prov);
    });

    // Sync model select -> custom input and persist
    if (modelSelect) {
        modelSelect.addEventListener('change', (e) => {
            const v = e.target.value;
            if (modelInput) modelInput.value = v;
            localStorage.setItem("llm_model", v);
        });
    }

    // Persist custom model input
    if (modelInput) {
        modelInput.addEventListener('input', (e) => {
            localStorage.setItem("llm_model", e.target.value.trim());
        });
    }

    saveBtn.addEventListener("click", () => {
        const key = input.value.trim();
        const prov = providerSelect.value;
        if (prov) {
            localStorage.setItem("llm_provider", prov);
        }
        if (key) {
            localStorage.setItem("llm_api_key", key);
            alert("API key and provider saved in your browser.");
        } else {
            alert("Provider saved.");
        }
    });
});

function getApiKey() {
    return localStorage.getItem("llm_api_key") || "";
}

function getProvider() {
    // prefer session selection in UI, else stored provider
    const provEl = document.getElementById("providerSelect");
    if (provEl && provEl.value) return provEl.value;
    return localStorage.getItem("llm_provider") || "openai";
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
        // Check if there's a saved unit selection
        const savedUnit = sessionStorage.getItem("selectedUnit");
        if (savedUnit && units.includes(savedUnit)) {
            dropdown.value = savedUnit;
            loadUnit(savedUnit);
        } else {
            dropdown.value = units[0];
            loadUnit(units[0]);
        }
    }

    dropdown.onchange = () => {
        sessionStorage.setItem("selectedUnit", dropdown.value);
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

    populateQuestionDropdown(currentUnitQtags);
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
    console.log("Displaying question:", qtag);
    const qdata = currentUnitItems[qtag];

    // Update question text
    document.getElementById("question-text").innerHTML =
        qdata.question_text || "";
    
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
            // Save student solution at qtag level (not per-part)
            updateSessionData(currentUnitName, qtag, {
                student_solution: solBox.value
            }, null);
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
    const provider = getProvider();
    if (!apiKey) {
        alert("Please set your API key first.");
        return;
    }

    const timeout = Number(document.getElementById("timeout-input").value);

    const gradeBtn = document.getElementById("grade-button");
    gradeBtn.disabled = true;
    gradeBtn.textContent = "Grading...";

    // prefer custom model input if populated, else selected model
    const modelInputVal = (document.getElementById("model-input") || {}).value || "";
    const modelSelectVal = (document.getElementById("model-select") || {}).value || "";
    const model = modelInputVal.trim() || modelSelectVal;

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
            provider: provider,
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