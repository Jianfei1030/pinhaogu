// test-only-initNewsToggle.js
console.log('TEST: Loading test-only-initNewsToggle.js');
function initNewsToggle() {
  console.log('TEST: initNewsToggle defined');
  const header = document.getElementById('newsHeader');
  const body = document.getElementById('newsBody');
  if (header && body) {
    header.style.cursor = 'pointer';
    header.onclick = function() {
      body.style.display = body.style.display === 'none' ? 'block' : 'none';
    };
  }
}
console.log('TEST: After definition, typeof initNewsToggle:', typeof initNewsToggle);
window.initNewsToggleTestLoaded = true;
