import type {Metadata} from 'next';
import {Providers} from '@/components/providers';
import './globals.css';
export const metadata:Metadata={title:'mivo. — Your AI. Your deal.',description:'Discover products, negotiate with merchant AI agents, and review your deal.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body><Providers>{children}</Providers></body></html>;}
