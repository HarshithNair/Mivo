// Create a dedicated 0G testnet wallet that pays storage fees. Prints only the PUBLIC address.
import {Wallet} from 'ethers';
import {existsSync, mkdirSync, writeFileSync, readFileSync} from 'node:fs';
import {KEY_FILE} from './config.mjs';
const dir = new URL('.', KEY_FILE);
if (existsSync(KEY_FILE)) { console.log('Exists. Address:', new Wallet(readFileSync(KEY_FILE, 'utf8').trim()).address); process.exit(0); }
mkdirSync(dir, {recursive: true, mode: 0o700});
const w = Wallet.createRandom();
writeFileSync(KEY_FILE, w.privateKey + '\n', {mode: 0o600});
writeFileSync(new URL('zerog-storage.address', dir), w.address + '\n');
console.log('Created (key saved to .secrets/, git-ignored). Fund this address with 0G testnet tokens:', w.address);
