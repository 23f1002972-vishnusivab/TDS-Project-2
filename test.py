import requests
import os
from dotenv import load_dotenv

load_dotenv()

resp = requests.post(
    "http://localhost:5000/quiz",
    json={
        "email": "23f1002972@ds.study.iitm.ac.in",
        "secret": os.environ.get("QUIZ_SECRET"),
        "url": "https://tds-llm-analysis.s-anand.net/demo",
    },
)

print(resp.status_code)
print(resp.text)
