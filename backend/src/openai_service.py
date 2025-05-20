from openai import OpenAI
import os

class OpenAIService:
    def __init__(self, api_key, default_model, default_temperature=0.7):
        self.client = OpenAI(api_key=api_key)
        self.default_model = default_model
        self.default_temperature = default_temperature

    def get_response(self, human_message, system_message=None, model=None, temperature=None):
        model = model or self.default_model
        temperature = temperature or self.default_temperature

        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": human_message})

        try:
            response = self.client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=messages
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error with getting a response from OpenAI: {e}")
            return None
