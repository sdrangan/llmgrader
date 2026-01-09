from agents import Agent, Runner
import asyncio
import os
from agents import function_tool
import textwrap
import argparse
from xilinxutils.parselatex import parse_latex_soln
import json
import pandas as pd


def wrap_preserving_newlines(text, width=80):
    paragraphs = text.split("\n")
    wrapped = [
        textwrap.fill(p, width=width) if p.strip() else ""
        for p in paragraphs
    ]
    return "\n".join(wrapped)

class SolutionParser:
    def __init__(self, ref_soln: str, student_soln: str):
        """
        Load and parse LaTeX solution files for reference and student solutions.
        
        Parameters:
        -----------
        ref_soln : str
            Path to the reference LaTeX solution file.
        student_soln : str
            Path to the student's LaTeX solution file.
        """
        self.ref_soln = ref_soln
        self.student_soln = student_soln
        
    def parse(self) -> str:
        """
        Parses the LaTeX solution files and extracts items for all questions
        
        Returns
        -------
        error_msg : str | None
            Error message if any items are missing, else None.
        """
        try:
            self.ref_items = parse_latex_soln(self.ref_soln)
        except Exception as e:
            return f"Error parsing reference solution: {e}"
        try:
            self.student_items = parse_latex_soln(self.student_soln)
        except Exception as e:
            return f"Error parsing student solution: {e}"
        
    def check_question(self, qnum: int) -> str | None:
        """
        Checks if the specified question number exists in both reference and student items.
        Parameters:
        qnum : int
            Question number to check (1-based index).
        Returns:
        -------
        error_msg : str | None 
            Error message if the question number is invalid, else None.
        """
        if qnum < 1:
            return f"Invalid question number {qnum}. Must be >= 1."
        if len(self.ref_items) < qnum:
            return f"Reference solution has only {len(self.ref_items)} questions; cannot get question {qnum}."
        if len(self.student_items) < qnum:
            return f"Student solution has only {len(self.student_items)} questions; cannot get question {qnum}."        
        return None        
        
   

def create_task(part_label : str | None) -> str:
    """
    Creates the task description for the agent to grade a student's solution.
    
    Parameters:
    -----------
    part_label : str | None
        Optional label for the part of the question being graded.
        
    Returns:
    --------
    task : str
        The task description for the agent.
    """
    if part_label is None:
    
        task = """
        Your task is to grade a problem based on a student's solution parsed from a LaTeX file
        and a correct reference solution. You must always return a single JSON object with the
        fields: "result" and "feedback". The "result" field must be one of: "correct", "incorrect", or "error".

        Follow these steps exactly:

        1. Call the get_items tool:
            parsed_items = get_items()
        This returns a dictionary with:
            - parsed_items['question']      : the question text
            - parsed_items['ref_soln']      : one correct reference solution
            - parsed_items['grading']       : grading notes
            - parsed_items['student_soln']  : the student's solution

        2. Determine whether parsed_items['student_soln'] appears to be for a *different* problem
        than parsed_items['question'].
        - If it appears misaligned:
                Return the following JSON object:
                {
                "result": "error",
                "feedback": "There appears to be an alignment error. <brief explanation>"
                }
            Do not attempt further grading.

        3. If the student solution appears to be for the correct problem:
        - Compare parsed_items['student_soln'] to parsed_items['ref_soln'], using
            parsed_items['grading'] as guidance.
        - Keep feedback to at most 3 short sentences.
        - Do not restate the question, reference solution, or student solution.
        - Do not use section headings like "Error:", "Explanation:", or "Suggestion:".

        - If the student solution is correct:
                Return:
                {
                "result": "correct",
                "feedback": "The solution is correct. Congratulations!"
                }

        - If the student solution contains errors:
                Return:
                {
                "result": "incorrect",
                "feedback": "<a concise paragraph: briefly state what is correct (if anything) and clearly state the main error(s)>"
                }

        Your final output must be valid JSON and must contain only the fields:
            - "result"
            - "feedback"
        No additional text or formatting is allowed outside the JSON object.
        """
    else :
        task = f"""
        Your task is to grade **part ({part_label})** of a multi-part engineering problem.
        You will be given the entire question, the entire reference solution, and the entire
        student solution. Students may mix parts together or refer to earlier parts. Ignore
        all parts except the one you are asked to grade.

        You must always return a single JSON object with the fields: "result" and "feedback".
        The "result" field must be one of: "correct", "incorrect", or "error".

        Follow these steps exactly:

        1. Call the get_items tool:
            parsed_items = get_items()
        This returns a dictionary with:
            - parsed_items['question']      : the full question text
            - parsed_items['ref_soln']      : the full reference solution
            - parsed_items['grading']       : the full grading notes
            - parsed_items['student_soln']  : the full student solution

        2. Extract the student's answer for part ({part_label}) from parsed_items['student_soln'].
        Students may write answers out of order or embed multiple parts together. Use your
        judgment to isolate the portion corresponding to part ({part_label}).

        3. Determine whether the extracted answer appears to be for a *different* problem
        than parsed_items['question'].
        - If misaligned:
                Return:
                {{
                "result": "error",
                "feedback": "There appears to be an alignment error. <brief explanation>"
                }}
            Do not attempt further grading.

        4. If the student's answer appears to be for the correct problem:
        - Compare it to the reference solution for part ({part_label}), using the grading notes.
        - Keep feedback to at most 3 short sentences.
        - Do not restate the question, reference solution, or student solution.
        - Do not use section headings like "Error:", "Explanation:", or "Suggestion:".

        - If the student's answer is correct:
                Return:
                {{
                "result": "correct",
                "feedback": "The solution is correct. Congratulations!"
                }}

        - If the student's answer contains errors:
                Return:
                {{
                "result": "incorrect",
                "feedback": "<a concise paragraph: briefly state what is correct (if anything) and clearly state the main error(s)>"
                }}

        Your final output must be valid JSON and must contain only:
            - "result"
            - "feedback"
        No additional text is allowed outside the JSON object.
        """
    return task


    
