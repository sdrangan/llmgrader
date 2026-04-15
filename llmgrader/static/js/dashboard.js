// Dashboard JavaScript
const RESULTS_OUTPUT_SUMMARY = 'See detailed feedback for individual questions';

function getSessionPartResult(partData) {
    if (!partData) {
        return "";
    }
    return partData.result ?? partData.grade_status ?? "";
}

function getSessionPartExplanation(partData) {
    if (!partData) {
        return "";
    }
    return partData.full_explanation ?? partData.explanation ?? "";
}

function getQuestionTotalPoints(questionData) {
    const parts = questionData?.parts || [];
    return parts.reduce((sum, part) => {
        return sum + Number(part.points || 0);
    }, 0);
}

function getQuestionMaxPointsByPart(questionData) {
    const parts = questionData?.parts || [];
    const byPart = {};
    parts.forEach(part => {
        byPart[part.part_label] = Number(part.points || 0);
    });
    return byPart;
}

function getRequiredQtags(unitItems) {
    return Object.keys(unitItems || {}).filter(qtag => {
        const questionData = unitItems[qtag];
        return questionData && questionData.required !== false;
    });
}

function getRequiredAnsweredQtags(unitName, sessionState, unitItems) {
    const unitData = sessionState[unitName] || {};
    return getRequiredQtags(unitItems).filter(qtag => {
        const qdata = unitData[qtag];
        return qdata && qdata.parts && Object.keys(qdata.parts).length > 0;
    });
}

function buildQuestionResult(qtag, qdata, questionData = null) {
    const partMaxPoints = getQuestionMaxPointsByPart(questionData);
    const totalQuestionPoints = getQuestionTotalPoints(questionData);
    const parts = qdata?.parts || {};
    const allPart = parts.all || null;
    const otherPartLabels = (questionData?.parts || [])
        .map(part => part.part_label)
        .filter(partLabel => partLabel !== 'all');

    const scoreAll = Number(allPart?.points ?? 0);
    const scoreOther = otherPartLabels.reduce((sum, partLabel) => {
        return sum + Number(parts[partLabel]?.points ?? 0);
    }, 0);

    const allMaxScore = Number(allPart?.max_points ?? partMaxPoints.all ?? totalQuestionPoints);
    const otherMaxScore = otherPartLabels.reduce((sum, partLabel) => {
        return sum + Number(parts[partLabel]?.max_points ?? partMaxPoints[partLabel] ?? 0);
    }, 0);
    const fallbackMaxScore = allMaxScore || otherMaxScore || totalQuestionPoints;

    if (!qdata || Object.keys(parts).length === 0) {
        return {
            selectedPart: qdata?.selected_part || 'all',
            score: 0,
            maxScore: fallbackMaxScore,
            output: '',
            feedback: '',
            explanation: ''
        };
    }

    if (allPart && scoreAll >= scoreOther) {
        const outputLines = [
            `[all] Feedback: ${allPart.feedback ?? ''}`,
            `[all] Explanation: ${getSessionPartExplanation(allPart)}`
        ];

        return {
            selectedPart: 'all',
            score: scoreAll,
            maxScore: fallbackMaxScore,
            output: outputLines.join('\n'),
            feedback: allPart.feedback ?? '',
            explanation: getSessionPartExplanation(allPart)
        };
    }

    const outputLines = [];
    const feedbackBlocks = [];
    const explanationBlocks = [];

    otherPartLabels.forEach(partLabel => {
        const partData = parts[partLabel] || {};
        const feedback = partData.feedback ?? '';
        const explanation = getSessionPartExplanation(partData);

        outputLines.push(`[${partLabel}] Feedback: ${feedback}`);
        outputLines.push(`[${partLabel}] Explanation: ${explanation}`);
        feedbackBlocks.push(`[${partLabel}] ${feedback}`);
        explanationBlocks.push(`[${partLabel}] ${explanation}`);
    });

    return {
        selectedPart: qdata?.selected_part || otherPartLabels.join(', ') || 'all',
        score: scoreOther,
        maxScore: fallbackMaxScore,
        output: outputLines.join('\n'),
        feedback: feedbackBlocks.join('\n'),
        explanation: explanationBlocks.join('\n')
    };
}

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

