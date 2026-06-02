import os, sys
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('OPENAI_API_KEY')

if not key or key.startswith('sk-your-key'):
    print('[FAIL] OPENAI_API_KEY is not set.')
    print('       -> Copy .env.example to .env and paste your key into it.')
    sys.exit(1)

try:
    from openai import OpenAI
    client = OpenAI(api_key=key)
    model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    r = client.chat.completions.create(
        model=model,
        messages=[{'role': 'user', 'content': 'reply with the single word: OK'}],
        max_tokens=5,
    )
    reply = r.choices[0].message.content.strip()
    print('[OK] Environment ready. model=' + model + '  reply=' + reply)
except Exception as e:
    print('[FAIL] OpenAI call failed: ' + repr(e))
    print('       -> Check your key, billing, and internet connection.')
    sys.exit(1)
