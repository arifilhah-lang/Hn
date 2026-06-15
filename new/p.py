from openai import OpenAI

client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = "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"
)

completion = client.chat.completions.create(
  model="nvidia/nemotron-3-ultra-550b-a55b",
  messages=[{"role":"user","content":"hi"}],
  temperature=1,
  top_p=0.95,
  max_tokens=100,
  stream=True
)

for chunk in completion:
  if not chunk.choices:
    continue
  reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None)
  if reasoning:
    print(reasoning, end="")
  if chunk.choices[0].delta.content is not None:
    print(chunk.choices[0].delta.content, end="")