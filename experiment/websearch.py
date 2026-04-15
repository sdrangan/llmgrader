from openai import OpenAI
import textwrap
import json
client = OpenAI()

response = client.responses.create(
    model="gpt-5",
    tools=[{"type": "web_search"}],
    input=textwrap.dedent("""\
        Can you review this project:  https://sdrangan.github.io/pysilicon/docs.  It is still under construction.  But, I am wondering if there are any novel features relative to what other python spec-RTL tools do.  
                          
        If completed, would the project add value to what is likely to be commercially available shortly.  Should I consider using this, if it they complete some of the features. 
    """)
)

print(response.output_text)


print(json.dumps(response.model_dump(), indent=2))