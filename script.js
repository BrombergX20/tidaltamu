const STORAGE_PREFIX = 'tidal_file_';

function saveFile(name, content){
  const id = STORAGE_PREFIX + Date.now() + '_' + Math.random().toString(36).slice(2,8);
  const payload = {id, name, content, created: Date.now()};
  try{ localStorage.setItem(id, JSON.stringify(payload)); }catch(e){ alert('Failed to save file: ' + e.message); }
}

function loadAllFiles(){
  const files = [];
  for(let i=0;i<localStorage.length;i++){
    const key = localStorage.key(i);
    if(!key || !key.startsWith(STORAGE_PREFIX)) continue;
    try{ files.push(JSON.parse(localStorage.getItem(key))); }catch(e){ }
  }
  files.sort((a,b)=>b.created - a.created);
  return files;
}

function refreshSavedList(){
  const ul = document.getElementById('savedList');
  if(!ul) return;
  ul.innerHTML = '';
  const files = loadAllFiles();
  if(files.length===0){ ul.innerHTML = '<li class="meta">No files saved yet.</li>'; return; }
  files.forEach(f=>{
    const li = document.createElement('li');

    const preview = document.createElement('div');
    preview.className = 'preview-box';
    if(f.content && typeof f.content === 'string' && f.content.startsWith('data:image/')){
      const img = document.createElement('img'); img.src = f.content; img.alt = f.name || 'preview';
      preview.appendChild(img);
    } else {
      const txt = document.createElement('div'); txt.className = 'preview-text';
      txt.textContent = f.content ? f.content.slice(0,160).replace(/\s+/g,' ') : f.name;
      preview.appendChild(txt);
    }

    const info = document.createElement('div'); info.style.flex='1'; info.style.display='flex'; info.style.flexDirection='column';
    const nameSpan = document.createElement('div'); nameSpan.textContent = f.name; nameSpan.style.fontWeight='600';
    const meta = document.createElement('div'); meta.className='meta'; meta.textContent = new Date(f.created).toLocaleString();
    info.appendChild(nameSpan); info.appendChild(meta);

    const right = document.createElement('div'); right.style.display='flex'; right.style.gap='8px';
    const viewBtn = document.createElement('button'); viewBtn.textContent='View'; viewBtn.onclick = ()=>{ showPreview(f); };
    const delBtn = document.createElement('button'); delBtn.textContent='Delete'; delBtn.style.background='#e02424'; delBtn.onclick = ()=>{ if(confirm('Delete "'+f.name+'"?')){ localStorage.removeItem(f.id); refreshSavedList(); refreshSearchResults(); }};
    right.appendChild(viewBtn); right.appendChild(delBtn);

    li.appendChild(preview);
    li.appendChild(info);
    li.appendChild(right);
    ul.appendChild(li);
  });
}

function showPreview(f){
  const w = window.open('about:blank','_blank');
  w.document.title = f.name;
  const pre = w.document.createElement('pre'); pre.textContent = f.content; pre.style.whiteSpace='pre-wrap'; pre.style.fontFamily='system-ui,monospace';
  w.document.body.appendChild(pre);
}

function refreshSearchResults(query){
  const searchElem = document.getElementById('searchInput');
  const ul = document.getElementById('searchResults');
  if(!ul || !searchElem) return;
  const q = (query||searchElem.value||'').toLowerCase().trim();
  ul.innerHTML='';
  const files = loadAllFiles();
  const filtered = files.filter(f=> f.name.toLowerCase().includes(q) || f.content.toLowerCase().includes(q));
  if(q===''){ ul.innerHTML = '<li class="meta">Type to search filenames and file contents.</li>'; return; }
  if(filtered.length===0){ ul.innerHTML = '<li class="meta">No matches found.</li>'; return; }
  filtered.forEach(f=>{
    const li = document.createElement('li');
    const left = document.createElement('div'); left.style.flex='1';
    const title = document.createElement('div'); title.textContent = f.name; title.style.fontWeight='1800';
    const snippet = document.createElement('div'); snippet.className='meta'; snippet.textContent = f.content.slice(0,250).replace(/\s+/g,' ');
    left.appendChild(title); left.appendChild(snippet);
    const btn = document.createElement('button'); btn.textContent='View'; btn.onclick = ()=> showPreview(f);
    li.appendChild(left); li.appendChild(btn);
    ul.appendChild(li);
  });
}

document.addEventListener('DOMContentLoaded', ()=>{
  const uploadForm = document.getElementById('uploadForm');
  const fileInput = document.getElementById('fileInput');
  if(uploadForm && fileInput){
    uploadForm.addEventListener('submit', (e)=>{
      e.preventDefault();
      const files = fileInput.files;
      if(!files || files.length===0) return alert('Select at least one file');
      let count=0;
      Array.from(files).forEach(file=>{
        const reader = new FileReader();
        reader.onload = (ev)=>{ saveFile(file.name, String(ev.target.result)); count++; if(count===files.length){ refreshSavedList(); alert('Saved '+count+' file(s) to browser.'); }};
        // For images, keep a data URL so we can render an image preview; otherwise read as text
        try{
          if(file.type && file.type.startsWith('image/')){
            reader.readAsDataURL(file);
          } else {
            reader.readAsText(file);
          }
        }catch(err){ reader.readAsText(file); }
      });
      fileInput.value='';
    });
  }

  const searchInput = document.getElementById('searchInput');
  if(searchInput){
    searchInput.addEventListener('input',(e)=> refreshSearchResults(e.target.value));
    refreshSearchResults('');
  }

  if(document.getElementById('savedList')) refreshSavedList();
});

