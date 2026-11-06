from pydantic_settings import BaseSettings, SettingsConfigDict


class PaymentSettings(BaseSettings):
    """Payment settings. Only PUBLIC values: no private keys or wallet secrets live here.

    Chain id and RPC URL come from the existing settings (ARC_CHAIN_ID, ARC_RPC_URL).
    """
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    # Public address of the merchant/test wallet that receives payments.
    payment_recipient_address: str = ''
    # Official Arc Testnet USDC ERC-20 interface (6 decimals). Native gas USDC uses 18 decimals.
    payment_token_address: str = '0x3600000000000000000000000000000000000000'
    payment_token_decimals: int = 6
    payment_network_name: str = 'Arc Testnet'
    payment_explorer_url: str = 'https://explorer.testnet.arc.io'
    # Blocks that must exist on top of (and including) the payment's block before it counts.
    payment_confirmations: int = 1
    # Seconds the buyer has to approve in MetaMask after a BUY.
    payment_window: int = 600
    # Seconds a submitted transaction may stay unseen on-chain before the payment fails.
    payment_tx_timeout: int = 600
    # Minimum seconds between on-chain checks of one payment (the public RPC rate-limits).
    payment_check_interval: int = 4


payment_settings = PaymentSettings()
