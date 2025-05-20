from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
from src.openai_service import OpenAIService
load_dotenv(dotenv_path="config/.env")

app = Flask(__name__)
api_key = os.getenv('OPENAI_API_KEY')
default_model = os.getenv('DEFAULT_MODEL', 'gpt-4o-mini')
default_temperature = float(os.getenv('DEFAULT_TEMPERATURE', '0.7'))

openai_service = OpenAIService(
    api_key=api_key,
    default_model=default_model,
    default_temperature=default_temperature
)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    if not data or 'human_message' not in data:
        return jsonify({'error': 'Human message is required'}), 400
    response = openai_service.get_response(
        human_message=data.get('human_message'),
        system_message=data.get('system_message'),
        model=data.get('model', default_model),
        temperature=data.get('temperature', default_temperature)
    )

    return jsonify({'response': response}) if response else (jsonify({'error': 'OpenAI failed'}), 500)



@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
