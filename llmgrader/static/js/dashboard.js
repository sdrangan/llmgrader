// Dashboard JavaScript
function initializeDashboardView() {
    const downloadBtn = document.getElementById("download-submission-btn");
    if (downloadBtn) {
        downloadBtn.addEventListener("click", downloadSubmission);
    }

    const unitName = document.getElementById("unit-select").value;
    if (unitName) {
        loadDashboardUnit(unitName);
    }
}

// Calculate points and completed parts for a question
function calculateQuestionStatus(unitName, qtag, questionData) {
    const sessionData = sessionState[unitName]?.[qtag];
    const parts = questionData.parts || [];
    
    // Calculate total points
    const totalPoints = parts.reduce((sum, part) => {
        return sum + parseInt(part.points || 0, 10);
    }, 0);
    
    // Check if any grading was attempted
    let hasAttempts = false;
    if (sessionData && sessionData.parts) {
        hasAttempts = Object.keys(sessionData.parts).length > 0;
    }
    
    if (!sessionData || !sessionData.parts) {
        return {
            completedParts: [],
            earnedPoints: 0,
            totalPoints: totalPoints,
            isComplete: false,
            hasAttempts: false
        };
    }
    
    // Check which parts are correct
    const correctParts = [];
    let earnedFromIndividual = 0;
    
    parts.forEach(part => {
        const partLabel = part.part_label;
        const partData = sessionData.parts[partLabel];
        
        if (partData && partData.grade_status === "pass") {
            correctParts.push(partLabel);
            earnedFromIndividual += parseInt(part.points || 0, 10);
        }
    });
    
    // Check if "all" was graded correct
    let earnedFromAll = 0;
    const allPartData = sessionData.parts["all"];
    if (allPartData && allPartData.grade_status === "pass") {
        earnedFromAll = totalPoints;
    }
    
    // Final earned points is the maximum
    const earnedPoints = Math.max(earnedFromIndividual, earnedFromAll);
    
    // Determine completed parts display
    let completedPartsDisplay = [];
    if (earnedFromAll === totalPoints) {
        completedPartsDisplay = ["all"];
    } else if (correctParts.length === parts.length && parts.length > 0) {
        completedPartsDisplay = ["all"];
    } else {
        completedPartsDisplay = correctParts;
    }

    console.log(`Status for ${qtag}: earned ${earnedPoints}/${totalPoints} points, completed parts: ${completedPartsDisplay.join(", ")}, has attempts: ${hasAttempts}`);
    
    return {
        completedParts: completedPartsDisplay,
        earnedPoints: earnedPoints,
        totalPoints: totalPoints,
        isComplete: earnedPoints === totalPoints && totalPoints > 0,
        hasAttempts: hasAttempts
    };
}

// Get CSS class for points cell based on earned/total/attempts
function getPointsClass(earnedPoints, totalPoints, hasAttempts) {
    if (earnedPoints === 0 && !hasAttempts) {
        return 'points-none';
    } else if (earnedPoints === 0 && hasAttempts) {
        return 'points-attempted-zero';
    } else if (earnedPoints > 0 && earnedPoints < totalPoints) {
        return 'points-partial';
    } else if (earnedPoints === totalPoints && totalPoints > 0) {
        return 'points-full';
    }
    return '';
}

// Load and display unit data in the table
async function loadDashboardUnit(unitName) {
    if (!unitName) return;
    
    try {
        const response = await fetch(`/unit/${unitName}`);
        const data = await response.json();
        
        const tableBody = document.getElementById('dashboard-table-body');
        tableBody.innerHTML = '';
        
        if (!data.qtags || data.qtags.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #888;">No questions in this unit.</td></tr>';
            document.getElementById('total-all-points').textContent = '0/0';
            document.getElementById('total-all-points').className = 'points-none';
            document.getElementById('total-required-points').textContent = '0/0';
            document.getElementById('total-required-points').className = 'points-none';
            return;
        }
        
        // Track totals
        let totalAllEarned = 0;
        let totalAllPossible = 0;
        let totalRequiredEarned = 0;
        let totalRequiredPossible = 0;
        let hasAnyAttempts = false;
        let hasAnyRequiredAttempts = false;
        
        // Build table rows
        data.qtags.forEach(qtag => {
            const questionData = data.items[qtag];
            const status = calculateQuestionStatus(unitName, qtag, questionData);
            const isRequired = questionData.grade === true;
            
            const row = document.createElement('tr');
            
            // Question column
            const qtagCell = document.createElement('td');
            qtagCell.textContent = qtag;
            row.appendChild(qtagCell);
            
            // Required column
            const requiredCell = document.createElement('td');
            requiredCell.textContent = questionData.grade ? 'true' : 'false';
            row.appendChild(requiredCell);
            
            // Completed Parts column
            const completedCell = document.createElement('td');
            completedCell.textContent = status.completedParts.length > 0 
                ? status.completedParts.join(', ') 
                : '—';
            row.appendChild(completedCell);
            
            // Points column
            const pointsCell = document.createElement('td');
            pointsCell.textContent = `${status.earnedPoints}/${status.totalPoints}`;
            const pointsClass = getPointsClass(status.earnedPoints, status.totalPoints, status.hasAttempts);
            if (pointsClass) {
                pointsCell.classList.add(pointsClass);
            }
            row.appendChild(pointsCell);
            
            tableBody.appendChild(row);
            
            // Update totals
            totalAllEarned += status.earnedPoints;
            totalAllPossible += status.totalPoints;
            if (status.hasAttempts) hasAnyAttempts = true;
            
            if (isRequired) {
                totalRequiredEarned += status.earnedPoints;
                totalRequiredPossible += status.totalPoints;
                if (status.hasAttempts) hasAnyRequiredAttempts = true;
            }
        });
        
        // Update total row
        const totalAllCell = document.getElementById('total-all-points');
        totalAllCell.textContent = `${totalAllEarned}/${totalAllPossible}`;
        totalAllCell.className = getPointsClass(totalAllEarned, totalAllPossible, hasAnyAttempts);
        
        // Update required total row
        const totalRequiredCell = document.getElementById('total-required-points');
        totalRequiredCell.textContent = `${totalRequiredEarned}/${totalRequiredPossible}`;
        totalRequiredCell.className = getPointsClass(totalRequiredEarned, totalRequiredPossible, hasAnyRequiredAttempts);
        
    } catch (error) {
        console.error('Failed to load unit data:', error);
        const tableBody = document.getElementById('dashboard-table-body');
        tableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #f00;">Error loading data.</td></tr>';
    }
}

