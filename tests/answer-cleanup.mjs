import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync('static/format.js','utf8');
const {cleanAnswerText}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.equal(cleanAnswerText('[exact-source-id; general knowledge]\nAnswer: Hello! (General knowledge response—no source evidence was supplied for this session.)'),'Hello!');
assert.equal(cleanAnswerText('Evidence [doc-test::0000].'),'Evidence [doc-test::0000].');
console.log('Saved-answer cleanup passed');
