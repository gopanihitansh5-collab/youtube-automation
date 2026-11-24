import { readFileSync, writeFileSync } from 'node:fs';
const root = new URL('./', import.meta.url);
let html = readFileSync(new URL('source/examples/dial-indicator/dial-indicator-light.html', root), 'utf8');
const hook = `
window.renderFrame = (seconds) => {
  touring = false; visible = false; cancelAnimationFrame(frame); frame = 0;
  const phase = Math.max(0, Math.min(7.999, seconds)) / 8;
  const segment = Math.min(1, Math.floor(phase * 2));
  const t = Math.min(1, Math.max(0, phase * 2 - segment));
  const ease = t*t*(3-2*t);
  x = stops[segment] + (stops[segment+1]-stops[segment])*ease;
  tip.at = heightUnder(x); tip.rate = 0; draw();
  document.querySelector('.time-label').textContent = 'MODEL COORDINATES · NOT A CALIBRATED MEASUREMENT';
};
`;
html = html.replace('draw();\n</script>', `${hook}\ndraw();\nwindow.renderFrame(0);\n</script>`);
if (!html.includes('window.renderFrame(0)')) throw Error('Upstream hook changed');
html = html.replace('</head>', `<style>
html,body{width:720px;height:1280px;overflow:hidden;background:#f2f2ef}
.iso-page{width:636px;margin:0 auto;padding-top:82px}
.preview-kicker{font:600 18px system-ui;letter-spacing:.14em;color:#57575a}
h1{font:700 52px/1.08 system-ui;color:#18181a;letter-spacing:-.04em;margin:18px 0 22px}
.deck{font:24px/1.4 system-ui;color:#57575a;margin:0 0 28px}
.iso-plate{padding:52px 12px 44px}
.iso-plate-corner{font-size:12px}
.iso-plate-corner[data-corner=hint]{display:none}
.iso-plate-corner[data-corner=readout]{font-size:17px;left:0;right:auto}
.iso-legend{font:20px/1.4 system-ui;color:#57575a}
.iso-keys{display:none}.iso-caption{display:block;margin-top:22px}
.time-label{font:13px/1.4 system-ui;letter-spacing:.05em;color:#57575a;margin-top:28px}
.license-note{font:14px/1.4 system-ui;color:#57575a;margin-top:38px}
</style></head>`);
html = html.replace('<main class="iso-page">', `<main class="iso-page"><div class="preview-kicker">ANATOMY · TOOLKIT TEST</div><h1>A tiny movement.<br>A visible reading.</h1><p class="deck">A moving carriage brings three blocks under one contact probe.</p>`);
html = html.replace(/<span class="iso-caption">[\s\S]*?<\/span>/, '<span class="iso-caption">The contact probe rises and falls as each block moves beneath it. The dial follows the same geometric model.</span>');
html = html.replace('</main>', '<p class="time-label"></p><p class="license-note">Adapted from Anatomy dial-indicator example<br>MIT © 2026 Ryan · wheresryan22/anatomy<br>Silent technical preview, not an original finished episode.</p></main>');
writeFileSync(new URL('vertical-preview.html', root), html);
console.log('wrote vertical-preview.html');