async def main():
    # Parse command-line arguments
    arg_parser = argparse.ArgumentParser(description="Grade student solutions using AI")
    arg_parser.add_argument('--schema', type=str, default="grade_schema.csv", help='Schema file (default: grade_schema.csv)')
    arg_parser.add_argument('--qnum', type=int, nargs='+', default=None, help='Question number(s) to grade (default: None)')
    arg_parser.add_argument('--part', type=str, nargs='+', default=None, help='Part label(s) to grade (default: None)')
    arg_parser.add_argument('--model', type=str, default="gpt-4.1-mini", help='AI model to use (default: gpt-4.1-mini)')
    arg_parser.add_argument('--ref', type=str, default="ref_soln.tex", help='Reference solution file (default: ref_soln.tex)')
    arg_parser.add_argument('--student', type=str, default="student_soln.tex", help='Student solution file (default: student_soln.tex)')
    arg_parser.add_argument('--output', type=str, default="results.txt", help='Output file (default: results.txt)')
    args = arg_parser.parse_args()


    # Parse all the questions from the LaTeX files
    model = args.model
    output_file = args.output
    qnums = args.qnum
    schema_file = args.schema
    part_labels = args.part
    

    # Check if question numbers were provided
    if qnums is None:
        use_schema = True
    else:
        use_schema = False
        if part_labels is None:
            part_labels = [None] * len(qnums)
        
        # Check that lengths match
        if len(part_labels) != len(qnums):
            print("Error: Number of part labels must match number of question numbers.")
            return
    
    # If required, load the schema file to get question numbers and part labels
    if use_schema:
        if not os.path.isfile(schema_file):
            print(f"Schema file {schema_file} not found.")
            return
        
        df = pd.read_csv(schema_file)
        # Clean up part_label column
        df["part_label"] = (
            df["part_label"]
            .astype(str)          # convert NaN → "nan"
            .str.strip()          # remove whitespace
            .replace({"nan": None, "": None})
        )

        # Assign question numbers based on row order
        df["qnum"] = (df["question_name"] != df["question_name"].shift()).cumsum()

        # Select only graded parts
        graded = df[df["grade"].str.lower() == "yes"]

        # Extract qnums and part labels
        qnums = graded["qnum"].tolist()
        part_labels = graded["part_label"].tolist()

    # Try to parse the LaTeX solution files
    parser = SolutionParser(ref_soln=args.ref, student_soln=args.student)
    error_msg = parser.parse()
    if error_msg is not None:
        print(error_msg)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(error_msg)
            return
        
    # Open the output file once and loop through all question numbers
    with open(output_file, "w", encoding="utf-8") as f: 

        for qnum, part_label in zip(qnums, part_labels):

            # Create the header
            if part_label is not None:
                hdr = f"Question {qnum} part ({part_label})"
            else:
                hdr = f"Question {qnum}"
            print(f"{hdr}\n{'='*40}\n")
            f.write(f"{hdr}\n{'='*40}\n")

            # Check if the specified question number is valid
            error_msg = parser.check_question(qnum)
            if error_msg is not None:
                print(error_msg)
                f.write(error_msg + "\n\n")
                continue

            # Create the task description
            task = create_task(part_label)

            # We define the tool within the main function to have access to parser instance
            # and question number. This way we don't need to pass parser as an argument to the tool
            @function_tool
            def get_items() -> dict:        
                """
                Extracts and returns the parsed items for the current question.

                Returns:
                --------
                parsed_items : dict
                    A dictionary with items:
                    parsed_items['question'] : reference question text 
                    parsed_items['ref_soln'] : reference solution text representing one correct solution
                    parsed_items['grading'] : reference grading notes text
                    parsed_items['student_soln'] : student solution text
                """
                parsed_items = {'question': parser.ref_items[qnum - 1]['question'],
                                'ref_soln': parser.ref_items[qnum - 1]['solution'],
                                'grading': parser.ref_items[qnum - 1]['grading'],
                                'student_soln': parser.student_items[qnum - 1]['solution']}
                return parsed_items

            # Now we can create and run the agent
            agent = Agent(
                name="Grader",
                instructions="""
                Use the get_items tool (with no arguments) to retrieve the question,
                reference solution, grading notes, and student solution. Then compare
                the student solution to the reference solution and provide feedback
                on correctness.
                """,
                tools=[get_items],
                model=model,
            )

            print(f"Running agent using model {model}...")
            result = await Runner.run(
                agent, 
                task)
            response = result.final_output

            # Parse the JSON output
            data = json.loads(response)

            # Extract fields
            result = data["result"]
            feedback = data["feedback"]
            feedback = wrap_preserving_newlines(feedback, width=80)
            f.write(f"Result: {result}\n")
            f.write(f"Feedback: {feedback}\n\n")    

            # Also print to console
            print(f"Result: {result}") 
            print(f"Feedback: {feedback}")
    
def entrypoint():
    asyncio.run(main())

if __name__ == "__main__":
    entrypoint()