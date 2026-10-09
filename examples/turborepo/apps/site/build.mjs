import { readFileSync, mkdirSync, writeFileSync, appendFileSync } from 'node:fs';
const { greeting } = JSON.parse(readFileSync('../../packages/message/dist/message.json', 'utf8'));
const escape = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
mkdirSync('dist', { recursive: true });
writeFileSync('dist/index.html', `<!doctype html><title>Task cache example</title><h1>${escape(greeting)}</h1><p>${escape(process.env.EXAMPLE_LABEL ?? 'demo')}</p>\n`);
if (process.env.NANO_TURBO_EXECUTION_LOG) appendFileSync(process.env.NANO_TURBO_EXECUTION_LOG, 'site\n');
console.log('Built site');
