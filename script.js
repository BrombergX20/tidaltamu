// const API_BASE = (typeof window !== 'undefined' && (window.API_BASE || window.__API_BASE__)) ? (window.API_BASE || window.__API_BASE__) : '';
const API_BASE = "http://ec2-44-243-17-123.us-west-2.compute.amazonaws.com:8000"

// Highlight active nav tab
document.addEventListener('DOMContentLoaded', () => {
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  const navLinks = document.querySelectorAll('.nav a');
  navLinks.forEach(link => {
    const href = link.getAttribute('href');
    if(href === currentPage || (currentPage === '' && href === 'index.html')){
      link.classList.add('active');
    }
  });
});

async function saveFileToServer(file){
  console.log(API_BASE);
  const fd = new FormData();
  fd.append('file', file, file.name);
  // attach detected file type so FastAPI's `type: Form(...)` receives it
  const mt = (file.name || '').match(/\.([^.]+)$/);
  const fileExt = mt ? mt[1].toLowerCase() : '';
  fd.append('type', fileExt);
  const resp = await fetch(API_BASE + '/add_doc', { method: 'POST', body: fd });
  const ct = resp.headers.get('content-type') || '';
  const bodyText = await resp.text();
  if(!resp.ok){
    throw new Error(`Upload failed (${resp.status}): ${bodyText}`);
  }
  if(!ct.includes('application/json')){
    throw new Error('Expected JSON response but received HTML/text: ' + bodyText);
  }
  try{
    return JSON.parse(bodyText);
  }catch(err){
    throw new Error('Failed to parse JSON response: ' + bodyText);
  }
}

async function loadAllFiles(){
  // Try server first
  try{
    const resp = await fetch(API_BASE + '/files');
    if(!resp.ok) throw new Error('Failed to fetch files');
    const data = await resp.json();
    // normalize to expected fields
    return data.map(d=>({ id: d.key, name: d.name || d.key, url: d.url || '', created: d.last_modified || Date.now(), size: d.size || 0 }));
  }catch(err){
    // fallback to localStorage (offline)
    console.warn('Falling back to localStorage for files:', err);
    const STORAGE_PREFIX = 'tidal_file_';
    const files = [];
    for(let i=0;i<localStorage.length;i++){
      const key = localStorage.key(i);
      if(!key || !key.startsWith(STORAGE_PREFIX)) continue;
      try{ files.push(JSON.parse(localStorage.getItem(key))); }catch(e){ }
    }
    files.sort((a,b)=>b.created - a.created);
    return files;
  }
}

async function refreshSavedList(){
  const ul = document.getElementById('savedList');
  if(!ul) return;
  ul.innerHTML = '';
  const files = await loadAllFiles();
  if(files.length===0){ ul.innerHTML = '<li class="meta">No files saved yet.</li>'; return; }
  files.forEach(f=>{
    const li = document.createElement('li');

    const preview = document.createElement('div');
    preview.className = 'preview-box';
    if(f.url && (f.name.match(/\.(jpe?g|png|gif|webp)$/i))){
      const img = document.createElement('img'); img.src = f.url; img.alt = f.name || 'preview';
      preview.appendChild(img);
    } else {
      const txt = document.createElement('div'); txt.className = 'preview-text';
      txt.textContent = f.name;
      preview.appendChild(txt);
    }

    const info = document.createElement('div'); info.style.flex='1'; info.style.display='flex'; info.style.flexDirection='column';
    const nameSpan = document.createElement('div'); nameSpan.textContent = f.name; nameSpan.style.fontWeight='600';
    const meta = document.createElement('div'); meta.className='meta'; meta.textContent = f.created ? new Date(f.created).toLocaleString() : '';
    info.appendChild(nameSpan); info.appendChild(meta);

    const right = document.createElement('div'); right.style.display='flex'; right.style.gap='8px';
    const viewBtn = document.createElement('button'); viewBtn.textContent='View'; viewBtn.onclick = ()=>{ showPreview(f); };
    const delBtn = document.createElement('button'); delBtn.textContent='Delete'; delBtn.style.background='#e02424'; delBtn.onclick = ()=>{ if(confirm('Delete "'+f.name+'"?')){ alert('Deleting from S3 is not implemented in this demo.'); }};
    right.appendChild(viewBtn); right.appendChild(delBtn);

    li.appendChild(preview);
    li.appendChild(info);
    li.appendChild(right);
    ul.appendChild(li);
  });
}

function showPreview(f){
  if(f.url){
    window.open(f.url, '_blank');
    return;
  }
  const w = window.open('about:blank','_blank');
  w.document.title = f.name;
  const pre = w.document.createElement('pre'); pre.textContent = f.content || f.name; pre.style.whiteSpace='pre-wrap'; pre.style.fontFamily='system-ui,monospace';
  w.document.body.appendChild(pre);
}

async function refreshSearchResults(query){
  const searchElem = document.getElementById('searchInput');
  const ul = document.getElementById('searchResults');
  if(!ul || !searchElem) return;
  const q = (query||searchElem.value||'').toLowerCase().trim();
  ul.innerHTML='';
  const files = await loadAllFiles();
  const filtered = files.filter(f=> f.name.toLowerCase().includes(q));
  if(q===''){ ul.innerHTML = '<li class="meta">Type to search filenames and file contents.</li>'; return; }
  if(filtered.length===0){ ul.innerHTML = '<li class="meta">No matches found.</li>'; return; }
  filtered.forEach(f=>{
    const li = document.createElement('li');
    const left = document.createElement('div'); left.style.flex='1';
    const title = document.createElement('div'); title.textContent = f.name; title.style.fontWeight='1800';
    const snippet = document.createElement('div'); snippet.className='meta'; snippet.textContent = f.name;
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
    uploadForm.addEventListener('submit', async (e)=>{
      e.preventDefault();
      const files = fileInput.files;
      if(!files || files.length===0) return alert('Select at least one file');
      let count=0;
      for(const file of Array.from(files)){
        try{
          await saveFileToServer(file);
          count++;
        }catch(err){
          console.error('Upload failed', err);
          alert('Upload failed for '+file.name+': '+err.message);
        }
      }
      fileInput.value='';
      await refreshSavedList();
      alert('Uploaded '+count+' file(s) to server.');
    });
  }

  const searchInput = document.getElementById('searchInput');
  if(searchInput){
    searchInput.addEventListener('input',(e)=> refreshSearchResults(e.target.value));
    refreshSearchResults('');
  }

  if(document.getElementById('savedList')) refreshSavedList();
});

