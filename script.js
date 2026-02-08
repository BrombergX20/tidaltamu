// const API_BASE = (typeof window !== 'undefined' && (window.API_BASE || window.__API_BASE__)) ? (window.API_BASE || window.__API_BASE__) : '';
const API_BASE = "http://ec2-44-243-17-123.us-west-2.compute.amazonaws.com:8000"

document.addEventListener('DOMContentLoaded', () => {
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav a').forEach(link => {
    if(link.getAttribute('href') === currentPage) link.classList.add('active');
  });
  
  // Auto-run logic based on page
  if(document.getElementById('savedList')) refreshSavedList();
  if(document.getElementById('uploadForm')) setupUpload();
  
  // NEW: Search Logic
  const searchInput = document.getElementById('searchInput');
  if(searchInput){
    searchInput.addEventListener('input', (e) => refreshSearchResults(e.target.value));
  }
});

// 2. Upload Logic
function setupUpload() {
  const form = document.getElementById('uploadForm');
  const fileInput = document.getElementById('fileInput');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const files = fileInput.files;
    if(files.length === 0) return alert("Please select a file.");

    for(const file of files) {
      const fd = new FormData();
      fd.append('file', file);
      
      // Auto-detect extension (pdf, mp3, etc)
      const ext = file.name.split('.').pop().toLowerCase();
      fd.append('type', ext);

      try {
        const resp = await fetch(API_BASE + '/add_doc', { method: 'POST', body: fd });
        if(!resp.ok) throw new Error("Upload Failed");
        console.log("Uploaded:", file.name);
      } catch(err) {
        alert(`Error uploading ${file.name}`);
        console.error(err);
      }
    }
    alert("Upload(s) Complete!");
    fileInput.value = ''; // Reset input
  });
}

// 3. Saved Files Logic (The Viewer)
async function refreshSavedList() {
  const ul = document.getElementById('savedList');
  if (!ul) return;

  ul.innerHTML = '<li style="color:white">Loading files from Cloud...</li>';

  try {
    const resp = await fetch(API_BASE + '/list_docs');
    const files = await resp.json();
    ul.innerHTML = ''; // Clear loading text

    if (files.length === 0) {
      ul.innerHTML = '<li style="color:gray">No files found in bucket.</li>';
      return;
    }

    files.forEach(f => {
      const li = document.createElement('li');
      
      // File Info Area
      const left = document.createElement('div');
      const title = document.createElement('div');
      title.textContent = f.name;
      title.style.fontWeight = 'bold';
      title.style.color = 'white';
      
      const meta = document.createElement('div');
      meta.style.fontSize = '12px';
      meta.style.color = '#aaa';
      meta.textContent = `Size: ${(f.size / 1024).toFixed(1)} KB`;
      
      left.appendChild(title);
      left.appendChild(meta);

      // View Button
      const btn = document.createElement('button');
      btn.textContent = 'View';
      btn.style.padding = '5px 15px';
      btn.style.cursor = 'pointer';
      btn.onclick = () => window.open(f.url, '_blank');

      // Remove Button: deletes from S3 and localStorage
      const removeBtn = document.createElement('button');
      removeBtn.textContent = 'Remove';
      removeBtn.style.marginLeft = '8px';
      removeBtn.style.padding = '5px 12px';
      removeBtn.style.background = '#e02424';
      removeBtn.style.color = 'white';
      removeBtn.style.cursor = 'pointer';
      removeBtn.onclick = async () => {
        if(!confirm(`Remove "${f.name}" from cloud?`)) return;
        try{
          const resp = await fetch(API_BASE + '/delete_doc', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ key: f.key }) });
          const j = await resp.json();
          if(j && j.success){
            try{ removeLocalEntriesMatching(f); }catch(e){}
            li.remove();
          } else {
            alert('Failed to remove file: '+ (j && j.error ? j.error : 'unknown'));
          }
        }catch(err){
          console.error('Delete error', err);
          alert('Error deleting file');
        }
      };

      // Buttons container
      const btnContainer = document.createElement('div');
      btnContainer.style.display = 'flex';
      btnContainer.style.gap = '8px';
      btnContainer.style.marginLeft = 'auto';
      btnContainer.appendChild(btn);
      btnContainer.appendChild(removeBtn);

      li.appendChild(left);
      li.appendChild(btnContainer);
      ul.appendChild(li);
    });

  } catch (err) {
    console.error(err);
    ul.innerHTML = `<li style="color:red">Connection Error. Is Server running?</li>`;
  }
}

// 4. Search Logic (UPDATED to use Backend API)
async function refreshSearchResults(query) {
  const ul = document.getElementById('searchResults');
  if(!ul) return;
  
  if (!query) { 
      ul.innerHTML = ''; 
      return; 
  }

  try {
      // Call the new Python Search API
      const resp = await fetch(`${API_BASE}/search?q=${query}`);
      const files = await resp.json();
      
      ul.innerHTML = '';
      
      if(files.length === 0) {
           ul.innerHTML = '<li style="color:gray">No matches found.</li>';
           return;
      }

      files.forEach(f => {
          const li = document.createElement('li');
          
          // Name + Tags
          const left = document.createElement('div');
          
          const title = document.createElement('div');
          title.textContent = f.original_name || f.name; // Fallback if original_name missing
          title.style.fontWeight = 'bold';
          title.style.color = 'white';
          
          const tags = document.createElement('div');
          tags.style.color = '#4ea8ff';
          tags.style.fontSize = '12px';
          // Join the AI tags with commas
          tags.textContent = (f.tags && f.tags.length > 0) ? "Tags: " + f.tags.join(', ') : "No tags";
          
          left.appendChild(title);
          left.appendChild(tags);

          // View Button
          const btn = document.createElement('button');
          btn.textContent = 'View';
          btn.style.marginLeft = 'auto'; 
          btn.style.padding = '5px 15px';
          btn.style.cursor = 'pointer';
          btn.onclick = () => window.open(f.url, '_blank');

          li.appendChild(left);
          li.appendChild(btn);
          ul.appendChild(li);
      });
  } catch(err) {
      console.error(err);
      ul.innerHTML = '<li style="color:red">Search Error</li>';
  }
}

function removeLocalEntriesMatching(f){
  const STORAGE_PREFIX = 'tidal_file_';
  for(let i=localStorage.length-1;i>=0;i--){
    const key = localStorage.key(i);
    if(!key || !key.startsWith(STORAGE_PREFIX)) continue;
    try{
      const rec = JSON.parse(localStorage.getItem(key));
      if(!rec) continue;
      if((f.url && rec.url && rec.url === f.url) || (rec.name && rec.name === f.name)){
        localStorage.removeItem(key);
      }
    }catch(e){ }
  }
}