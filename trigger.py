import os
from vapi_python import Vapi
from dotenv import load_dotenv

load_dotenv()
vapi = Vapi(api_key=os.getenv('VAPI_PUBLIC_KEY'))

def start_test(question: str):
    vapi.start(
        assistant_id=os.getenv('VAPI_ASSISTANT_ID'),
        assistant_overrides={
            "firstMessage": question,
            "model": {
                "provider": "openai",  # <--- THIS WAS MISSING
                "model": "gpt-4o",    # <--- THIS WAS MISSING
                "messages": [{
                    "role": "system",
                    "content": "You are a critical Board Member. Ask the user about their failure and judge their poise."
                }]
            }
        }
    )

if __name__ == "__main__":
    q = "I see the Bangalore project is failing. Explain yourself clearly and concisely."
    start_test(q)