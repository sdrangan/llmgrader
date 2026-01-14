console.log("UI loaded.");

//
// GLOBAL STATE
//
let currentUnitQtags = [];          // list of qtags
let currentUnitItems = {};          // dict: qtag -> question object
let currentUnitName = null;         // current unit name
let currentStudentSolutions = {};   // dict: qtag -> student solution

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

    // Update student solution
    const solBox = document.getElementById("student-solution");
    solBox.value = currentStudentSolutions[qtag]?.solution || "";

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

    // Reset grading UI
    document.getElementById("full-explanation-box").textContent =
        "Not yet graded. No explanation yet.";
    document.getElementById("feedback-box").textContent =
        "Not yet graded. No feedback yet.";
    document.getElementById("grade-status").className = "status-not-graded";
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
    document.getElementById("full-explanation-box").textContent =
        data.full_explanation;
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