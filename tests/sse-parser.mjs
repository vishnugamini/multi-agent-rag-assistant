import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync('static/app.js','utf8');
const parser=source.slice(source.indexOf('export function parseSSE'),source.indexOf('async function submit')).replace('export ','');
const context={};vm.runInNewContext(parser,context);
let checks=0;
for(const newline of ['\n','\r\n']) {
 const frames=[': heartbeat','','event: answer_delta','data: {"type":"answer_delta","text":"héllo 🌲"}','','event: done','data: {"type":"done"}','',''].join(newline);
 // Every possible packet split, including splits inside CRLF and a JSON value.
 for(let split=0;split<=frames.length;split++) {
  let buffer='',events=[];
  for(const packet of [frames.slice(0,split),frames.slice(split)]) buffer=context.parseSSE(buffer+packet,e=>events.push(e));
  assert.deepEqual(JSON.parse(JSON.stringify(events)),[{type:'answer_delta',text:'héllo 🌲'},{type:'done'}]);
  assert.equal(buffer,'');checks++;
 }
}
let bytes=new TextEncoder().encode('data: {"text":"é🌲"}\n\n'),decoder=new TextDecoder(),buffer='',events=[];
for(const byte of bytes) buffer=context.parseSSE(buffer+decoder.decode(new Uint8Array([byte]),{stream:true}),e=>events.push(e));
assert.equal(events[0].text,'é🌲');
console.log(JSON.stringify({passed:true,packet_split_checks:checks,utf8_byte_split:true}));
