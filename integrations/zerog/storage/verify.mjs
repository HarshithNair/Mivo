// node verify.mjs <root_hash> [expected_sha256]   download from 0G Storage with Merkle proof and check the hash
import {downloadVerified} from './lib.mjs';
const [root, expected] = process.argv.slice(2);
if (!root) { console.error('usage: node verify.mjs <root_hash> [expected_sha256]'); process.exit(1); }
const r = await downloadVerified(root, expected);
console.log('sha256', r.sha256, expected ? (r.ok ? 'MATCH' : 'MISMATCH') : '');
console.log(r.bytes.toString('utf8'));
process.exit(r.ok ? 0 : 2);
