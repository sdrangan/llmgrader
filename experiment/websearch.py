from openai import OpenAI
import textwrap
import json
client = OpenAI()

response = client.responses.create(
    model="gpt-5",
    tools=[{"type": "web_search"}],
    input=textwrap.dedent("""\
        When is the NYU Spring break in 2026?
    """)
)

print(response.output_text)


print(json.dumps(response.model_dump(), indent=2))