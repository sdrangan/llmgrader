from openai import OpenAI
import textwrap
import json
client = OpenAI()

response = client.responses.create(
    model="gpt-5",
    tools=[{"type": "web_search"}],
    input=textwrap.dedent("""\
        How does this project compare to the state-of-the-art in autograding? What are the key differences and advantages?
        https://sdrangan.github.io/llmgrader/docs/
        Is it worth considering using?
    """)
)

print(response.output_text)


print(json.dumps(response.model_dump(), indent=2))