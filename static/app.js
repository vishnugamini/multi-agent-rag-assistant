import {formatAnswer} from './format.js';
const $ = id => document.getElementById(id);
let conversation = localStorage.getItem('agentic.conversation');
let busy = false, currentAnswer, currentSources, traceCount = 0, answerText='', answerSources=[];
const safeURL = value => {try {const u = new URL(value);return ['https:', 'http:'].includes(u.protocol) ? u.href : null;} catch {return null;}};

function message(role, text='') {
  const node=document.createElement('article'); node.className=`message ${role}`;
  const label=document.createElement('div');label.className='message-role';label.textContent=role==='user'?'You':'Agentic';
  const body=document.createElement('div');body.className='message-body';body.textContent=text;
  const sources=document.createElement('div');sources.className='source-buttons';
  node.append(label,body,sources);$('messages').append(node);
  return {body,sources};
}
function trace(event) {
  if (!$('trace').querySelector('details')) $('trace').replaceChildren();
  const item=document.createElement('details');item.className='trace-item';
  const title=document.createElement('summary');
  title.textContent=`${event.agent||event.server||'System'} · ${event.type.replaceAll('_',' ')}${event.tool?' / '+event.tool:''}`;
  const time=document.createElement('time');time.textContent=new Date(event.timestamp).toLocaleTimeString();
  const pre=document.createElement('pre');pre.textContent=JSON.stringify(event,null,2);
  item.append(title,time,pre);$('trace').append(item);$('activity-count').textContent=++traceCount;
}
function sourceButtons(sources, target) {
  target.replaceChildren();
  for (const source of sources) {
    const b=document.createElement('button');b.textContent=source.title||source.id;b.title=source.id;
    b.onclick=async()=>{
      let full=source;
      if (!source.text && source.id.startsWith('doc-')) {
        const response=await fetch('/api/sources/'+encodeURIComponent(source.id));
        if(response.ok) full=await response.json();
      }
      $('source-title').textContent=full.title||full.id;$('source-text').textContent=full.text||'No excerpt available.';
      const url=safeURL(full.url);$('source-link').hidden=!url;
      if(url)$('source-link').href=url;
      $('source-dialog').showModal();
    };target.append(b);
  }
}
function handle(event) {
  if(event.type==='answer_delta') {answerText+=event.text;currentAnswer.textContent=answerText;return;}
  trace(event);
  if(event.type==='turn_started') {conversation=event.conversation_id;localStorage.setItem('agentic.conversation',conversation);}
  if(event.type==='answer_reset') {answerText='';currentAnswer.textContent='';$('status').textContent=event.reason;}
  if(event.type==='routing_decision') {
    const card=document.createElement('div');card.className='route-card';
    const title=document.createElement('strong');title.textContent=`${event.agent} → ${event.model}`;
    const text=document.createElement('p');text.textContent=event.reason;card.append(title,text);$('routing').append(card);
  }
  if(event.type==='provider_fallback')$('status').textContent='NVIDIA unavailable. Continuing with OpenAI.';
  if(event.type==='agent_started')$('status').textContent=`${event.agent} is working…`;
  if(event.type==='citations') {answerSources=event.sources;sourceButtons(event.sources,currentSources);formatAnswer(currentAnswer,answerText,answerSources);}
  if(event.type==='metrics') {
    const cost=event.calls.filter(x=>x.estimated_usd!=null).reduce((s,x)=>s+x.estimated_usd,0);
    $('metrics').textContent=`First token ${event.ttft_seconds??'—'}s · Total ${event.total_seconds}s\n${event.calls.length} model attempts · ${event.fallback?'OpenAI fallback used':'Normal routing'}\nRecorded estimate $${cost.toFixed(5)}`;
    $('metrics').title='Estimate excludes unavailable usage and charges from other services.';
  }
  if(event.type==='done') {formatAnswer(currentAnswer,answerText,answerSources);$('status').textContent='';}
  if(event.type==='error') {$('status').textContent=event.message+' This turn was not saved.'; if(!currentAnswer.textContent) currentAnswer.textContent='The request could not be completed.';}
}

// SSE framing independent of network packet boundaries; comments are heartbeats.
export function parseSSE(buffer, consume) {
  buffer=buffer.replaceAll('\r\n','\n');let boundary;
  while((boundary=buffer.indexOf('\n\n'))!==-1) {
    const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
    const data=frame.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trimStart()).join('\n');
    if(data)consume(JSON.parse(data));
  }return buffer;
}
async function submit(event) {
  event.preventDefault();const query=$('query').value.trim();if(!query||busy)return;
  busy=true;$('send').disabled=true;message('user',query);
  const answer=message('assistant');currentAnswer=answer.body;currentSources=answer.sources;
  answerText='';answerSources=[];
  const payload={query,conversation_id:conversation};
  $('query').value='';
  $('routing').replaceChildren();$('trace').replaceChildren();$('metrics').textContent='';traceCount=0;
  $('status').textContent='Working…';let terminal=false;
  try {
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok)throw Error(`Request rejected (${response.status})`);
    const reader=response.body.getReader(), decoder=new TextDecoder();let buffer='';
    while(true) {const {value,done}=await reader.read();if(done)break;
      buffer+=decoder.decode(value,{stream:true});buffer=parseSSE(buffer,e=>{handle(e);if(['done','error'].includes(e.type))terminal=true;});
    }
    buffer+=decoder.decode();parseSSE(buffer,e=>{handle(e);if(['done','error'].includes(e.type))terminal=true;});
    if(!terminal)throw Error('Stream interrupted. This turn may be incomplete; reload before retrying.');
  } catch(error) {$('status').textContent=error.message;}
  finally {busy=false;$('send').disabled=false;$('query').focus();}
}
$('chat-form').addEventListener('submit',submit);
$('query').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('chat-form').requestSubmit();}});
$('new-chat').onclick=()=>{if(busy)return;conversation=null;localStorage.removeItem('agentic.conversation');$('messages').replaceChildren();$('trace').replaceChildren();$('routing').replaceChildren();$('metrics').textContent='';$('status').textContent='';$('activity-count').textContent='';};
$('close-source').onclick=()=>$('source-dialog').close();
async function init(){
  if(conversation)try {const r=await fetch('/api/conversations/'+encodeURIComponent(conversation));if(!r.ok)throw Error();const state=await r.json();
    for(const m of state.messages||[])message(m.role,m.content);
    const last=state.turns?.at(-1);if(last){for(const e of last.trace||[]) {
      if(e.type==='routing_decision') {
        const card=document.createElement('div');card.className='route-card';
        const title=document.createElement('strong');title.textContent=`${e.agent} → ${e.model}`;
        const reason=document.createElement('p');reason.textContent=e.reason;card.append(title,reason);$('routing').append(card);
      }
      trace(e);
    }}
    // Reattach saved source cards to their corresponding assistant messages.
    const assistants=[...$('messages').querySelectorAll('.message.assistant .source-buttons')];
    (state.turns||[]).forEach((t,i)=>{if(assistants[i]){sourceButtons(t.sources||[],assistants[i]);const body=assistants[i].previousElementSibling;formatAnswer(body,body.textContent,t.sources||[]);}});
  }catch{$('status').textContent='Could not restore conversation. Retry or start a new one.';}
}init();
