// 0G Storage testnet (Galileo). Values from docs.0g.ai storage SDK page; chain id verified live (16602).
export const RPC_URL = process.env.ZEROG_STORAGE_RPC || 'https://evmrpc-testnet.0g.ai';
export const INDEXER_URL = process.env.ZEROG_STORAGE_INDEXER || 'https://indexer-storage-testnet-turbo.0g.ai';
export const CHAIN_ID = 16602n;
// Dedicated storage-fee wallet for this tool only (never a personal wallet). Created by new-wallet.mjs.
export const KEY_FILE = new URL('../../../.secrets/zerog-storage.key', import.meta.url);
