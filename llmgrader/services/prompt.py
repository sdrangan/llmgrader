import textwrap


PROMPT_PREAMBLE = textwrap.dedent(
    """
    Your task is to grade a student's solution to an engineering problem.

    You will be given:
    - HTML version of the question,
    - HTML version of a correct reference solution,
    - Plain text grading notes, and
    - Plain text student solution.

    Return only the fields explicitly requested below.
    The backend will compute derived fields such as max_point_parts, max_points,
    aggregate result, aggregate points, and any fields not explicitly requested.
    Text fields such as "full_explanation" and "feedback" may use Markdown,
    including paragraphs, lists, and tables.
    """
)


JSON_REQUIREMENT = textwrap.dedent(
    """
    Important rules:
    - Return only the requested fields.
    - Do not include any extra fields, labels, maximum-point values, or computed totals.
    - Return exactly one valid JSON object and nothing else. Do not include code fences, markdown, comments, explanations, or any text before or after the JSON object.
    """
).strip()


NO_RUBRIC_TEMPLATES = {
    "partial_multi_all": """
        You must return a JSON object with the following fields:

        - "point_parts": a list of numeric values, one for each part, in the exact order above.
        Each point value must be between 0 and the maximum points for that part.
        - "full_explanation": a detailed explanation of your grading reasoning.
        - "feedback": concise (up to 5 sentences, unless otherwise specified in the grading notes),
        student-facing guidance that helps the student improve without revealing the reference solution or grading notes.

        Follow these steps:

        1. For each part, carefully identify the student's answer for that part. Students may
        write answers out of order or embed multiple parts together. Use your judgment to
        isolate the portion corresponding to each part.
        2. Compare the student's work for each part to the corresponding part in the reference
        solution, using the grading notes as guidance.
        3. In "full_explanation", explain your reasoning step by step, describing what is correct
        and what is incorrect for each part.
        4. Based on your reasoning and the grading notes, assign a numeric score to each part,
        between 0 and that part's maximum points. Place these point values in the "point_parts" list in
        the exact order given above.
        5. In "feedback", provide concise, student-facing guidance that helps the student improve,
        without revealing the reference solution or grading notes.

        {json_requirement}
    """,
    "partial_multi_single": """
        You must return a JSON object with the following fields:

        - "points": the numeric points for this part, between 0 and {max_points_part}.
        - "full_explanation": a detailed explanation of your grading reasoning for this part.
        - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
        student improve without revealing the reference solution or grading notes.

        Follow these steps:

        1. Extract the student's answer for part ({part_label}) from the student solution.
        Students may write answers out of order or embed multiple parts together. Use your
        judgment to isolate the portion corresponding to part ({part_label}).
        2. Compare the student's solution for part ({part_label}) to the corresponding part in the
        reference solution, using the grading notes as guidance.
        3. In "full_explanation", work through your reasoning step by step, explaining what is
        correct and what is incorrect.
        4. Based on your reasoning and the grading notes, decide how many points (from 0 to
        {max_points_part}) the student earns for this part and set "points" to that numeric value.
        5. In "feedback", provide concise, student-facing guidance that helps the student improve,
        without revealing the reference solution or grading notes.

        {json_requirement}
    """,
    "partial_single": """
        You must return a JSON object with the following fields:

        - "points": the numeric points for this question, between 0 and {max_points_part}.
        - "full_explanation": a detailed explanation of your grading reasoning.
        - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
        student improve without revealing the reference solution or grading notes.

        Follow these steps:

        1. Read the student's solution carefully.
        2. Compare the student's solution to the reference solution, using the grading notes as guidance.
        3. In "full_explanation", work through your reasoning step by step, explaining what is
        correct and what is incorrect.
        4. Based on your reasoning and the grading notes, decide how many points (from 0 to
        {max_points_part}) the student earns and set "points" to that numeric value.
        5. In "feedback", provide concise, student-facing guidance that helps the student improve,
        without revealing the reference solution or grading notes.

        {json_requirement}
    """,
    "binary_multi_all": """
        This question is configured for binary grading (no partial credit).

        You must return a JSON object with the following fields:

        - "result_parts": a list with one value for each part, in the same order as the parts above.
        Each value must be one of "pass", "fail", or "error".
        - "full_explanation": a detailed explanation of your grading reasoning.
        - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
        student improve without revealing the reference solution or grading notes.

        Follow these steps:

        1. For each part, carefully identify the student's answer for that part. Students may
        write answers out of order or embed multiple parts together. Use your judgment to
        isolate the portion corresponding to each part.
        2. Compare the student's work for each part to the corresponding part in the reference
        solution, using the grading notes as guidance.
        3. In "full_explanation", work through your reasoning step by step, explaining what is
        correct and what is incorrect for each part.
        4. After you have completed your reasoning, decide the correctness of each part and place
        the corresponding values in "result_parts" in the exact part order above.
        5. In "feedback", provide concise, student-facing guidance that helps the student improve,
        without revealing the reference solution or grading notes.

        {json_requirement}
    """,
    "binary_multi_single": """
        You must return a JSON object with the following fields:

        - "result": "pass", "fail", or "error"
        - "full_explanation": a detailed explanation of your grading reasoning for this part.
        - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
        student improve without revealing the reference solution or grading notes.

        Follow these steps:

        1. Extract the student's answer for part ({part_label}) from the student solution.
        Students may write answers out of order or embed multiple parts together. Use your
        judgment to isolate the portion corresponding to part ({part_label}).
        2. Compare the student's solution for part ({part_label}) to the corresponding part in the
        reference solution, using the grading notes as guidance.
        3. In "full_explanation", work through your reasoning step by step, explaining what is
        correct and what is incorrect.
        4. After you have completed your reasoning, decide the correctness for this part:
        - If the solution is correct, set "result" to "pass".
        - If the solution is incorrect, set "result" to "fail".
        - If you cannot grade due to missing or inconsistent information, set "result" to "error".
        5. In "feedback", provide concise, student-facing guidance that helps the student improve,
        without revealing the reference solution or grading notes.

        {json_requirement}
    """,
    "binary_single": """
        This question is configured for binary grading (no partial credit).

        You must return a JSON object with the following fields:

        - "result": "pass", "fail", or "error"
        - "full_explanation": a detailed explanation of your grading reasoning.
        - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
        student improve without revealing the reference solution or grading notes.

        Follow these steps:

        1. Read the student's solution carefully.
        2. Compare the student's solution to the reference solution, using the grading notes as guidance.
        3. In "full_explanation", work through your reasoning step by step, explaining what is
        correct and what is incorrect.
        4. After you have completed your reasoning, decide the overall correctness:
        - If the solution is correct, set "result" to "pass".
        - If the solution is incorrect, set "result" to "fail".
        - If you cannot grade due to missing or inconsistent information, set "result" to "error".
        5. In "feedback", provide concise, student-facing guidance that helps the student improve,
        without revealing the reference solution or grading notes.

        {json_requirement}
    """,
}


