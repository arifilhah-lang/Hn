import os
import logging

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

log = logging.getLogger(__name__)

# Load API key dynamically from env
def get_nvidia_client():
    if not OpenAI:
        log.error("OpenAI package is not installed.")
        return None
        
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        return OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
            timeout=15.0
        )
    except Exception as e:
        log.error(f"Failed to init Nvidia client: {e}")
        return None

# Model Map
NVIDIA_MODELS = {
    "zolo_v2": "minimaxai/minimax-m3",
    "zolo_2":  "z-ai/glm-5.1"
}

class NvidiaResponse:
    def __init__(self, text):
        self.text = text

def _convert_contents_to_openai(contents, system_instruction=None):
    """
    Converts Google genai.types.Content or plain text to OpenAI messages format.
    """
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    
    if isinstance(contents, str):
        messages.append({"role": "user", "content": contents})
    elif isinstance(contents, list):
        for c in contents:
            # Assume c is genai.types.Content
            role = "assistant" if getattr(c, "role", "") == "model" else "user"
            
            # Combine parts
            text_parts = []
            if hasattr(c, 'parts') and c.parts:
                for part in c.parts:
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
            
            messages.append({
                "role": role,
                "content": "\n".join(text_parts)
            })
    return messages

def is_nvidia_model(model_alias):
    return model_alias in NVIDIA_MODELS

def generate_nvidia_content(model_alias, contents, system_instruction=None, max_tokens=1024, temperature=0.7, thinking_mode=False):
    client = get_nvidia_client()
    if not client:
        raise ValueError("NVIDIA_API_KEY is not set in environment variables.")
        
    model_name = NVIDIA_MODELS.get(model_alias, NVIDIA_MODELS["zolo_v2"])
    messages = _convert_contents_to_openai(contents, system_instruction)
    
    kwargs = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "stream": False
    }
    
    # Handle thinking mode for Nemotron
    if thinking_mode and model_alias == "zolo_2":
        kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": max_tokens
        }
        
    response = client.chat.completions.create(**kwargs)
    if not response.choices:
        return NvidiaResponse("")
    
    content = response.choices[0].message.content or ""
    return NvidiaResponse(content)

def generate_nvidia_stream(model_alias, contents, system_instruction=None, max_tokens=1024, temperature=0.7, thinking_mode=False):
    client = get_nvidia_client()
    if not client:
        raise ValueError("NVIDIA_API_KEY is not set in environment variables.")
        
    model_name = NVIDIA_MODELS.get(model_alias, NVIDIA_MODELS["zolo_v2"])
    messages = _convert_contents_to_openai(contents, system_instruction)
    
    kwargs = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.95,
        "stream": True
    }
    
    # Handle thinking mode for Nemotron
    if thinking_mode and model_alias == "zolo_2":
        kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": max_tokens
        }
        
    stream = client.chat.completions.create(**kwargs)
    
    for chunk in stream:
        if not chunk.choices:
            continue
            
        delta = chunk.choices[0].delta
        
        # Stream reasoning (thinking) output if available
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            # We wrap thinking so it renders like standard output
            # Actually, standard output stream is just text. Let's yield it directly.
            yield ("chunk", reasoning)
            
        if delta.content:
            yield ("chunk", delta.content)
