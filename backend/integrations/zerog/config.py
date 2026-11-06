from pydantic_settings import BaseSettings, SettingsConfigDict


class ZeroGSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    # 0G Compute Router ("0G Private Computer"): one OpenAI-compatible endpoint + API key (sk-...).
    # Mainnet https://router-api.0g.ai/v1 ; testnet https://router-api-testnet.integratenetwork.work/v1
    zerog_router_url: str = 'https://router-api.0g.ai/v1'
    zerog_api_key: str = ''
    # 0G's own model on the router; supports JSON output and image input.
    zerog_model: str = '0gm-1.0-35b-a3b'
    zerog_timeout: float = 25.0
    zerog_retries: int = 1          # extra attempts on timeout / 429 / 5xx / invalid JSON
    zerog_max_tokens: int = 400
    zerog_enabled: bool = True      # set false to force the existing Gemini path

    @property
    def active(self): return self.zerog_enabled and bool(self.zerog_api_key)


zerog_settings = ZeroGSettings()
