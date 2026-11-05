import {rollup} from 'rollup';
import configuration from './rollup.config.js';
try {
 for(const config of (Array.isArray(configuration)?configuration:[configuration])){
  const {output,...input}=config;
  const bundle=await rollup(input);
  for(const settings of (Array.isArray(output)?output:[output]))await bundle.write(settings);
  await bundle.close();
 }
 process.exit(0);
}catch(error){console.error(error);process.exit(1);}
