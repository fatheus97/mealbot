---
description: Rules for LLM/AI integration code
globs: ["**/llm/**", "**/ai/**", "**/prompts/**"]
---

# LLM Integration Rules

- All LLM output MUST be parsed into Pydantic models
- Never trust raw LLM text — validate structure before using
- Implement retry logic with exponential backoff for API calls
- Set explicit timeouts on all LLM API calls
- Log token usage for cost tracking
- Be skeptical of agent frameworks (LangChain etc.) — prefer simple functions
  when a direct API call with structured output will do the job
- Handle hallucinations: validate generated data against known constraints