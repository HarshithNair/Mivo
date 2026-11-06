from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./mivo.db'
    app_origin: str = 'http://localhost:3000'
    cookie_secure: bool = False
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-3.1-flash-lite'
    gemini_rpm: int = 5
    negotiation_rounds: int = 4
    negotiation_deadline: int = 600
    payment_enabled: bool = False
    arc_rpc_url: str = 'https://rpc.testnet.arc.io'
    arc_chain_id: int = 5042002
    settlement_contract: str = ''
    settlement_token: str = '0x3600000000000000000000000000000000000000'
    settlement_decimals: int = 6
    quote_signer_file: str = '.secrets/quote-signer.key'
    confirmations: int = 2
    world_client_id: str = ''
    world_client_secret: str = ''
    world_sandbox: bool = True
    world_required: bool = False

settings = Settings()
