'use client';
import {motion,useReducedMotion} from 'motion/react';
export function Orb({small=false,thinking=false}:{small?:boolean;thinking?:boolean}){const reduced=useReducedMotion();return <motion.div role="img" aria-label={thinking?'Mivo is thinking':'Mivo, your friendly shopping assistant'} className={'orb '+(small?'small':'')} animate={reduced?{}:{y:[0,-12,0],rotate:[-4,4,-4]}} transition={{duration:4,repeat:Infinity,ease:'easeInOut'}}><div className="orb-face"><i/><i/></div><span className="orb-shine"/></motion.div>;}
