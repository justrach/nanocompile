import { readFileSync, mkdirSync, writeFileSync, appendFileSync } from 'node:fs';
const greeting = readFileSync('greeting.txt', 'utf8').trim();
mkdirSync('dist', { recursive: true });
writeFileSync('dist/message.json', JSON.stringify({ greeting }) + '\n');
if (process.env.NANO_TURBO_EXECUTION_LOG) appendFileSync(process.env.NANO_TURBO_EXECUTION_LOG, 'message\n');
console.log('Built message');