// Wrap text to specified column width
function wrapText(text, width = 80) {
    if (!text) return '';
    
    const words = text.split(/\s+/);
    const lines = [];
    let currentLine = '';
    
    words.forEach(word => {
        if ((currentLine + ' ' + word).length <= width) {
            currentLine = currentLine ? currentLine + ' ' + word : word;
        } else {
            if (currentLine) lines.push(currentLine);
            currentLine = word;
        }
    });
    
    if (currentLine) lines.push(currentLine);
    return lines.join('\n');
}

// Generate human-readable text for submission
function generateSubmissionText(unitName, unitData, questionDataMap) {
    const lines = [];
    lines.push(`Submission for Unit: ${unitName}`);
    lines.push('='.repeat(80));
    lines.push('');
    
    // Get required questions only
    const requiredQtags = Object.keys(unitData).filter(qtag => {
        const questionData = questionDataMap[qtag];
        return questionData && questionData.grade === true;
    });
    
    if (requiredQtags.length === 0) {
        lines.push('No required questions in this unit.');
        return lines.join('\n');
    }
    
    requiredQtags.forEach(qtag => {
        const questionData = questionDataMap[qtag];
        const sessionData = unitData[qtag];
        const status = calculateQuestionStatus(unitName, qtag, questionData);
        
        lines.push(`Question (${qtag})`);
        lines.push('-'.repeat(80));
        lines.push(`Points total: ${status.earnedPoints}/${status.totalPoints}`);
        lines.push('');
        
        // Student solution - preserve original formatting
        lines.push('Solution:');
        if (sessionData.student_solution) {
            lines.push(sessionData.student_solution);
        } else {
            lines.push('(No solution provided)');
        }
        lines.push('');
        
        // Parts
        if (sessionData.parts) {
            const partLabels = Object.keys(sessionData.parts);
            partLabels.forEach(partLabel => {
                const partData = sessionData.parts[partLabel];
                lines.push(`Part '${partLabel}'`);
                
                // Grade status
                let gradeStatus = 'ungraded';
                if (partData.grade_status === 'pass') {
                    gradeStatus = 'correct';
                } else if (partData.grade_status === 'fail') {
                    gradeStatus = 'incorrect';
                } else if (partData.grade_status) {
                    gradeStatus = partData.grade_status;
                }
                lines.push(`Grade status: ${gradeStatus}`);
                
                // Feedback
                lines.push('Feedback:');
                if (partData.feedback) {
                    lines.push(wrapText(partData.feedback));
                } else {
                    lines.push('');
                }
                lines.push('');
                
                // Explanation
                lines.push('Explanation:');
                if (partData.explanation) {
                    lines.push(wrapText(partData.explanation));
                } else {
                    lines.push('');
                }
                lines.push('');
            });
        }
        
        lines.push('');
    });
    
    return lines.join('\n');
}

// Download submission as zip
async function downloadSubmission() {
    const unitName = document.getElementById('unit-select').value;
    
    if (!unitName) {
        alert('Please select a unit first.');
        return;
    }
    
    const unitData = sessionState[unitName] || {};
     
    // Fetch unit data to get question metadata
    try {
        const response = await fetch(`/unit/${unitName}`);
        const data = await response.json(); 
        if (!data.items) {
            alert('No question data found for this unit.');
            return;
        }
        
        // Filter for required questions only
        const requiredQtags = Object.keys(unitData).filter(qtag => {
            const questionData = data.items[qtag];
            return questionData && questionData.grade === true;
        });
        
        if (requiredQtags.length === 0) {
            alert(
                'You must answer at least one required question before downloading a submission.'
            );
            return;
        }
        
        // Create filtered JSON with only required questions
        const filteredData = {};
        requiredQtags.forEach(qtag => {
            filteredData[qtag] = unitData[qtag];
        });
        
        // Generate JSON string
        const jsonString = JSON.stringify(filteredData, null, 2);
        
        // Generate text file
        const textContent = generateSubmissionText(unitName, filteredData, data.items);
        
        // Create zip file using JSZip
        const zip = new JSZip();
        zip.file(`submission_${unitName}.json`, jsonString);
        zip.file(`submission_${unitName}.txt`, textContent);
        
        // Generate zip and download
        const zipBlob = await zip.generateAsync({ type: 'blob' });
        const url = URL.createObjectURL(zipBlob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `submission_${unitName}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        console.log(`Downloaded submission for unit: ${unitName}`);
    } catch (error) {
        console.error('Failed to generate submission:', error);
        alert('Failed to generate submission. Please try again.');
    }
}

