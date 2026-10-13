from env_setup import load_env  # round 38d: ELIGIBILITY_DOTENV, else the .env here
load_env()

from openai import OpenAI

client = OpenAI()

response = client.embeddings.create(
    input="test sentence",
    model="text-embedding-3-small"
)

print("OpenAI connection works")
print("Embedding length: " + str(len(response.data[0].embedding)))
