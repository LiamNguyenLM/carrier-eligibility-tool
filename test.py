from dotenv import load_dotenv
load_dotenv()

import anthropic

client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Say exactly this: Setup is working correctly."}
    ]
)

print(message.content[0].text)
