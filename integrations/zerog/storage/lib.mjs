import {Indexer, MemData} from '@0gfoundation/0g-storage-ts-sdk';
import {JsonRpcProvider, Wallet, formatEther} from 'ethers';
import {createHash} from 'node:crypto';
import {readFileSync, mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {RPC_URL, INDEXER_URL, CHAIN_ID, KEY_FILE} from './config.mjs';

export const sha256 = bytes => '0x' + createHash('sha256').update(bytes).digest('hex');

export async function signer() {
  const provider = new JsonRpcProvider(RPC_URL);
  const {chainId} = await provider.getNetwork();
  if (chainId !== CHAIN_ID) throw new Error(`RPC is chain ${chainId}, expected 0G testnet ${CHAIN_ID}`);
  const wallet = new Wallet(readFileSync(KEY_FILE, 'utf8').trim(), provider);
  const balance = await provider.getBalance(wallet.address);
  return {wallet, balance: formatEther(balance), funded: balance > 0n};
}

export async function upload(bytes, wallet) {
  const file = new MemData(bytes);
  const [tree, treeErr] = await file.merkleTree();
  if (treeErr) throw treeErr;
  const expectedRoot = tree.rootHash();
  const [result, err] = await new Indexer(INDEXER_URL).upload(file, RPC_URL, wallet);
  if (err) throw err;
  if (result.rootHash !== expectedRoot) throw new Error(`root mismatch ${result.rootHash} != ${expectedRoot}`);
  return {rootHash: result.rootHash, txHash: result.txHash};
}

// Download with Merkle proof verification, then compare content hashes.
export async function downloadVerified(rootHash, expectedSha256) {
  const path = join(mkdtempSync(join(tmpdir(), 'mivo-0g-')), 'evidence.json');
  const err = await new Indexer(INDEXER_URL).download(rootHash, path, true);
  if (err) throw err;
  const bytes = readFileSync(path);
  const got = sha256(bytes);
  return {bytes, sha256: got, ok: !expectedSha256 || got === expectedSha256};
}
