// Local Anvil only. No public-network transaction submission is allowed here.
import {readFile,writeFile} from 'node:fs/promises';
import {createWalletClient,createPublicClient,http,parseEther,keccak256,toBytes} from 'viem';
import {privateKeyToAccount,generatePrivateKey} from 'viem/accounts';
import {foundry} from 'viem/chains';
const transport=http('http://127.0.0.1:8547');const publicClient=createPublicClient({chain:foundry,transport});
if(await publicClient.getChainId()!==31337)throw Error('Local chain required');
const buyer=privateKeyToAccount((await readFile('.secrets/testnet-wallet.key','utf8')).trim());
const signer=privateKeyToAccount((await readFile('.secrets/quote-signer.key','utf8')).trim());
const merchant=privateKeyToAccount(generatePrivateKey());
const wallet=createWalletClient({account:buyer,chain:foundry,transport});
await publicClient.request({method:'anvil_setBalance',params:[buyer.address,'0x'+parseEther('10').toString(16)]});
const mock=JSON.parse(await readFile('contracts/out/MivoSettlement.t.sol/MockUSD.json','utf8'));
const artifact=JSON.parse(await readFile('contracts/out/MivoSettlement.sol/MivoSettlement.json','utf8'));
async function receipt(hash){const r=await publicClient.waitForTransactionReceipt({hash});if(r.status!=='success')throw Error('Transaction failed');return r;}
const token=(await receipt(await wallet.deployContract({abi:mock.abi,bytecode:mock.bytecode.object}))).contractAddress;
const contract=(await receipt(await wallet.deployContract({abi:artifact.abi,bytecode:artifact.bytecode.object,args:[token,signer.address,1000_000000n]}))).contractAddress;
await receipt(await wallet.writeContract({address:token,abi:mock.abi,functionName:'mint',args:[buyer.address,500_000000n]}));
await receipt(await wallet.writeContract({address:token,abi:mock.abi,functionName:'approve',args:[contract,129_000000n]}));
const block=await publicClient.getBlock();
const authorization={quoteId:keccak256(toBytes('mivo-local-'+Date.now())),buyer:buyer.address,merchant:merchant.address,amount:129_000000n,nonce:1n,deadline:block.timestamp+600n};
const signature=await signer.signTypedData({domain:{name:'MivoSettlement',version:'1',chainId:31337,verifyingContract:contract},types:{Authorization:[{name:'quoteId',type:'bytes32'},{name:'buyer',type:'address'},{name:'merchant',type:'address'},{name:'amount',type:'uint256'},{name:'nonce',type:'uint256'},{name:'deadline',type:'uint256'}]},primaryType:'Authorization',message:authorization});
const result=await receipt(await wallet.writeContract({address:contract,abi:artifact.abi,functionName:'settle',args:[authorization,signature]}));
await publicClient.request({method:'anvil_mine',params:['0x2']});
const balance=await publicClient.readContract({address:token,abi:mock.abi,functionName:'balanceOf',args:[merchant.address]});
if(balance!==authorization.amount)throw Error('Merchant did not receive exact amount');
await writeFile('docs/local-settlement.json',JSON.stringify({network:'local-anvil-only',chain_id:31337,contract_address:contract,token_address:token,buyer_address:buyer.address,merchant_address:merchant.address,quote_hash:authorization.quoteId,token_amount:authorization.amount.toString(),nonce:'1',expires:Number(authorization.deadline),transaction_hash:result.transactionHash,block_number:Number(result.blockNumber)},null,2)+'\n');
console.log('PASS: local deployment, EIP-712 authorization, exact ERC20 settlement and merchant balance. Public receipt: docs/local-settlement.json');
