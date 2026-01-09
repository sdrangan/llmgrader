console.log("UI loaded.");

//
// GLOBAL STATE
//
let currentUnitQuestions = null;     // plain text
let currentUnitQuestionsLatex = null; // latex version
let currentUnitSolutions = null;     // reference solutions
let currentUnitNotes = null;         // grading notes
//
// ---------------------------
//  CHAT SEND BUTTON
// ---------------------------
document.getElementById("send-chat").onclick = function () {
    const input = document.getElementById("chat-input");
    const history = document.getElementById("chat-history");

    if (input.value.trim() !== "") {
        const msg = document.createElement("div");
        msg.textContent = "You: " + input.value;
        history.appendChild(msg);
        input.value = "";
        history.scrollTop = history.scrollHeight;
    }
};


//
// ---------------------------
//  GRADE BUTTON (dummy for now)
// ---------------------------
document.getElementById("grade-button").onclick = function () {
    const status = document.getElementById("grade-status");

    if (status.classList.contains("status-not-graded")) {
        status.textContent = "Correct";
        status.className = "status-correct";
    } else if (status.classList.contains("status-correct")) {
        status.textContent = "Incorrect";
        status.className = "status-incorrect";
    } else {
        status.textContent = "Not graded";
        status.className = "status-not-graded";
    }
};


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
        currentStudentSolutions = data.questions;

        // If the unit is already loaded, update the student solution box
        const qIdx = Number(document.getElementById("question-number").value);
        document.getElementById("student-solution").value =
            currentStudentSolutions[qIdx] || "Not loaded";
    });
};


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

    // Reset grading UI
    document.getElementById("explanation").textContent = "No explanation yet.";
    document.getElementById("grade-status").textContent = "Not graded";
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


