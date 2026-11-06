"""0G decentralized AI for MIVO negotiations (isolated integration).

compute  : 0G Compute Router (OpenAI-compatible) inference with request/provider metadata
policy   : privacy-preserving prompts; model output -> price via deterministic server rules
agents   : drop-in buyer/merchant/dealer adapters (0G first, Gemini fallback, decision log)
evidence : sanitized negotiation evidence + content hash for 0G Storage
api      : status, decision log and evidence endpoints
Storage upload/download runs with the official TS SDK in integrations/zerog/storage/.
"""
