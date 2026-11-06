import type { NextConfig } from 'next';
const config:NextConfig={logging:{incomingRequests:false},async rewrites(){return [{source:'/api/:path*',destination:(process.env.API_ORIGIN || 'http://127.0.0.1:8137')+'/:path*'}]},async headers(){return [{source:'/:path*',headers:[{key:'X-Content-Type-Options',value:'nosniff'},{key:'X-Frame-Options',value:'DENY'},{key:'Referrer-Policy',value:'strict-origin-when-cross-origin'}]}]}};
export default config;
