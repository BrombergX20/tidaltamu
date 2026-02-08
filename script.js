const API_BASE = "http://ec2-44-243-17-123.us-west-2.compute.amazonaws.com:8000"

document.addEventListener('DOMContentLoaded', () => {
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav a').forEach(link => {
    if(link.getAttribute('href') === currentPage) link.classList.add('active');
  });
  
  // Auto-run logic based on page
  if(document.getElementById('savedList')) {
    refreshSavedList();
    // Auto-refresh saved list every 30 seconds to pick up new tags
    setInterval(refreshSavedList, 30000);
  }
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

  ul.innerHTML = '<li style="color:white">Loading files...</li>';

  try {
    const resp = await fetch(API_BASE + '/list_docs');
    const files = await resp.json();
    ul.innerHTML = ''; 

    if (files.length === 0) {
      ul.innerHTML = '<li style="color:gray">No files found. Upload new files to see tags.</li>';
      return;
    }

    files.forEach(f => {
      const li = document.createElement('li');
      
      // --- LEFT SIDE: Name + Tags ---
      const left = document.createElement('div');
      
      // 1. Filename
      const title = document.createElement('div');
      title.textContent = f.name;
      title.style.fontWeight = 'bold';
      title.style.color = 'white';
      
      // 2. Tags (NEW)
      const meta = document.createElement('div');
      meta.style.fontSize = '12px';
      if (f.tags && f.tags.length > 0) {
          meta.style.color = '#4ea8ff'; // Blue
          meta.textContent = "Tags: " + f.tags.join(', ');
      } else {
          // Check if file is audio/video (likely being processed)
          const isAudioOrVideo = /\.(mp3|wav|mp4|mov|avi|mkv|aac)$/i.test(f.name);
          if (isAudioOrVideo) {
              meta.style.color = '#ffaa00'; // Orange for "processing"
              meta.textContent = "⏳ Processing tags (audio/video can take 5-15 minutes)...";
          } else {
              meta.style.color = '#777';
              meta.textContent = "No tags";
          }
      }
      
      left.appendChild(title);
      left.appendChild(meta);

      // --- RIGHT SIDE: Buttons ---
      const right = document.createElement('div');
      right.style.display = 'flex';
      right.style.alignItems = 'center';

      // 1. View Button
      const btn = document.createElement('button');
      btn.textContent = 'View';
      btn.style.padding = '5px 15px';
      btn.style.cursor = 'pointer';
      btn.style.marginRight = '10px';
      btn.onclick = () => window.open(f.url, '_blank');

      // 2. Delete Button (RESTORED)
      const removeBtn = document.createElement('button');
      removeBtn.textContent = 'Delete';
      removeBtn.style.background = '#ff4444';
      removeBtn.style.color = 'white';
      removeBtn.style.border = 'none';
      removeBtn.style.padding = '5px 10px';
      removeBtn.style.cursor = 'pointer';
      
      removeBtn.onclick = async () => {
        if(!confirm(`Remove "${f.name}" from cloud?`)) return;
        try{
          const resp = await fetch(API_BASE + '/delete_doc', { 
            method: 'POST', 
            headers: {'Content-Type':'application/json'}, 
            body: JSON.stringify({ key: f.key }) 
          });
          const j = await resp.json();
          if(j && j.success || resp.ok){ // Handle flexible success response
            li.remove();
          } else {
            alert('Failed to remove file.');
          }
        }catch(err){
          console.error('Delete error', err);
          alert('Error deleting file');
        }
      };

      right.appendChild(btn);
      right.appendChild(removeBtn);

      li.appendChild(left);
      li.appendChild(right);
      ul.appendChild(li);
    });

  } catch (err) {
    console.error(err);
    ul.innerHTML = `<li style="color:red">Error loading list. Is server running?</li>`;
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