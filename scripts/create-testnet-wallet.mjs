import {mkdir,writeFile,access} from 'node:fs/promises';
import {generatePrivateKey,privateKeyToAccount} from 'viem/accounts';
const directory=new URL('../.secrets/',import.meta.url);
await mkdir(directory,{recursive:true,mode:0o700});
for(const name of ['testnet-wallet','quote-signer']){
 const keyFile=new URL(name+'.key',directory);
 try{await access(keyFile);console.log(name+': already exists; preserved');continue;}catch{}
 const key=generatePrivateKey();const account=privateKeyToAccount(key);
 await writeFile(keyFile,key+'\n',{mode:0o600,flag:'wx'});
 await writeFile(new URL(name+'.address',directory),account.address+'\n',{mode:0o600,flag:'wx'});
 console.log(name+' public address: '+account.address);
}
