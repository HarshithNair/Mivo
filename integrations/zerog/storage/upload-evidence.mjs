// node upload-evidence.mjs <negotiation_id>
// Fetch sanitized evidence from MIVO, upload to 0G Storage, download with proof, verify hash, record the root.
// Env: MIVO_URL, MIVO_DEVICE_KEY
import {sha256, signer, upload, downloadVerified} from './lib.mjs';
const [nid] = process.argv.slice(2);
const {MIVO_URL, MIVO_DEVICE_KEY} = process.env;
if (!nid || !MIVO_URL || !MIVO_DEVICE_KEY) { console.error('usage: MIVO_URL=… MIVO_DEVICE_KEY=… node upload-evidence.mjs <negotiation_id>'); process.exit(1); }
const auth = {Authorization: `Bearer ${MIVO_DEVICE_KEY}`};

const r = await fetch(`${MIVO_URL.replace(/\/$/, '')}/api/device/zerog/evidence/${nid}`, {headers: auth});
if (!r.ok) throw new Error(`evidence fetch HTTP ${r.status}: ${await r.text()}`);
const {canonical, content_hash} = await r.json();
const bytes = Buffer.from(canonical, 'utf8');
if (sha256(bytes) !== content_hash) throw new Error('server content hash does not match canonical bytes');
console.log('evidence', bytes.length, 'bytes, sha256', content_hash);

const {wallet, balance, funded} = await signer();
console.log('storage wallet', wallet.address, 'balance', balance, '0G');
if (!funded) throw new Error('storage wallet has no 0G testnet tokens; fund it from the 0G faucet first');

const {rootHash, txHash} = await upload(bytes, wallet);
console.log('uploaded: root', rootHash, 'tx', txHash);
const check = await downloadVerified(rootHash, content_hash);
console.log('downloaded with Merkle proof: sha256', check.sha256, check.ok ? 'MATCH' : 'MISMATCH');
if (!check.ok) process.exit(2);

const s = await fetch(`${MIVO_URL.replace(/\/$/, '')}/api/device/zerog/evidence/${nid}/stored`, {
  method: 'POST', headers: {...auth, 'Content-Type': 'application/json'},
  body: JSON.stringify({content_hash, root_hash: rootHash, tx_hash: txHash, verified: true})});
console.log('recorded in MIVO:', s.status, await s.text());
