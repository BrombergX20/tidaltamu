import requests
import json

key = ""
with open('key.txt', 'r') as f:
	key = f.readline().strip()

print(key)

def get_available_models():
    """Fetch list of available models"""
    url = "https://chat-api.tamu.ai/openai/models"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {key}"
    }
    
    # print(f"Debug - Key being used: '{key}'")
    # print(f"Debug - Authorization header: '{headers['Authorization']}'")
    response = requests.get(url, headers=headers)
    # print(f"Debug - Response status: {response.status_code}")
    # print(f"Debug - Response body: {response.text}")
    response.raise_for_status()
    
    return response.json()


def prompt_llm(user_message, model="protected.gemini-2.5-flash-lite", system_message=None):
    """Send a prompt to the LLM and get a response"""
    url = "https://chat-api.tamu.ai/openai/chat/completions"
    
    # Build the messages list
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": user_message})
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }
    
    data = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,  # Controls randomness (0-1)
        "stream": False  # Disable streaming to get complete response at once
    }
    
    response = requests.post(url, headers=headers, json=data)
    # print(f"Debug - Response status: {response.status_code}")
    # print(f"Debug - Response body: {response.text}")
    response.raise_for_status()
    
    result = response.json()
    return result["choices"][0]["message"]["content"]


# Usage
try:
    # List available models
    models = get_available_models()
    # print("Available models:")
    # print(json.dumps(models, indent=2))
    
    # Example: Prompt the LLM with your code
    my_code = """
    def hello():
        print('Hello World')
    """
    
    response = prompt_llm(
        user_message=f"Review this code and suggest improvements:\n{my_code}",
        system_message="You are a helpful code reviewer"
    )
    print("\nLLM Response:")
    print(response)
    
except Exception as e:
    print(f"Error: {e}")

