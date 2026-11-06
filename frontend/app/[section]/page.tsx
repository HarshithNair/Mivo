import {AppScreen} from '@/components/app-screen';
export default async function Page({params}:{params:Promise<{section:string}>}){const {section}=await params;return <AppScreen section={section}/>;}
