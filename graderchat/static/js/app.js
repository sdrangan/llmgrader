console.log("UI loaded.");

//
// GLOBAL STATE
//
let currentUnitQuestions = null;     // plain text
let currentUnitQuestionsLatex = null; // latex version
let currentUnitSolutions = null;     // reference solutions
let currentUnitNotes = null;         // grading notes
let currentUnitName = null;          // current unit name
let currentStudentSolutions = null; // student solutions
let currentPartLabels = [];       // part labels for current unit

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

        // Store student solutions
        currentStudentSolutions = data.solutions;

        // If the unit is already loaded, update the student solution box
        const qIdx = Number(document.getElementById("question-number").value);
        document.getElementById("student-solution").value =
            currentStudentSolutions[qIdx] || "Not loaded";
    });
};


// ---------------------------
//  OpenAI KEY MANAGEMENT
// ---------------------------
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("apiKeyInput");
    const saveBtn = document.getElementById("saveKeyBtn");

    // Preload saved key
    const saved = localStorage.getItem("openai_api_key");
    if (saved) input.value = saved;

    // Save key on click
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

    // When user selects a different unit
    dropdown.onchange = () => {
        loadUnit(dropdown.value);
    };
}

async function loadUnit(unitName) {
    const resp = await fetch(`/unit/${unitName}`);
    const data = await resp.json();

    // Store everything the backend sends
    currentUnitQuestions = data.questions_text;     // plain text
    currentUnitQuestionsLatex = data.questions_latex; // latex version
    currentUnitSolutions = data.solutions;          // reference solutions
    currentUnitNotes = data.grading;                // grading notes
    currentPartLabels = data.part_labels;          // part labels
    currentUnitName = unitName;

    populateQuestionDropdown(currentUnitQuestions);
}



//
// ---------------------------
//  DISPLAY QUESTION
// ---------------------------
function displayQuestion(idx) {
    // Update question text
    const qText = currentUnitQuestions[idx];
    document.getElementById("question-text").textContent = qText;

    // Update student solution text
    const solBox = document.getElementById("student-solution");
    if (currentStudentSolutions) {
        solBox.value = currentStudentSolutions[idx] || "";
    } else {
        solBox.value = "";
    }

    // ---------------------------
    // Update PART DROPDOWN
    // ---------------------------
    const partSelect = document.getElementById("part-select");
    const parts = currentPartLabels[idx] || [];

    // Clear old options
    partSelect.innerHTML = "";

    if (parts.length === 0) {
        // No parts → only "All"
        const opt = document.createElement("option");
        opt.value = "all";
        opt.textContent = "All";
        partSelect.appendChild(opt);
    } else {
        // Insert "All" first
        const optAll = document.createElement("option");
        optAll.value = "all";
        optAll.textContent = "All";
        partSelect.appendChild(optAll);

        // Insert each part label
        parts.forEach(label => {
            const opt = document.createElement("option");
            opt.value = label;
            opt.textContent = label;
            partSelect.appendChild(opt);
        });
    }


    // Reset grading UI
    document.getElementById("full-explanation-box").textContent = "Not yet graded.  No explanation yet.";
    document.getElementById("feedback-box").textContent = "Not yet graded. No feedback yet.";
    document.getElementById("grade-status").className = "status-not-graded";
}


// ---------------------------
//  DIVIDER DRAGGING
// ---------------------------

const divider = document.querySelector(".divider");
const topPanel = document.getElementById("question-panel");
const bottomPanel = document.getElementById("solution-panel");

let dragging = false;

divider.addEventListener("mousedown", () => dragging = true);
document.addEventListener("mouseup", () => dragging = false);

document.addEventListener("mousemove", (e) => {
    if (!dragging) return;

    const containerHeight = divider.parentElement.offsetHeight;
    const newTopHeight = e.clientY - divider.parentElement.offsetTop;

    if (newTopHeight < 100 || newTopHeight > containerHeight - 100) return;

    topPanel.style.flex = `0 0 ${newTopHeight}px`;
    bottomPanel.style.flex = `1`;
});


divider.addEventListener("mousedown", () => {
    dragging = true;
    document.body.style.userSelect = "none";
});

document.addEventListener("mouseup", () => {
    dragging = false;
    document.body.style.userSelect = "";
});




//
// ---------------------------
//  QUESTION DROPDOWN
// ---------------------------
function populateQuestionDropdown(questions) {
    const dropdown = document.getElementById("question-number");
    dropdown.innerHTML = "";

    questions.forEach((q, idx) => {
        const opt = document.createElement("option");
        opt.value = idx;
        opt.textContent = `Question ${idx + 1}`;
        dropdown.appendChild(opt);
    });

    if (questions.length > 0) {
        dropdown.value = 0;
        displayQuestion(0);
    }

    dropdown.onchange = () => {
        displayQuestion(Number(dropdown.value));
    };
}

// ---------------------------
//  QUESTION DROPDOWN HANDLER
// ---------------------------
document.getElementById("question-number").addEventListener("change", () => {
    const idx = Number(document.getElementById("question-number").value);
    displayQuestion(idx);
});

// ---------------------------
//  GRADE CURRENT QUESTION
// ---------------------------
async function gradeCurrentQuestion() {
    const idx = Number(document.getElementById("question-number").value);
    const studentSolution = document.getElementById("student-solution").value;
    const partSelect = document.getElementById("part-select");
    const selectedPart = partSelect.value;   // "all", "a", "b", ...
    const apiKey = getApiKey();

    if (!apiKey) {
        alert("Please set your OpenAI API key first.");
        return;
    }

    const gradeBtn = document.getElementById("grade-button");
    gradeBtn.disabled = true;
    gradeBtn.textContent = "Grading...";

    const model = document.getElementById("model-select").value;

    console.log('API Key being used:', apiKey);
    const resp = await fetch("/grade", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            unit: currentUnitName,
            question_idx: idx,
            student_solution: studentSolution,
            part_label: selectedPart,
            model: model,
            api_key: apiKey
        })
    });
    const data = await resp.json();  

    
    gradeBtn.disabled = false;
    gradeBtn.textContent = "Grade";


    document.getElementById("grade-status").textContent =
        data.result === "pass" ? "Correct" :
        data.result === "fail" ? "Incorrect" :
        "Error";

    document.getElementById("grade-status").className =
        data.result === "pass" ? "status-correct" :
        data.result === "fail" ? "status-incorrect" :
        "status-error";

    document.getElementById("feedback-box").textContent = data.feedback;
    document.getElementById("full-explanation-box").textContent = data.full_explanation;
}

// ---------------------------
// Unit Reloading
// ---------------------------
async function reloadUnitData() {
    console.log("Reloading all units...");

    const res = await fetch("/reload", { method: "POST" });
    const data = await res.json();

    if (data.status === "ok") {
        console.log("Units reloaded.");

        // Refresh the unit dropdown
        await loadUnits();

        // Re-load the currently selected unit
        const unitName = document.getElementById("unit-select").value;
        if (unitName) {
            await loadUnit(unitName);
        }
    }
}



