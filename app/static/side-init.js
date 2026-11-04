/* Runs before first paint (loaded without defer): restore the collapsed sidebar so it doesn't flash open. */
try { if (localStorage.getItem('tt-side') === 'collapsed') document.documentElement.classList.add('side-collapsed'); } catch (e) { /* private mode */ }
