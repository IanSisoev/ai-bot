import os

from dotenv import load_dotenv
from gigachat import GigaChat

load_dotenv()
giga = GigaChat(
    credentials=os.getenv("GIGACHAT_CREDENTIALS"),
    model="GigaChat-2",
    verify_ssl_certs=False,
)

response = giga.chat("Привет! Кто ты?")
print(response.choices[0].message.content)
