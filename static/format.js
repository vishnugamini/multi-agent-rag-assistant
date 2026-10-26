// Remove obsolete source boilerplate from previously saved answers as well.
export function cleanAnswerText(text) {
  return text.replace(/\[[^\]\n]*(?:general knowledge|exact-source-id)[^\]\n]*\]/gi,'')
    .replace(/\([^()]*general knowledge response[^()]*\)/gi,'')
    .replace(/^\s*Answer:\s*/i,'').trim();
}
// Small, DOM-only formatting renderer. No HTML from model output is interpreted.
function inline(element, text, sources) {
  const pattern=/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]\n]+\])/g;
  let offset=0;
  for(const match of text.matchAll(pattern)) {
    element.append(document.createTextNode(text.slice(offset,match.index)));
    const token=match[0];let child;
    if(token.startsWith('**')) {child=document.createElement('strong');child.textContent=token.slice(2,-2);}
    else if(token.startsWith('`')) {child=document.createElement('code');child.textContent=token.slice(1,-1);}
    else {
      const source=sources.find(s=>s.id===token.slice(1,-1));
      if(source) {child=document.createElement('button');child.className='inline-citation';child.textContent=String(sources.indexOf(source)+1);child.title=source.title||source.id;child.onclick=()=>element.closest('.message').querySelectorAll('.source-buttons button')[sources.indexOf(source)]?.click();}
      else {child=document.createTextNode(token);}
    }
    element.append(child);offset=match.index+token.length;
  }
  element.append(document.createTextNode(text.slice(offset)));
}
export function formatAnswer(element, text, sources=[]) {
  element.replaceChildren();element.classList.add('formatted');
  const lines=cleanAnswerText(text).split('\n');let code=null,list=null,table=null;
  for(const line of lines) {
    if(line.startsWith('```')) {
      if(code)code=null;
      else {const pre=document.createElement('pre');code=document.createElement('code');pre.append(code);element.append(pre);}
      list=null;table=null;continue;
    }
    if(code){code.textContent+=line+'\n';continue;}
    if(/^\s*\|.*\|\s*$/.test(line)) {
      if(/^\s*\|[\s:|\-]+\|\s*$/.test(line))continue;
      if(!table){table=document.createElement('table');element.append(table);}
      const row=document.createElement('tr');
      for(const cell of line.trim().slice(1,-1).split('|')){const td=document.createElement('td');inline(td,cell.trim(),sources);row.append(td);}
      table.append(row);continue;
    }
    table=null;
    const heading=line.match(/^(#{1,4})\s+(.+)/),bullet=line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);
    if(heading){const h=document.createElement('h'+Math.min(4,heading[1].length+1));inline(h,heading[2],sources);element.append(h);list=null;}
    else if(bullet){if(!list){list=document.createElement('ul');element.append(list);}const li=document.createElement('li');inline(li,bullet[1],sources);list.append(li);}
    else if(line.trim()){list=null;const p=document.createElement('p');inline(p,line,sources);element.append(p);}
    else list=null;
  }
}
