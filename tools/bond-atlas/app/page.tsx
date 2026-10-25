"use client";
import {useState} from 'react';
import EuroDashboard from '@/components/euro-dashboard';
import GlobalDashboard from '@/components/global-dashboard';
export default function Home(){
 const [view,setView]=useState('euro');
 return <><header className="topbar"><a className="brand" href="/"><span className="brand-mark">↗</span><b>Bond Atlas</b></a><nav className="view-nav" aria-label="Vista dell'osservatorio"><button aria-pressed={view==='euro'} onClick={()=>setView('euro')}>Titoli in euro</button><button aria-pressed={view==='global'} onClick={()=>setView('global')}>Curve globali</button></nav><a className="pill method-link" href={view==='euro'?'#euro-method':'#method'}>Metodo e fonti ↗</a></header>{view==='euro'?<EuroDashboard/>:<GlobalDashboard/>}</>;
}
