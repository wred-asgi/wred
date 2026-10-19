document.querySelectorAll('.code-block').forEach(block => {
  const code = block.querySelector('code');
  const actions = block.querySelector('.code-actions');
  if (!code || !actions) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'copy';
  button.textContent = 'Copy';
  button.setAttribute('aria-label', `Copy ${block.querySelector('.code-label').textContent}`);
  let reset;
  button.addEventListener('click', async () => {
    clearTimeout(reset);
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = 'Copied';
      document.getElementById('copy-status').textContent = 'Code copied.';
    } catch {
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = 'Selected';
      document.getElementById('copy-status').textContent = 'Code selected. Use your browser’s copy command.';
    }
    reset = setTimeout(() => { button.textContent = 'Copy'; }, 2000);
  });
  actions.appendChild(button);
});

function findDocs(query) {
  if (typeof DOCS_SEARCH_INDEX === 'undefined') return [];
  const terms = [...new Set((query.toLowerCase().match(/[a-z0-9_./:-]+/g) || [])
    .filter(term => !['a', 'an', 'the', 'how', 'do', 'i', 'to', 'in', 'and', 'with'].includes(term)))];
  if (!terms.length) return [];
  return DOCS_SEARCH_INDEX.map(page => {
    const title = page.title.toLowerCase();
    const text = page.text.toLowerCase();
    if (!terms.every(term => text.includes(term))) return null;
    const heading = page.headings.find(item => terms.every(term => item.title.toLowerCase().includes(term)))
      || page.headings.find(item => terms.some(term => item.title.toLowerCase().includes(term)));
    const score = terms.reduce((total, term) => total
      + (title.includes(term) ? 10 : 0)
      + (page.headings.some(item => item.title.toLowerCase().includes(term)) ? 4 : 0), 0);
    const start = Math.max(0, text.indexOf(terms[0]) - 45);
    return {
      title: page.title,
      url: page.url + (heading ? `#${encodeURIComponent(heading.anchor)}` : ''),
      snippet: (start ? '…' : '') + page.text.slice(start, start + 155) + (start + 155 < page.text.length ? '…' : ''),
      score,
    };
  }).filter(Boolean).sort((a, b) => b.score - a.score || a.title.localeCompare(b.title));
}

const searchInput = document.getElementById('docs-query');
const searchPanel = document.getElementById('search-results');
const searchMatches = document.getElementById('search-matches');
const searchStatus = document.getElementById('search-status');
if (searchInput && searchPanel && searchMatches && searchStatus && typeof DOCS_SEARCH_INDEX !== 'undefined') {
  searchInput.disabled = false;
  function closeSearch() {
    searchPanel.hidden = true;
  }
  function updateSearch() {
    const query = searchInput.value.trim();
    searchMatches.replaceChildren();
    if (query.length < 2) {
      closeSearch();
      return;
    }
    const matches = findDocs(query);
    for (const match of matches.slice(0, 8)) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = match.url;
      const title = document.createElement('strong');
      title.textContent = match.title;
      const description = document.createElement('span');
      description.textContent = match.snippet;
      link.append(title, description);
      item.appendChild(link);
      searchMatches.appendChild(item);
    }
    searchPanel.hidden = false;
    searchStatus.textContent = matches.length
      ? `Showing ${Math.min(matches.length, 8)} of ${matches.length} matching pages.`
      : 'No matching pages. Try a method name or a shorter phrase.';
  }
  searchInput.addEventListener('input', updateSearch);
  searchInput.addEventListener('focus', updateSearch);
  searchInput.addEventListener('keydown', event => {
    const first = searchMatches.querySelector('a');
    if (event.key === 'ArrowDown' && first && !searchPanel.hidden) {
      event.preventDefault();
      event.stopPropagation();
      first.focus();
    } else if (event.key === 'Enter' && first && !searchPanel.hidden) {
      event.preventDefault();
      first.click();
    }
  });
  const searchContainer = searchInput.closest('.docs-search');
  searchContainer.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      searchInput.focus();
      closeSearch();
    }
    const links = [...searchMatches.querySelectorAll('a')];
    const current = links.indexOf(document.activeElement);
    if (current < 0) return;
    if (event.key === 'ArrowDown' && current + 1 < links.length) {
      event.preventDefault();
      links[current + 1].focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (current === 0) searchInput.focus();
      else links[current - 1].focus();
    }
  });
  document.addEventListener('click', event => {
    if (!searchContainer.contains(event.target)) closeSearch();
  });
  searchContainer.addEventListener('focusout', event => {
    if (!searchContainer.contains(event.relatedTarget)) closeSearch();
  });
}
