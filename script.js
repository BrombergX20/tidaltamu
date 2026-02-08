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
      btn.style.marginLeft = 'auto';
      btn.style.padding = '5px 15px';
      btn.style.cursor = 'pointer';
      btn.onclick = () => window.open(f.url, '_blank');

      li.appendChild(left);
      li.appendChild(btn);
      ul.appendChild(li);
    });

  } catch (err) {
    console.error(err);
    ul.innerHTML = `<li style="color:red">Connection Error. Is Server running?</li>`;
  }
}