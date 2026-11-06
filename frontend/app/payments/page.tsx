import type {Metadata} from 'next';
import {BuyPayments} from '@/components/buy-payments';
export const metadata:Metadata={title:'Payments — mivo.',description:'Approve and track Raspberry Pi BUY payments in testnet USDC on Arc.'};
export default function Page(){return <BuyPayments/>;}
