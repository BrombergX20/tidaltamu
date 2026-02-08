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
  
  // NEW: Quick search on saved files page
  const quickSearchInput = document.getElementById('quickSearchInput');
  if(quickSearchInput){
    quickSearchInput.addEventListener('input', (e) => filterSavedList(e.target.value));
  }
  
  // NEW: Qwen search on search page
  const qwenSearchBtn = document.getElementById('qwenSearchBtn');
  if(qwenSearchBtn){
    qwenSearchBtn.addEventListener('click', () => {
      const query = document.getElementById('qwenSearchInput').value;
      if(query.trim()) performQwenSearch(query);
    });
    
    // Allow Enter to submit search, Shift+Enter creates new line
    document.getElementById('qwenSearchInput')?.addEventListener('keydown', (e) => {
      if(e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        qwenSearchBtn.click();
      }
    });
  }
});

// 2. Upload Logic
function setupUpload() {
  const form = document.getElementById('uploadForm');
  const fileInput = document.getElementById('fileInput');
  const uploadThrobber = document.getElementById('uploadThrobber');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const files = fileInput.files;
    if(files.length === 0) return alert("Please select a file.");

    uploadThrobber.classList.add('active');

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
    uploadThrobber.classList.remove('active');
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
              meta.textContent = "⏳ Processing audio & visual tags (5-15 minutes)...";
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

      // 2. Transcript Button (for audio/video only)
      if(f.is_audio_or_video) {
        const transcriptBtn = document.createElement('button');
        transcriptBtn.textContent = 'View Transcript';
        transcriptBtn.style.background = '#0099ff';
        transcriptBtn.style.color = 'white';
        transcriptBtn.style.border = 'none';
        transcriptBtn.style.padding = '5px 12px';
        transcriptBtn.style.cursor = 'pointer';
        transcriptBtn.style.marginRight = '10px';
        transcriptBtn.onclick = () => showTranscriptModal(f.key, f.name);
        right.appendChild(transcriptBtn);
      }

      // 3. Delete Button (RESTORED)
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

// Quick filter for saved files (by filename or tags)
function filterSavedList(query) {
  const ul = document.getElementById('savedList');
  if(!ul) return;
  
  const items = ul.querySelectorAll('li');
  const lowerQuery = query.toLowerCase();
  
  items.forEach(item => {
    const text = item.textContent.toLowerCase();
    if(query === '' || text.includes(lowerQuery)) {
      item.style.display = '';
    } else {
      item.style.display = 'none';
    }
  });
}

// Qwen-powered natural language search
async function performQwenSearch(query) {
  const ul = document.getElementById('qwenSearchResults');
  const searchThrobber = document.getElementById('searchThrobber');
  if(!ul) return;
  
  ul.innerHTML = '<li style="color:#ffaa00">Searching with Qwen...</li>';
  searchThrobber.classList.add('active');
  
  try {
    const resp = await fetch(API_BASE + '/qwen_search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ query: query })
    });
    
    const data = await resp.json();
    ul.innerHTML = '';
    searchThrobber.classList.remove('active');
    
    if(!data.success || !data.files || data.files.length === 0) {
      ul.innerHTML = '<li style="color:gray">No matching files found.</li>';
      return;
    }
    
    data.files.forEach(f => {
      const li = document.createElement('li');
      
      // Left side: filename + tags
      const left = document.createElement('div');
      const title = document.createElement('div');
      title.textContent = f.name;
      title.style.fontWeight = 'bold';
      title.style.color = 'white';
      
      const tags = document.createElement('div');
      tags.style.color = '#4ea8ff';
      tags.style.fontSize = '12px';
      tags.textContent = (f.tags && f.tags.length > 0) ? "Tags: " + f.tags.join(', ') : "No tags";
      
      left.appendChild(title);
      left.appendChild(tags);
      
      // Right side: view button
      const btn = document.createElement('button');
      btn.textContent = 'View';
      btn.style.padding = '5px 15px';
      btn.style.cursor = 'pointer';
      btn.style.marginLeft = 'auto';
      btn.onclick = () => window.open(f.url, '_blank');
      
      li.appendChild(left);
      li.appendChild(btn);
      ul.appendChild(li);
    });
  } catch(err) {
    console.error('Qwen search error:', err);
    ul.innerHTML = `<li style="color:red">Search error: ${err.message}</li>`;
    searchThrobber.classList.remove('active');
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

// 5. Transcript Viewer Modal
async function showTranscriptModal(key, fileName) {
  try {
    // Fetch transcript from backend
    const resp = await fetch(API_BASE + '/get_transcript', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ key: key })
    });
    
    const data = await resp.json();
    
    if (!data.success) {
      alert('Error loading transcript: ' + (data.error || 'Unknown error'));
      return;
    }
    
    // Create modal
    const modal = document.createElement('div');
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100%';
    modal.style.height = '100%';
    modal.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
    modal.style.display = 'flex';
    modal.style.justifyContent = 'center';
    modal.style.alignItems = 'center';
    modal.style.zIndex = '9999';
    
    const modalContent = document.createElement('div');
    modalContent.style.backgroundColor = '#222';
    modalContent.style.color = '#fff';
    modalContent.style.padding = '30px';
    modalContent.style.borderRadius = '10px';
    modalContent.style.maxWidth = '700px';
    modalContent.style.maxHeight = '80vh';
    modalContent.style.overflow = 'auto';
    modalContent.style.boxShadow = '0 4px 6px rgba(0, 0, 0, 0.3)';
    
    // Title
    const title = document.createElement('h2');
    title.textContent = 'Transcript: ' + fileName;
    title.style.marginTop = '0';
    title.style.marginBottom = '20px';
    title.style.color = '#4ea8ff';
    modalContent.appendChild(title);
    
    // Transcript text
    const transcriptDiv = document.createElement('div');
    if (data.transcript !== null && data.transcript !== undefined) {
      // Transcript field exists (transcription completed)
      if (data.transcript.length > 0) {
        transcriptDiv.textContent = data.transcript;
        transcriptDiv.style.lineHeight = '1.6';
        transcriptDiv.style.whiteSpace = 'pre-wrap';
        transcriptDiv.style.wordWrap = 'break-word';
      } else {
        // Transcription completed but result is empty
        transcriptDiv.textContent = 'No transcript content available.';
        transcriptDiv.style.color = '#aaa';
        transcriptDiv.style.fontStyle = 'italic';
      }
    } else {
      // Transcription still in progress
      const isVideo = /\.(mp4|mov|avi|mkv)$/i.test(fileName);
      transcriptDiv.textContent = isVideo 
        ? '⏳ Video audio is being transcribed. This typically takes 5-15 minutes. Please check back later.'
        : '⏳ Audio is being transcribed. This typically takes 5-15 minutes. Please check back later.';
      transcriptDiv.style.color = '#ffaa00';
      transcriptDiv.style.fontStyle = 'italic';
    }
    modalContent.appendChild(transcriptDiv);
    
    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.textContent = 'Close';
    closeBtn.style.marginTop = '20px';
    closeBtn.style.padding = '10px 20px';
    closeBtn.style.backgroundColor = '#444';
    closeBtn.style.color = '#fff';
    closeBtn.style.border = 'none';
    closeBtn.style.borderRadius = '5px';
    closeBtn.style.cursor = 'pointer';
    closeBtn.onclick = () => modal.remove();
    modalContent.appendChild(closeBtn);
    
    modal.appendChild(modalContent);
    document.body.appendChild(modal);
    
    // Close on background click
    modal.onclick = (e) => {
      if (e.target === modal) modal.remove();
    };
    
  } catch (err) {
    console.error('Error fetching transcript:', err);
    alert('Failed to load transcript');
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