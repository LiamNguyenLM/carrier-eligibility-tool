from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

client = OpenAI()

response = client.embeddings.create(
    input="test sentence",
    model="text-embedding-3-small"
)

print("OpenAI connection works")
print("Embedding length: " + str(len(response.data[0].embedding)))
