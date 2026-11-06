from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./mivo.db'
    app_origin: str = 'http://localhost:3000'
    cookie_secure: bool = False
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-3.1-flash-lite'
    gemini_rpm: int = 5
    negotiation_rounds: int = 2
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
    # Shared secret the Raspberry Pi sends as 'Authorization: Bearer <key>'. Empty disables /device.
    device_api_key: str = ''
    # Buyer account that owns negotiations started from the device (shown on the website for that login).
    device_buyer_email: str = ''
    device_dealers: int = 3
    # Set automatically by Vercel. VERCEL=1 switches to serverless behaviour.
    vercel: bool = False
    vercel_url: str = ''
    vercel_branch_url: str = ''
    vercel_project_production_url: str = ''

    @model_validator(mode='after')
    def serverless_defaults(self):
        if self.vercel:
            if self.app_origin == 'http://localhost:3000' and self.vercel_project_production_url:
                self.app_origin = 'https://' + self.vercel_project_production_url
            self.cookie_secure = True
        return self

    @property
    def allowed_origins(self):
        # Production origin plus this deployment's own preview URLs.
        extra = {'https://' + u for u in (self.vercel_url, self.vercel_branch_url) if u}
        return {self.app_origin, *extra}

    @property
    def sqlalchemy_url(self):
        url = self.database_url
        for prefix in ('postgres://', 'postgresql://'):
            if url.startswith(prefix): return 'postgresql+psycopg://' + url[len(prefix):]
        return url

settings = Settings()