RUBRIC_TEMPLATES = {
    "partial_multi_all": """
        This question allows partial credit. It has multiple parts.
        Grade the student using the rubric items below as the primary scoring guide.

        The parts and their maximum points are:
        {part_points_block}

        Rubric items:
        {rubric_items_block}

        Rubric groups:
        {rubric_groups_block}

        Group semantics:
        - A group with type "one_of" means at most one rubric item in that group should contribute points.
        - If more than one item in a "one_of" group appears applicable, choose the single best-supported item and set the others to 0.0.

        Scoring guidance:
        - Evaluate every rubric item exactly once and respect the rubric item's listed "part" field.
        - A rubric item attached to a specific part should affect only that part's score.
        - A rubric item attached to part "all" may reflect work that spans multiple parts; when that happens, allocate its effect across the relevant part scores in the most defensible way.
        - Do not count the same evidence twice. If two rubric items are triggered by the same underlying mistake or the same underlying success, award both only if the rubric items clearly measure distinct requirements. Otherwise, apply only the most specific or best-supported rubric item and set the overlapping item to 0.0.
        - If the condition is met and point_adjustment > 0, set "point_awarded" to a numeric value between 0 and point_adjustment.
        - If the condition is met and point_adjustment < 0, set "point_awarded" to point_adjustment exactly (that is, a negative adjustment).
        - If the condition is not met, set "point_awarded" to 0.0.
        - Use the rubric items as the primary scoring mechanism.
        - Overall total rule: {rubric_total_rule}
        - Because you must return per-part scores, ensure the sum of "point_parts" is consistent with the rubric evaluation and your explanation.
        - If the rubric does not fully resolve the score distribution, use the grading notes and explain the judgment clearly.

        You must return a JSON object with the following fields:

        - "point_parts": a list of numeric values, one for each part, in the exact order listed above.
        Each point value must be between 0 and that part's maximum points.
        - "rubric_eval": an object keyed by rubric id.
        For each rubric id, return an object with:
          - "evidence": concise factual evidence from the student's solution explaining whether the rubric condition is met. This text may be shown to the student, so it should be clear and professional, but your grading decision must still be based on comparison to the reference solution and grading notes.
          - "point_awarded": the numeric adjustment awarded for that rubric item, following the scoring guidance above.
        - "full_explanation": a concise grading summary that explains the per-part scoring at a high level. Do not repeat the full per-rubric detail already captured in "rubric_eval".
        - "feedback": concise (up to 5 sentences, unless otherwise specified in the grading notes), student-facing guidance derived from the rubric evaluation and focused on the most important strengths or mistakes that affected the score.

        Follow these steps:

        1. For each part, identify the student's answer for that part. Students may write answers out of order or embed multiple parts together. Use your judgment to isolate the relevant work.
        2. Compare the student's work for each part to the corresponding part in the reference solution, using the grading notes as guidance.
        3. Evaluate each rubric item against the student's work and record concise evidence in "rubric_eval".
        4. Before finalizing awards, check for overlapping rubric items that rely on the same evidence. Do not double count the same underlying mistake or success unless the rubric items clearly refer to distinct criteria.
        5. Apply the rubric groups before deciding the awarded adjustments, especially any "one_of" groups.
        6. Determine the numeric score for each part and place those values in "point_parts" in the exact order listed above. Make the total across all parts consistent with this rule: {rubric_total_step}.
        7. In "full_explanation", summarize the overall grading judgment briefly, emphasizing the part-level outcomes and the major rubric findings without restating every rubric item.
        8. In "feedback", give concise, student-facing guidance that is consistent with the rubric evaluation, emphasizes the main reasons for the score, and does not reveal the reference solution or hidden grading notes.

        {json_requirement}
    """,
    "partial_multi_single": """
        This question allows partial credit. It has multiple parts, and you are grading only part ({part_label}).
        Grade the student using the rubric items below as the primary scoring guide.

        The maximum points for part ({part_label}) is {max_points_part} points.

        Rubric items:
        {rubric_items_block}

        Rubric groups:
        {rubric_groups_block}

        Group semantics:
        - A group with type "one_of" means at most one rubric item in that group should contribute points.
        - If more than one item in a "one_of" group appears applicable, choose the single best-supported item and set the others to 0.0.

        Scoring guidance:
        - Evaluate only the student's work for part ({part_label}).
        - Rubric items listed for part ({part_label}) or part "all" may be relevant here.
        - Do not count the same evidence twice. If two rubric items are triggered by the same underlying mistake or the same underlying success, award both only if the rubric items clearly measure distinct requirements. Otherwise, apply only the most specific or best-supported rubric item and set the overlapping item to 0.0.
        - If the condition is met and point_adjustment > 0, set "point_awarded" to a numeric value between 0 and point_adjustment.
        - If the condition is met and point_adjustment < 0, set "point_awarded" to point_adjustment exactly (that is, a negative adjustment).
        - If the condition is not met, set "point_awarded" to 0.0.
        - Use the rubric items as the primary scoring mechanism.
        - Final score rule for this part: {rubric_total_rule}
        - If the rubric does not fully resolve the score for this part, use the grading notes and explain the judgment clearly.

        You must return a JSON object with the following fields:

        - "points": the final numeric score for part ({part_label}), between 0 and {max_points_part}.
        - "rubric_eval": an object keyed by rubric id.
        For each rubric id, return an object with:
          - "evidence": concise factual evidence from the student's solution explaining whether the rubric condition is met. This text may be shown to the student, so it should be clear and professional, but your grading decision must still be based on comparison to the reference solution and grading notes.
          - "point_awarded": the numeric adjustment awarded for that rubric item, following the scoring guidance above.
        - "full_explanation": a concise grading summary for part ({part_label}). Do not repeat the full per-rubric detail already captured in "rubric_eval".
        - "feedback": concise (up to 5 sentences), student-facing guidance derived from the rubric evaluation and focused on the most important strengths or mistakes that affected the score for this part.

        Follow these steps:

        1. Extract the student's answer for part ({part_label}) from the student solution. Students may write answers out of order or embed multiple parts together. Use your judgment to isolate the relevant work.
        2. Compare the student's work for part ({part_label}) to the corresponding part in the reference solution, using the grading notes as guidance.
        3. Evaluate each rubric item against the student's work and record concise evidence in "rubric_eval".
        4. Before finalizing awards, check for overlapping rubric items that rely on the same evidence. Do not double count the same underlying mistake or success unless the rubric items clearly refer to distinct criteria.
        5. Apply the rubric groups before deciding the awarded adjustments, especially any "one_of" groups.
        6. Compute the final score for part ({part_label}) using this rule: {rubric_total_step}. Set "points" to that value.
        7. In "full_explanation", summarize the grading judgment for this part briefly, referring to the major rubric findings without restating every rubric item.
        8. In "feedback", give concise, student-facing guidance that is consistent with the rubric evaluation, emphasizes the main reasons for the score, and does not reveal the reference solution or hidden grading notes.

        {json_requirement}
    """,
    "partial_single": """
        This question allows partial credit. It has a single part.
        Grade the student using the rubric items below as the primary scoring guide.

        The maximum points for this question is {max_points_part} points.

        Rubric items:
        {rubric_items_block}

        Rubric groups:
        {rubric_groups_block}

        Group semantics:
        - A group with type "one_of" means at most one rubric item in that group should contribute points.
        - If more than one item in a "one_of" group appears applicable, choose the single best-supported item and set the others to 0.0.

        Scoring guidance:
        - For each rubric item, find evidence in the student's solution to determine whether the rubric condition is met.
        - Do not count the same evidence twice. If two rubric items are triggered by the same underlying mistake or the same underlying success, award both only if the rubric items clearly measure distinct requirements. Otherwise, apply only the most specific or best-supported rubric item and set the overlapping item to 0.0.
        - If the condition is met and point_adjustment > 0, set "point_awarded" to a numeric value between 0 and point_adjustment.
        - If the condition is met and point_adjustment < 0, set "point_awarded" to point_adjustment exactly (that is, a negative adjustment).
        - If the condition is not met, set "point_awarded" to 0.0.
        - Use the rubric items as the primary scoring mechanism.
        - Final score rule: {rubric_total_rule}
        - If the rubric does not fully resolve the score, use the grading notes and explain the judgment clearly.

        You must return a JSON object with the following fields:

        - "points": the final numeric score for this question, between 0 and {max_points_part}.
        - "rubric_eval": an object keyed by rubric id.
        For each rubric id, return an object with:
          - "evidence": concise factual evidence from the student's solution explaining whether the rubric condition is met. This text may be shown to the student, so it should be clear and professional, but your grading decision must still be based on comparison to the reference solution and grading notes.
          - "point_awarded": the numeric adjustment awarded for that rubric item, following the scoring guidance above.
        - "full_explanation": a concise grading summary that explains the overall score at a high level. Do not repeat the full per-rubric detail already captured in "rubric_eval".
        - "feedback": concise (up to 5 sentences), student-facing guidance derived from the rubric evaluation and focused on the most important strengths or mistakes that affected the score.

        Follow these steps:

        1. Read the student's solution carefully.
        2. Compare the student's solution to the reference solution, using the grading notes as guidance.
        3. Evaluate each rubric item against the student's work and record concise evidence in "rubric_eval".
        4. Before finalizing awards, check for overlapping rubric items that rely on the same evidence. Do not double count the same underlying mistake or success unless the rubric items clearly refer to distinct criteria.
        5. Apply the rubric groups before deciding the awarded adjustments, especially any "one_of" groups.
        6. Compute the final score using this rule: {rubric_total_step}. Set "points" to that value.
        7. In "full_explanation", summarize the overall grading judgment briefly, referring to the major rubric findings without restating every rubric item.
        8. In "feedback", give concise, student-facing guidance that is consistent with the rubric evaluation, emphasizes the main reasons for the score, and does not reveal the reference solution or hidden grading notes.

        {json_requirement}
    """,
        "binary_multi_all": """
                This question is configured for binary grading. It has multiple parts.
                Grade the student using the rubric items below as the primary grading guide.

                The parts are:
                {part_points_block}

                Rubric items:
                {rubric_items_block}

                Rubric groups:
                {rubric_groups_block}

                Group semantics:
                - A group with type "one_of" means at most one rubric item in that group should be marked as applicable.
                - If more than one item in a "one_of" group appears applicable, choose the single best-supported item and mark the others as not applicable.

                Scoring guidance:
                - Evaluate every rubric item exactly once and respect the rubric item's listed "part" field.
                - A rubric item attached to a specific part should affect only that part's correctness judgment.
                - A rubric item attached to part "all" may reflect work that spans multiple parts; when that happens, apply it only to the parts for which the evidence actually supports it.
                - Do not count the same evidence twice. If two rubric items are triggered by the same underlying mistake or the same underlying success, mark both as applicable only if the rubric items clearly measure distinct requirements. Otherwise, apply only the most specific or best-supported rubric item and mark the overlapping item as not applicable.
                - Use the rubric items as the primary grading mechanism.
                - If the rubric does not fully resolve a part's result, use the grading notes and explain the judgment clearly.

                You must return a JSON object with the following fields:

                - "result_parts": a list with one value for each part, in the exact order listed above. Each value must be one of "pass", "fail", or "error".
                - "rubric_eval": an object keyed by rubric id.
                For each rubric id, return an object with:
                    - "evidence": concise factual evidence from the student's solution explaining whether the rubric condition is met.
                    - "result": one of "pass", "fail", "feedback", or "n/a".
                Use:
                    - "pass" when the rubric item is satisfied and supports correctness,
                    - "fail" when the rubric item identifies a substantive mistake or an unmet required criterion,
                    - "feedback" when the item is useful context but not decisive on its own,
                    - "n/a" when the rubric item does not apply.
                - "full_explanation": a concise grading summary that explains the per-part judgments at a high level. Do not repeat the full per-rubric detail already captured in "rubric_eval".
                - "feedback": concise (up to 5 sentences, unless otherwise specified in the grading notes), student-facing guidance derived from the rubric evaluation.

                Follow these steps:

                1. For each part, identify the student's answer for that part. Students may write answers out of order or embed multiple parts together. Use your judgment to isolate the relevant work.
                2. Compare the student's work for each part to the corresponding part in the reference solution, using the grading notes as guidance.
                3. Evaluate each rubric item against the student's work and record concise evidence and a rubric-level result in "rubric_eval".
                4. Before finalizing judgments, check for overlapping rubric items that rely on the same evidence. Do not double count the same underlying mistake or success unless the rubric items clearly refer to distinct criteria.
                5. Apply the rubric groups before deciding the rubric-level results, especially any "one_of" groups.
                6. Decide the correctness of each part and place the values in "result_parts" in the exact order listed above.
                7. In "full_explanation", summarize the overall grading judgment briefly, emphasizing the part-level outcomes and the major rubric findings without restating every rubric item.
                8. In "feedback", give concise, student-facing guidance that is consistent with the rubric evaluation and does not reveal the reference solution or hidden grading notes.

                {json_requirement}
        """,
        "binary_multi_single": """
                This question is configured for binary grading. It has multiple parts, and you are grading only part ({part_label}).
                Grade the student using the rubric items below as the primary grading guide.

                Rubric items:
                {rubric_items_block}

                Rubric groups:
                {rubric_groups_block}

                Group semantics:
                - A group with type "one_of" means at most one rubric item in that group should be marked as applicable.
                - If more than one item in a "one_of" group appears applicable, choose the single best-supported item and mark the others as not applicable.

                Scoring guidance:
                - Evaluate only the student's work for part ({part_label}).
                - Rubric items listed for part ({part_label}) or part "all" may be relevant here.
                - Do not count the same evidence twice. If two rubric items are triggered by the same underlying mistake or the same underlying success, mark both as applicable only if the rubric items clearly measure distinct requirements. Otherwise, apply only the most specific or best-supported rubric item and mark the overlapping item as not applicable.
                - Use the rubric items as the primary grading mechanism.
                - If the rubric does not fully resolve the result for this part, use the grading notes and explain the judgment clearly.

                You must return a JSON object with the following fields:

                - "result": one of "pass", "fail", or "error" for part ({part_label}).
                - "rubric_eval": an object keyed by rubric id.
                For each rubric id, return an object with:
                    - "evidence": concise factual evidence from the student's solution explaining whether the rubric condition is met.
                    - "result": one of "pass", "fail", "feedback", or "n/a".
                Use:
                    - "pass" when the rubric item is satisfied and supports correctness,
                    - "fail" when the rubric item identifies a substantive mistake or an unmet required criterion,
                    - "feedback" when the item is useful context but not decisive on its own,
                    - "n/a" when the rubric item does not apply.
                - "full_explanation": a concise grading summary for part ({part_label}). Do not repeat the full per-rubric detail already captured in "rubric_eval".
                - "feedback": concise (up to 5 sentences), student-facing guidance derived from the rubric evaluation.

                Follow these steps:

                1. Extract the student's answer for part ({part_label}) from the student solution. Students may write answers out of order or embed multiple parts together. Use your judgment to isolate the relevant work.
                2. Compare the student's work for part ({part_label}) to the corresponding part in the reference solution, using the grading notes as guidance.
                3. Evaluate each rubric item against the student's work and record concise evidence and a rubric-level result in "rubric_eval".
                4. Before finalizing judgments, check for overlapping rubric items that rely on the same evidence. Do not double count the same underlying mistake or success unless the rubric items clearly refer to distinct criteria.
                5. Apply the rubric groups before deciding the rubric-level results, especially any "one_of" groups.
                6. Decide the correctness for part ({part_label}) and set "result" to "pass", "fail", or "error".
                7. In "full_explanation", summarize the grading judgment for this part briefly, referring to the major rubric findings without restating every rubric item.
                8. In "feedback", give concise, student-facing guidance that is consistent with the rubric evaluation and does not reveal the reference solution or hidden grading notes.

                {json_requirement}
        """,
        "binary_single": """
                This question is configured for binary grading. It has a single part.
                Grade the student using the rubric items below as the primary grading guide.

                Rubric items:
                {rubric_items_block}

                Rubric groups:
                {rubric_groups_block}

                Group semantics:
                - A group with type "one_of" means at most one rubric item in that group should be marked as applicable.
                - If more than one item in a "one_of" group appears applicable, choose the single best-supported item and mark the others as not applicable.

                Scoring guidance:
                - Evaluate each rubric item against the student's solution.
                - Do not count the same evidence twice. If two rubric items are triggered by the same underlying mistake or the same underlying success, mark both as applicable only if the rubric items clearly measure distinct requirements. Otherwise, apply only the most specific or best-supported rubric item and mark the overlapping item as not applicable.
                - Use the rubric items as the primary grading mechanism.
                - If the rubric does not fully resolve the result, use the grading notes and explain the judgment clearly.

                You must return a JSON object with the following fields:

                - "result": one of "pass", "fail", or "error".
                - "rubric_eval": an object keyed by rubric id.
                For each rubric id, return an object with:
                    - "evidence": concise factual evidence from the student's solution explaining whether the rubric condition is met.
                    - "result": one of "pass", "fail", "feedback", or "n/a".
                Use:
                    - "pass" when the rubric item is satisfied and supports correctness,
                    - "fail" when the rubric item identifies a substantive mistake or an unmet required criterion,
                    - "feedback" when the item is useful context but not decisive on its own,
                    - "n/a" when the rubric item does not apply.
                - "full_explanation": a concise grading summary for the overall question. Do not repeat the full per-rubric detail already captured in "rubric_eval".
                - "feedback": concise (up to 5 sentences), student-facing guidance derived from the rubric evaluation.

                Follow these steps:

                1. Read the student's solution carefully.
                2. Compare the student's solution to the reference solution, using the grading notes as guidance.
                3. Evaluate each rubric item against the student's work and record concise evidence and a rubric-level result in "rubric_eval".
                4. Before finalizing judgments, check for overlapping rubric items that rely on the same evidence. Do not double count the same underlying mistake or success unless the rubric items clearly refer to distinct criteria.
                5. Apply the rubric groups before deciding the rubric-level results, especially any "one_of" groups.
                6. Decide the overall correctness and set "result" to "pass", "fail", or "error".
                7. In "full_explanation", summarize the grading judgment briefly, referring to the major rubric findings without restating every rubric item.
                8. In "feedback", give concise, student-facing guidance that is consistent with the rubric evaluation and does not reveal the reference solution or hidden grading notes.

                {json_requirement}
        """,
}