function calculateQuestionStatus(unitName, qtag, questionData) {
    const sessionData = sessionState[unitName]?.[qtag];
    const totalPoints = getQuestionTotalPoints(questionData);

    let hasAttempts = false;
    if (sessionData && sessionData.parts) {
        hasAttempts = Object.keys(sessionData.parts).length > 0;
    }

    if (!sessionData || !sessionData.parts || Object.keys(sessionData.parts).length === 0) {
        return {
            completedParts: [],
            earnedPoints: 0,
            totalPoints: totalPoints,
            isComplete: false,
            hasAttempts: false
        };
    }

    const questionResult = buildQuestionResult(qtag, sessionData, questionData);
    const allPartData = sessionData.parts.all || null;
    const scoreAll = Number(allPartData?.points ?? 0);
    const otherPartLabels = (questionData.parts || [])
        .map(part => part.part_label)
        .filter(partLabel => partLabel !== 'all');
    const scoreOther = otherPartLabels.reduce((sum, partLabel) => {
        return sum + Number(sessionData.parts?.[partLabel]?.points ?? 0);
    }, 0);

    let completedPartsDisplay = [];
    if (allPartData && scoreAll >= scoreOther) {
        completedPartsDisplay = ['all'];
    } else {
        completedPartsDisplay = otherPartLabels.filter(partLabel => {
            const partData = sessionData.parts?.[partLabel];
            return Number(partData?.points ?? 0) > 0 || !!getSessionPartResult(partData);
        });
    }

    const earnedPoints = Number(questionResult.score ?? 0);
    const displayedTotalPoints = Number(questionResult.maxScore ?? totalPoints);

    console.log(`Status for ${qtag}: earned ${earnedPoints}/${displayedTotalPoints} points, completed parts: ${completedPartsDisplay.join(', ')}, has attempts: ${hasAttempts}`);

    return {
        completedParts: completedPartsDisplay,
        earnedPoints: earnedPoints,
        totalPoints: displayedTotalPoints,
        isComplete: earnedPoints === displayedTotalPoints && displayedTotalPoints > 0,
        hasAttempts: hasAttempts
    };
}

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

        let totalAllEarned = 0;
        let totalAllPossible = 0;
        let totalRequiredEarned = 0;
        let totalRequiredPossible = 0;
        let hasAnyAttempts = false;
        let hasAnyRequiredAttempts = false;

        data.qtags.forEach(qtag => {
            const questionData = data.items[qtag];
            const status = calculateQuestionStatus(unitName, qtag, questionData);
            const isRequired = questionData.required !== false;

            const row = document.createElement('tr');

            const qtagCell = document.createElement('td');
            qtagCell.textContent = qtag;
            row.appendChild(qtagCell);

            const requiredCell = document.createElement('td');
            requiredCell.textContent = questionData.required === false ? 'false' : 'true';
            row.appendChild(requiredCell);

            const completedCell = document.createElement('td');
            completedCell.textContent = status.completedParts.length > 0
                ? status.completedParts.join(', ')
                : '—';
            row.appendChild(completedCell);

            const pointsCell = document.createElement('td');
            pointsCell.textContent = `${status.earnedPoints}/${status.totalPoints}`;
            const pointsClass = getPointsClass(status.earnedPoints, status.totalPoints, status.hasAttempts);
            if (pointsClass) {
                pointsCell.classList.add(pointsClass);
            }
            row.appendChild(pointsCell);

            tableBody.appendChild(row);

            totalAllEarned += status.earnedPoints;
            totalAllPossible += status.totalPoints;
            if (status.hasAttempts) hasAnyAttempts = true;

            if (isRequired) {
                totalRequiredEarned += status.earnedPoints;
                totalRequiredPossible += status.totalPoints;
                if (status.hasAttempts) hasAnyRequiredAttempts = true;
            }
        });

        const totalAllCell = document.getElementById('total-all-points');
        totalAllCell.textContent = `${totalAllEarned}/${totalAllPossible}`;
        totalAllCell.className = getPointsClass(totalAllEarned, totalAllPossible, hasAnyAttempts);

        const totalRequiredCell = document.getElementById('total-required-points');
        totalRequiredCell.textContent = `${totalRequiredEarned}/${totalRequiredPossible}`;
        totalRequiredCell.className = getPointsClass(totalRequiredEarned, totalRequiredPossible, hasAnyRequiredAttempts);
    } catch (error) {
        console.error('Failed to load unit data:', error);
        const tableBody = document.getElementById('dashboard-table-body');
        tableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #f00;">Error loading data.</td></tr>';
    }
}

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

