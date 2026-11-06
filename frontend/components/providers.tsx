'use client';
import {useState} from 'react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {WagmiProvider,createConfig,http} from 'wagmi';
import {injected} from '@wagmi/core';
import {defineChain} from 'viem';
export const arc=defineChain({id:5042002,name:'Arc Testnet',nativeCurrency:{name:'USDC',symbol:'USDC',decimals:18},rpcUrls:{default:{http:['https://rpc.testnet.arc.io']}},blockExplorers:{default:{name:'Arc Explorer',url:'https://explorer.testnet.arc.io'}},testnet:true});
const config=createConfig({chains:[arc],connectors:[injected()],transports:{[arc.id]:http()},ssr:true});
export function Providers({children}:{children:React.ReactNode}){const [query]=useState(()=>new QueryClient());return <WagmiProvider config={config}><QueryClientProvider client={query}>{children}</QueryClientProvider></WagmiProvider>;}
