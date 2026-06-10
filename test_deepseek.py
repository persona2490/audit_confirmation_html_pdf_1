from openai import OpenAI

client = OpenAI(
    api_key="sk-f1d43542a8764848a037afb35e9c666e",
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {
            "role": "user",
            "content": "你好，请简单介绍一下你自己"
        }
    ],
    temperature=0.2
)

print(response.choices[0].message.content)