function buildResultsJson(unitName, sessionState, unitItems) {
    const qtags = getRequiredQtags(unitItems);
    const unitData = sessionState[unitName] || {};
    const tests = [];
    let totalScore = 0;

    qtags.forEach(qtag => {
        const qdata = unitData[qtag];
        const questionResult = buildQuestionResult(qtag, qdata, unitItems[qtag]);

        totalScore += Number(questionResult.score || 0);
        tests.push({
            name: qtag,
            score: questionResult.score,
            max_score: questionResult.maxScore,
            output: questionResult.output
        });
    });

    return {
        score: totalScore,
        output: RESULTS_OUTPUT_SUMMARY,
        tests: tests
    };
}

function buildResultsTxt(unitName, sessionState, unitItems) {
    const qtags = getRequiredQtags(unitItems);
    const unitData = sessionState[unitName] || {};
    const lines = [`Unit: ${unitName}`, ''];

    qtags.forEach((qtag, index) => {
        const qdata = unitData[qtag];
        const questionResult = buildQuestionResult(qtag, qdata, unitItems[qtag]);
        const selectedPart = qdata?.selected_part || questionResult.selectedPart || 'all';

        lines.push(`Question ${qtag} (selected part: ${selectedPart})`);
        lines.push(`Score: ${questionResult.score} / ${questionResult.maxScore}`);
        lines.push('');
        lines.push('Feedback:');
        lines.push(questionResult.feedback || '');
        lines.push('');
        lines.push('Explanation:');
        lines.push(questionResult.explanation || '');
        lines.push('');
        lines.push('----------------------------------------');

        if (index !== qtags.length - 1) {
            lines.push('');
        }
    });

    return lines.join('\n');
}

async function downloadSubmission() {
    const unitName = document.getElementById('unit-select').value;

    if (!unitName) {
        alert('Please select a unit first.');
        return;
    }

    try {
        const response = await fetch(`/unit/${unitName}`);
        const data = await response.json();
        if (!data.items) {
            alert('No question data found for this unit.');
            return;
        }

        const requiredAnsweredQtags = getRequiredAnsweredQtags(unitName, sessionState, data.items);
        if (requiredAnsweredQtags.length === 0) {
            alert(
                'You must answer at least one required question before downloading a submission.'
            );
            return;
        }

        const resultsJson = buildResultsJson(unitName, sessionState, data.items);
        const resultsTxt = buildResultsTxt(unitName, sessionState, data.items);

        const zip = new JSZip();
        zip.file('results.json', JSON.stringify(resultsJson, null, 2));
        zip.file('results.txt', resultsTxt);

        // Add solution images as separate files: images/<qtag>/<index>.<ext>
        const unitData = sessionState[unitName] || {};
        Object.keys(unitData).forEach(qtag => {
            const images = unitData[qtag]?.solution_images || [];
            images.forEach((dataUri, index) => {
                const match = dataUri.match(/^data:([^;]+);base64,(.+)$/);
                if (!match) return;
                const mimeType = match[1];
                const b64data = match[2];
                const ext = mimeType.split('/')[1] || 'png';
                zip.file(`images/${qtag}/${index}.${ext}`, b64data, { base64: true });
            });
        });

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

