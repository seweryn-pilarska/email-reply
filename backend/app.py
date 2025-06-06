from flask import Flask, request, jsonify
from dotenv import load_dotenv
from agent_graph import build_agent_graph
import os
load_dotenv(dotenv_path="config/.env")
graph = build_agent_graph()

app = Flask(__name__)
api_key = os.getenv('OPENAI_API_KEY')
default_model = os.getenv('DEFAULT_MODEL', 'gpt-4o-mini')
default_temperature = float(os.getenv('DEFAULT_TEMPERATURE', '0.7'))

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    if not data or 'human_message' not in data:
        return jsonify({'error': 'Human message is required'}), 400
    
    result = graph.invoke({"email": data.get('human_message')})
    reply = result.get("reply")
    return jsonify({'response': reply}) if reply else (jsonify({'error': 'OpenAI failed'}), 500)

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