class PromptBuilder:
    """Builds grading prompts from a question dictionary and student submission."""

    def _format_rubric_items(
        self,
        rubrics: dict[str, dict],
        part_label: str = "all",
    ) -> str:
        relevant_items = []
        for rubric_id, rubric_data in rubrics.items():
            rubric_part = rubric_data.get("part", "all")
            if part_label != "all" and rubric_part not in {"all", part_label}:
                continue
            relevant_items.append((rubric_id, rubric_data))

        lines = []
        for rubric_id, rubric_data in relevant_items:
            point_adjustment = rubric_data.get("point_adjustment")
            display_text = rubric_data.get("display_text", "")
            condition = rubric_data.get("condition", "")
            notes = rubric_data.get("notes", "")
            rubric_part = rubric_data.get("part", "all")

            lines.append(f"- id: {rubric_id}")
            lines.append(f"  part: {rubric_part}")
            lines.append(f"  point_adjustment: {point_adjustment}")
            lines.append(f"  display_text: {display_text}")
            lines.append(f"  condition: {condition}")
            if notes:
                lines.append(f"  notes: {notes}")

        return "\n".join(lines)

    def _format_rubric_groups(
        self,
        rubric_groups: list[dict] | None,
    ) -> str:
        if not rubric_groups:
            return "None"

        lines = []
        for group in rubric_groups:
            group_type = group.get("type", "")
            group_ids = ", ".join(group.get("ids", []))
            lines.append(f"- type: {group_type}; ids: {group_ids}")
        return "\n".join(lines)

    def _format_part_points(
        self,
        part_labels: list[str] | None,
        max_points: list[float] | None,
    ) -> str:
        if not part_labels or not max_points:
            return "- None"

        lines = []
        for label, points in zip(part_labels, max_points):
            lines.append(f"- ({label}): max_points = {points}")
        return "\n".join(lines)

    def get_grading_mode(
        self,
        partial_credit: bool,
        part_labels: list[str] | None,
        part_label: str = "all",
    ) -> str:
        multi_part = bool(part_labels) and len(part_labels) > 1

        if partial_credit and multi_part and part_label == "all":
            return "partial_multi_all"
        if partial_credit and multi_part:
            return "partial_multi_single"
        if partial_credit:
            return "partial_single"
        if multi_part and part_label == "all":
            return "binary_multi_all"
        if multi_part:
            return "binary_multi_single"
        return "binary_single"

    def _get_max_points_part(
        self,
        part_labels: list[str] | None,
        max_points: list[float] | None,
        part_label: str = "all",
    ) -> float | list[float] | None:
        multi_part = bool(part_labels) and len(part_labels) > 1

        if max_points is None:
            return None
        if multi_part and part_label == "all":
            return max_points
        if max_points:
            if multi_part and part_labels:
                try:
                    part_index = part_labels.index(part_label)
                    return max_points[part_index]
                except (ValueError, IndexError):
                    return None
            return max_points[0]
        return None

    def _format_prompt_block(self, template: str, **kwargs) -> str:
        return textwrap.dedent(template).format(**kwargs)

    def _rubric_total_instructions(self, rubric_total: str, max_points_part: float | list[float] | None) -> tuple[str, str]:
        max_points_limit = (
            float(sum(max_points_part))
            if isinstance(max_points_part, list)
            else max_points_part
        )
        if rubric_total == "sum_negative":
            return (
                f"start from the maximum points and add the awarded rubric adjustments, then clamp to [0, {max_points_limit}]",
                f"start from {max_points_limit}, add the awarded rubric adjustments, and clamp the result to [0, {max_points_limit}]",
            )
        if rubric_total == "flexible":
            return (
                "use the rubric award sum as a baseline, but you may adjust the final score up or down when the overall work justifies it; explain any deviation clearly",
                "use the rubric award sum as a baseline, then adjust if needed based on the overall work and grading notes, and clamp the final value to the allowed range",
            )
        return (
            f"sum the awarded rubric points from a baseline of 0 and clamp to [0, {max_points_limit}]",
            f"sum the awarded rubric points from 0 and clamp the result to [0, {max_points_limit}]",
        )

    def _no_rubric_context(
        self,
        mode: str,
        *,
        part_label: str = "all",
        part_labels: list[str] | None = None,
        max_points: list[float] | None = None,
        max_points_part: float | list[float] | None = None,
    ) -> str:
        if mode == "partial_multi_all":
            lines = [
                "",
                "This question allows partial credit. It has multiple parts.",
                "The parts and their maximum points are:",
                "",
            ]
            for label, points in zip(part_labels or [], max_points or []):
                lines.append(f"- ({label}): max_points = {points}")
            return "\n".join(lines) + "\n"

        if mode == "partial_multi_single":
            return (
                f"\nThis question allows partial credit. You are grading only part ({part_label}).\n"
                f"The maximum points for this part is {max_points_part} points.\n\n"
            )

        if mode == "partial_single":
            return (
                "\nThis question allows partial credit. It has a single part.\n"
                f"The maximum points for this question is {max_points_part} points.\n\n"
            )

        if mode == "binary_multi_all":
            lines = ["", "This question has multiple parts. The parts are:", ""]
            for label in part_labels or []:
                lines.append(f"- ({label})")
            return "\n".join(lines) + "\n"

        if mode == "binary_multi_single":
            return (
                f"\nThis question is configured for binary grading. You are grading only part ({part_label}).\n\n"
            )

        if mode == "binary_single":
            return "\nThis question is configured for binary grading (no partial credit).\n\n"

        return "\n"

    def instructions_no_rubric(
        self,
        mode: str,
        json_requirement: str,
        part_label: str = "all",
        part_labels: list[str] | None = None,
        max_points: list[float] | None = None,
        max_points_part: float | list[float] | None = None,
    ) -> str:
        template = NO_RUBRIC_TEMPLATES[mode]
        context = self._no_rubric_context(
            mode,
            part_label=part_label,
            part_labels=part_labels,
            max_points=max_points,
            max_points_part=max_points_part,
        )
        return context + self._format_prompt_block(
            template,
            json_requirement=json_requirement,
            part_label=part_label,
            max_points_part=max_points_part,
        )

    def instructions_rubric(
        self,
        mode: str,
        json_requirement: str,
        rubrics: dict[str, dict],
        rubric_groups: list[dict] | None = None,
        part_label: str = "all",
        part_labels: list[str] | None = None,
        max_points: list[float] | None = None,
        max_points_part: float | list[float] | None = None,
        rubric_total: str = "sum_positive",
    ) -> str:
        if mode not in RUBRIC_TEMPLATES:
            raise NotImplementedError(
                f"Rubric prompt not implemented yet for grading mode '{mode}'."
            )

        rubric_items_block = self._format_rubric_items(rubrics, part_label)
        rubric_groups_block = self._format_rubric_groups(rubric_groups)
        part_points_block = self._format_part_points(part_labels, max_points)
        template = RUBRIC_TEMPLATES[mode]
        rubric_total_rule, rubric_total_step = self._rubric_total_instructions(rubric_total, max_points_part)

        return self._format_prompt_block(
            template,
            json_requirement=json_requirement,
            part_label=part_label,
            max_points_part=max_points_part,
            part_points_block=part_points_block,
            rubric_items_block=rubric_items_block or "- None",
            rubric_groups_block=rubric_groups_block,
            rubric_total_rule=rubric_total_rule,
            rubric_total_step=rubric_total_step,
        )

    def build_task_prompt(
        self,
        question_dict: dict,
        student_soln: str,
        part_label: str = "all",
    ) -> tuple[str, int | list[int] | None]:
        if 0:
            print("[PromptBuilder] build_task_prompt called:")
            print("  qtag:", question_dict.get("qtag"))
            print("  partial_credit:", question_dict.get("partial_credit"))
            print("  parts:", question_dict.get("parts"))
            print("  rubrics:", list(question_dict.get("rubrics", {{}}).keys()))
            print("  part_label:", part_label)
            import traceback; traceback.print_stack(limit=5)

        question_text = str(question_dict.get("question_text", ""))
        ref_solution = str(question_dict.get("solution", ""))
        grading_notes = str(question_dict.get("grading_notes", ""))
        partial_credit = question_dict.get("partial_credit", False) is True
        parts = question_dict.get("parts", [])
        rubrics = question_dict.get("rubrics", {})
        rubric_total = question_dict.get("rubric_total") or "sum_positive"
        rubric_groups = question_dict.get("rubric_groups", [])
        part_labels = [part.get("part_label", "all") for part in parts]
        max_points = [part.get("points", 0) for part in parts]

        if partial_credit and (
            not part_labels or not max_points or len(part_labels) != len(max_points)
        ):
            partial_credit = False

        mode = self.get_grading_mode(partial_credit, part_labels, part_label)
        max_points_part = self._get_max_points_part(part_labels, max_points, part_label)

        prompt = PROMPT_PREAMBLE
        if rubrics:
            prompt += self.instructions_rubric(
                mode,
                JSON_REQUIREMENT,
                rubrics,
                rubric_groups=rubric_groups,
                part_label=part_label,
                part_labels=part_labels,
                max_points=max_points,
                max_points_part=max_points_part,
                rubric_total=rubric_total,
            )
        else:
            prompt += self.instructions_no_rubric(
                mode,
                JSON_REQUIREMENT,
                part_label=part_label,
                part_labels=part_labels,
                max_points=max_points,
                max_points_part=max_points_part,
            )

        prompt += "\n\n--- QUESTION HTML ---\n" + question_text
        prompt += "\n\n--- REFERENCE SOLUTION HTML ---\n" + ref_solution
        prompt += "\n\n--- GRADING NOTES ---\n" + grading_notes
        prompt += "\n\n--- STUDENT SOLUTION ---\n" + student_soln

        return prompt, max_points_part